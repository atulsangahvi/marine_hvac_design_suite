"""Evaporator thermal / hydraulic module for Marine Chiller Suite v7.

This module improves the earlier screening module by adding:
- water/glycol property estimate;
- tube-side Gnielinski/Darcy calculations;
- DX refrigerant evaporation screening with correct Bo=q''/(G*h_fg);
- Müller-Steinhagen-Heck style two-phase pressure drop decomposition;
- Kern/Bell-Delaware-style shell-side water/glycol screening for baffled shells;
- air-cooled DX coil screening with separate air-side heat-transfer and pressure-drop checks.

Important: These are engineering screening calculations. Final manufacture still requires
validation against test data, supplier software, ASHRAE/VDI/HTRI/CoilDesigner style models,
and pressure-vessel/mechanical design checks.
"""
from __future__ import annotations

import math
from typing import Dict, List, Optional
import pandas as pd

try:
    from CoolProp.CoolProp import PropsSI
except Exception:  # pragma: no cover
    PropsSI = None

from .thermo import water_flow_m3h
from .correlations import bell_delaware_screening, BellKernInput, cooper_pool_boiling

G0 = 9.80665
P_ATM = 101325.0


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def glycol_props(glycol_pct: float = 0.0, temp_c: float = 7.0, fluid: str = "Water") -> Dict[str, float]:
    """Approximate water/ethylene-glycol properties for preliminary HVAC design.

    The formula is smooth and conservative. For final design use ASHRAE tables or
    CoolProp incompressible fluid properties.
    """
    # v14: water baseline now uses temperature-dependent correlations (Kell density,
    # Vogel viscosity, quadratic k, quartic cp) instead of linear guesses. The old
    # exp(-0.033·ΔT) viscosity over-predicted chilled-water viscosity trends and the
    # density slope had the wrong sign below 20 °C.
    from .correlations import water_properties
    g = _clamp(glycol_pct, 0.0, 60.0) / 100.0
    w = water_properties(temp_c, seawater=False)
    rho = w["rho"] * (1.0 + 0.135 * g)               # EG density ratio ~1.135 at 100% eq.
    cp = w["cp"] * (1.0 - 0.42 * g + 0.06 * g * g)   # ASHRAE EG cp trend
    k = w["k"] * (1.0 - 0.55 * g + 0.12 * g * g)     # EG conductivity trend
    mu = w["mu"] * math.exp(4.2 * g * (1.0 + 0.012 * max(20.0 - temp_c, 0.0) * g))
    pr = cp * mu / max(k, 1e-12)
    return {"rho": rho, "cp": cp, "k": k, "mu": mu, "pr": pr}


def friction_factor_churchill(re: float, roughness_m: float, d_m: float) -> float:
    re = max(re, 1e-9)
    if re < 2300:
        return 64.0 / re
    eod = roughness_m / max(d_m, 1e-12)
    a = (2.457 * math.log(1.0 / ((7.0 / re) ** 0.9 + 0.27 * eod))) ** 16
    b = (37530.0 / re) ** 16
    return 8.0 * (((8.0 / re) ** 12 + 1.0 / ((a + b) ** 1.5)) ** (1.0 / 12.0))


def gnielinski_htc(mdot_kg_s: float, rho: float, mu: float, k: float, cp: float, d_m: float,
                   flow_area_m2: float, length_m: float = 1.0, roughness_m: float = 1.5e-6) -> Dict[str, float]:
    if flow_area_m2 <= 0 or d_m <= 0:
        return {"h": 0.0, "re": 0.0, "pr": 0.0, "v": 0.0, "f": 0.0, "nu": 0.0}
    v = mdot_kg_s / max(rho * flow_area_m2, 1e-12)
    re = rho * v * d_m / max(mu, 1e-12)
    pr = cp * mu / max(k, 1e-12)
    if re < 2300:
        gz = re * pr * d_m / max(length_m, d_m)
        nu = max(3.66, 1.86 * (max(gz, 1e-12)) ** (1.0 / 3.0))
        f = 64.0 / max(re, 1e-12)
    else:
        f = friction_factor_churchill(re, roughness_m, d_m)
        nu = ((f / 8.0) * (re - 1000.0) * pr) / max(1.0 + 12.7 * math.sqrt(f / 8.0) * (pr ** (2/3) - 1.0), 1e-12)
    h = nu * k / max(d_m, 1e-12)
    return {"h": h, "re": re, "pr": pr, "v": v, "f": f, "nu": nu}


def darcy_dp_kpa(mdot_kg_s: float, rho: float, mu: float, d_m: float, length_m: float,
                 flow_area_m2: float, minor_k: float = 2.0, roughness_m: float = 1.5e-6) -> Dict[str, float]:
    h = gnielinski_htc(mdot_kg_s, rho, mu, 0.6, 4180.0, d_m, flow_area_m2, length_m, roughness_m)
    v, re, f = h["v"], h["re"], h["f"]
    dp_f = f * length_m / max(d_m, 1e-12) * 0.5 * rho * v * v
    dp_m = minor_k * 0.5 * rho * v * v
    return {"dp_kpa": (dp_f + dp_m) / 1000.0, "dp_friction_kpa": dp_f/1000.0, "dp_minor_kpa": dp_m/1000.0, "v": v, "re": re, "f": f}


def _sat_props(ref: str, evap_temp_c: float) -> Dict[str, float]:
    if PropsSI is None:
        return {"rho_l": 1100.0, "rho_v": 25.0, "mu_l": 0.00018, "mu_v": 1.2e-5, "k_l": 0.085, "cp_l": 1400.0, "h_fg": 180000.0, "p_sat": 400000.0}
    T = evap_temp_c + 273.15
    return {
        "rho_l": float(PropsSI("D", "T", T, "Q", 0, ref)),
        "rho_v": float(PropsSI("D", "T", T, "Q", 1, ref)),
        "mu_l": float(PropsSI("V", "T", T, "Q", 0, ref)),
        "mu_v": float(PropsSI("V", "T", T, "Q", 1, ref)),
        "k_l": float(PropsSI("L", "T", T, "Q", 0, ref)),
        "cp_l": float(PropsSI("C", "T", T, "Q", 0, ref)),
        "h_fg": float(PropsSI("H", "T", T, "Q", 1, ref) - PropsSI("H", "T", T, "Q", 0, ref)),
        "p_sat": float(PropsSI("P", "T", T, "Q", 1, ref)),
    }


def shah_like_evaporation_multiplier(x: float, q_flux_w_m2: float, mass_flux: float, h_fg_j_kg: float,
                                     rho_l: float, rho_v: float, h_liq: float) -> Dict[str, float]:
    """Dimensionally corrected Shah-style screening multiplier.

    Correct boiling number: Bo = q'' / (G h_fg).
    """
    x = _clamp(x, 0.001, 0.999)
    co = ((1.0 - x) / x) ** 0.8 * (rho_v / max(rho_l, 1e-12)) ** 0.5
    bo = q_flux_w_m2 / max(mass_flux * h_fg_j_kg, 1e-12)
    if bo > 0.0011:
        f_nb = 230.0 * bo ** 0.5
        f_cb = 1.8 * max(co, 1e-9) ** -0.8
        mult = max(f_nb, f_cb)
    else:
        mult = 1.8 * max(co, 1e-9) ** -0.8 if co <= 0.65 else 1.0 + 0.8 * math.exp(1.0 - co)
    mult = _clamp(mult, 1.2, 15.0)
    return {"h_tp": h_liq * mult, "bo": bo, "co": co, "mult": mult}


def muller_steinhagen_heck_dp(dp_lo_pa: float, dp_vo_pa: float, x: float) -> float:
    x = _clamp(x, 0.001, 0.999)
    g_term = dp_lo_pa + 2.0 * (dp_vo_pa - dp_lo_pa) * x
    return g_term * (1.0 - x) ** (1.0 / 3.0) + dp_vo_pa * x ** 3


def dx_refrigerant_tube_evaporation(ref: str, evap_temp_c: float, mdot_ref_kg_s: float,
                                    tube_id_m: float, tubes_per_pass: int, length_m: float,
                                    heat_kw: float, area_i_m2: float,
                                    x_in: float = 0.20, x_out: float = 0.95) -> Dict[str, float]:
    """Refrigerant-in-tube DX evaporation HTC and pressure-drop screening.

    Uses liquid-only Gnielinski for base h_l, a Shah-style two-phase multiplier, and
    MSH pressure-drop interpolation with acceleration term.
    """
    sp = _sat_props(ref, evap_temp_c)
    flow_area = max(tubes_per_pass, 1) * math.pi * tube_id_m**2 / 4.0
    G = mdot_ref_kg_s / max(flow_area, 1e-12)
    q_flux = heat_kw * 1000.0 / max(area_i_m2, 1e-12)
    x_avg = _clamp((x_in + x_out) / 2.0, 0.02, 0.98)
    # v14: Shah's correlation defines h_l on the LIQUID-FRACTION basis, i.e. the
    # superficial liquid flow G(1-x) flowing alone: Re_l = G(1-x)·d/μ_l. The
    # previous code used total flow as liquid, which mis-states the multiplier
    # basis and skews h_tp with quality.
    h_liq = gnielinski_htc(mdot_ref_kg_s * (1.0 - x_avg), sp["rho_l"], sp["mu_l"], sp["k_l"], sp["cp_l"], tube_id_m, flow_area, length_m)
    evap = shah_like_evaporation_multiplier(x_avg, q_flux, G, sp["h_fg"], sp["rho_l"], sp["rho_v"], h_liq["h"])

    # liquid-only and vapor-only friction dp basis over full path
    dp_lo = darcy_dp_kpa(mdot_ref_kg_s, sp["rho_l"], sp["mu_l"], tube_id_m, length_m, flow_area, minor_k=0.5)
    dp_vo = darcy_dp_kpa(mdot_ref_kg_s, sp["rho_v"], sp["mu_v"], tube_id_m, length_m, flow_area, minor_k=0.5)
    dp_fric_pa = muller_steinhagen_heck_dp(dp_lo["dp_friction_kpa"]*1000, dp_vo["dp_friction_kpa"]*1000, x_avg)
    # acceleration dp approximately from quality change
    dp_acc_pa = max(0.0, G**2 * ((x_out**2/sp["rho_v"] + (1-x_out)**2/sp["rho_l"]) - (x_in**2/sp["rho_v"] + (1-x_in)**2/sp["rho_l"])))
    dp_minor_pa = 2.0 * 0.5 * (sp["rho_v"] * (G/max(sp["rho_v"],1e-12))**2)  # return bends/distributor placeholder
    return {
        "ref_mass_flux_kg_m2s": G,
        "ref_q_flux_w_m2": q_flux,
        "ref_boiling_number": evap["bo"],
        "ref_convection_number": evap["co"],
        "ref_base_liquid_h_w_m2k": h_liq["h"],
        "ref_evap_htc_w_m2k": evap["h_tp"],
        "ref_evap_multiplier": evap["mult"],
        "ref_dp_friction_kpa": dp_fric_pa/1000.0,
        "ref_dp_acceleration_kpa": dp_acc_pa/1000.0,
        "ref_dp_minor_kpa": dp_minor_pa/1000.0,
        "ref_dp_total_kpa": (dp_fric_pa + dp_acc_pa + dp_minor_pa)/1000.0,
    }


def kern_shell_side_water(mdot_kg_s: float, props: Dict[str, float], shell_id_m: float, tube_od_m: float,
                          tube_pitch_m: float, baffle_spacing_m: float, baffle_cut_pct: float,
                          tube_count: int, tube_layout: str = "triangular") -> Dict[str, float]:
    """Kern/Bell-Delaware style shell-side water/glycol estimate.

    This is much better than a pure guessed shell velocity, but still not a full TEMA/HTRI
    implementation. It calculates cross-flow area, equivalent diameter, ideal j/H factor
    style HTC, and applies practical leakage/window/bypass corrections.
    """
    p = max(tube_pitch_m, 1.05*tube_od_m)
    ds = max(shell_id_m, tube_od_m*5)
    bs = _clamp(baffle_spacing_m, 0.08, 1.5)
    cut = _clamp(baffle_cut_pct, 15.0, 45.0)
    clearance = max(p - tube_od_m, 1e-5)
    # Cross-flow free area at shell centerline (Kern estimate)
    As = max(1e-5, ds * bs * clearance / p)
    v = mdot_kg_s / max(props["rho"] * As, 1e-12)
    # Equivalent diameter: triangular/square pitch approximate
    if tube_layout.lower().startswith("tri"):
        de = max(0.003, 1.10 * (p*p - 0.917*tube_od_m*tube_od_m) / tube_od_m)
    else:
        de = max(0.003, 1.27 * (p*p - 0.785*tube_od_m*tube_od_m) / tube_od_m)
    re = props["rho"] * v * de / max(props["mu"], 1e-12)
    pr = props["pr"]
    # Kern shell-side coefficient form
    if re < 100:
        jh = 0.9 * max(re, 1.0)**-0.5
    elif re < 1000:
        jh = 0.52 * re**-0.5
    else:
        jh = 0.36 * re**-0.55
    h_ideal = jh * re * pr**(1/3) * props["k"] / max(de, 1e-12)
    # v8: delegate correction-factor calculation to common Bell-Delaware screening core.
    bd = bell_delaware_screening(BellKernInput(
        mdot_kg_s=mdot_kg_s, rho=props["rho"], mu=props["mu"], cp=props["cp"], k=props["k"],
        shell_id_m=ds, tube_od_m=tube_od_m, pitch_m=p, baffle_spacing_m=bs,
        baffle_cut_pct=cut, tube_count=tube_count, layout=tube_layout
    ))
    return bd


def shell_tube_evaporator_screening(capacity_kw: float, chw_in_c: float, chw_out_c: float,
                                    fluid: str = "Water", glycol_pct: float = 0.0,
                                    evap_temp_c: float = 2.0, tube_od_mm: float = 15.88,
                                    tube_length_m: float = 1.2, tube_count: int = 80,
                                    tube_passes: int = 2, u_w_m2k: float = 0.0,
                                    tube_wall_mm: float = 0.8,
                                    refrigerant_in_tubes: bool = True,
                                    refrigerant_mass_flow_kg_s: Optional[float] = None,
                                    refrigerant: str = "R134a",
                                    shell_id_mm: Optional[float] = None,
                                    baffle_spacing_mm: Optional[float] = None,
                                    baffle_cut_pct: float = 25.0,
                                    pitch_ratio: float = 1.25,
                                    tube_layout: str = "triangular",
                                    water_flow_m3h_input: Optional[float] = None,
                                    max_water_dp_kpa: float = 80.0,
                                    max_refrigerant_dp_kpa: float = 80.0,
                                    target_superheat_k: float = 6.0) -> dict:
    """Screen a shell-and-tube DX or flooded evaporator with calculated U when possible.

    v11 adds user-entered water/glycol flow, heat-capacity/effectiveness analysis,
    refrigerant and water pressure-drop status, and refrigerant pressure-drop effect
    on effective evaporating temperature.
    """
    props = glycol_props(glycol_pct, 0.5 * (chw_in_c + chw_out_c), fluid)
    cp_kj = props["cp"] / 1000.0
    rho = props["rho"]
    design_flow_m3h = water_flow_m3h(capacity_kw, max(chw_in_c - chw_out_c, 0.1), cp_kj, rho)
    flow_m3h = float(water_flow_m3h_input) if water_flow_m3h_input and water_flow_m3h_input > 0 else design_flow_m3h
    mdot_w = flow_m3h * rho / 3600.0
    chw_out_from_flow_c = chw_in_c - capacity_kw / max(mdot_w * cp_kj, 1e-12)

    do = tube_od_mm / 1000.0
    di = max(0.001, (tube_od_mm - 2.0 * tube_wall_mm) / 1000.0)
    tubes_per_pass = max(1, int(tube_count) // max(1, int(tube_passes)))
    tube_flow_area = tubes_per_pass * math.pi * di * di / 4.0
    area_o = math.pi * do * tube_length_m * tube_count
    area_i = math.pi * di * tube_length_m * tube_count
    pitch = max(pitch_ratio * do, 1.05*do)
    bundle_od = math.sqrt(max(tube_count, 1) / 0.866) * pitch
    shell_id_m = (shell_id_mm/1000.0) if shell_id_mm else bundle_od + max(0.035, 0.12*bundle_od)
    baffle_spacing_m = (baffle_spacing_mm/1000.0) if baffle_spacing_mm else max(0.10, min(0.5*shell_id_m, tube_length_m/6.0))

    dt1 = max(chw_in_c - evap_temp_c, 0.1)
    dt2 = max(chw_out_c - evap_temp_c, 0.1)
    lmtd = (dt1 - dt2) / math.log(dt1 / dt2) if abs(dt1 - dt2) > 1e-9 else dt1

    notes: List[str] = []
    k_wall = 330.0  # copper/CuNi rough default; final selected material should override
    rfo = 0.00018
    rfi = 0.00018

    if refrigerant_in_tubes:
        # water/glycol shell side; refrigerant tube side
        shell = kern_shell_side_water(mdot_w, props, shell_id_m, do, pitch, baffle_spacing_m, baffle_cut_pct, tube_count, tube_layout)
        h_water = shell["shell_h_corrected_w_m2k"]
        if refrigerant_mass_flow_kg_s is None:
            sat = _sat_props(refrigerant, evap_temp_c)
            refrigerant_mass_flow_kg_s = capacity_kw*1000.0 / max(sat["h_fg"]*0.75, 1.0)
        refcalc = dx_refrigerant_tube_evaporation(refrigerant, evap_temp_c, refrigerant_mass_flow_kg_s, di, tubes_per_pass, tube_length_m*tube_passes, capacity_kw, area_i)
        h_ref_i = refcalc["ref_evap_htc_w_m2k"]
        # Overall U on outside area basis
        r_wall_o = do * math.log(do/di) / max(2.0*k_wall, 1e-12)
        Uo_calc = 1.0 / max(1.0/h_water + rfo + r_wall_o + (do/di)*(1.0/h_ref_i + rfi), 1e-12)
        dp_used = shell["shell_dp_kpa"]
        velocity_used = shell["shell_velocity_ms"]
        h_water_label = "shell-side water/glycol"
        notes.append("DX arrangement: water/glycol shell side by Kern/Bell-style correction; refrigerant tube side by Shah-style evaporation and MSH pressure drop.")
    else:
        # flooded/shell-side refrigerant; water in tubes
        hwt = gnielinski_htc(mdot_w, rho, props["mu"], props["k"], props["cp"], di, tube_flow_area, tube_length_m*tube_passes)
        dp_w = darcy_dp_kpa(mdot_w, rho, props["mu"], di, tube_length_m*tube_passes, tube_flow_area, minor_k=2.0*tube_passes)
        h_water = hwt["h"]
        # Outside pool boiling by Cooper correlation with optional enhanced-tube multiplier.
        q_flux = capacity_kw*1000/max(area_o, 1e-12)
        try:
            if PropsSI is not None:
                tc = PropsSI("Tcrit", refrigerant) - 273.15
                pc = PropsSI("Pcrit", refrigerant)
                ps = PropsSI("P", "T", evap_temp_c+273.15, "Q", 1, refrigerant)
                mw = PropsSI("M", refrigerant) * 1000.0
                pred = ps/max(pc,1.0)
            else:
                pred, mw = 0.15, 100.0
        except Exception:
            pred, mw = 0.15, 100.0
        enhanced_mult = 1.0
        h_ref_o = cooper_pool_boiling(pred, mw, q_flux) * enhanced_mult
        h_ref_o = _clamp(h_ref_o, 900.0, 12000.0)
        r_wall_o = do * math.log(do/di) / max(2.0*k_wall, 1e-12)
        Uo_calc = 1.0 / max(1.0/h_ref_o + rfo + r_wall_o + (do/di)*(1.0/h_water + rfi), 1e-12)
        dp_used = dp_w["dp_kpa"]
        velocity_used = hwt["v"]
        h_water_label = "tube-side water/glycol"
        shell = {"shell_h_corrected_w_m2k": h_ref_o, "shell_dp_kpa": 0.0, "shell_re": 0.0, "shell_velocity_ms": 0.0}
        refcalc = {"ref_evap_htc_w_m2k": h_ref_o, "ref_dp_total_kpa": 0.0, "ref_boiling_number": 0.0, "ref_evap_multiplier": 1.0}
        notes.append("Flooded/shell-side refrigerant screening: water/glycol tube side by Gnielinski/Darcy; shell-side boiling by Cooper pool-boiling screening. Enhanced evaporator tubes still require supplier/test multiplier.")

    U_used = Uo_calc if u_w_m2k <= 0 else u_w_m2k
    q_possible_kw = U_used * area_o * lmtd / 1000.0

    # Heat-capacity-rate / effectiveness view. For a boiling refrigerant at nearly
    # constant temperature, refrigerant C is effectively very large, so water/glycol
    # is normally Cmin and the limiting sensible side.
    c_water_kw_k = mdot_w * cp_kj
    c_refrigerant_kw_k_equiv = 1.0e9 if refrigerant_in_tubes else 1.0e9
    c_min_kw_k = min(c_water_kw_k, c_refrigerant_kw_k_equiv)
    c_max_kw_k = max(c_water_kw_k, c_refrigerant_kw_k_equiv)
    capacity_ratio = c_min_kw_k / max(c_max_kw_k, 1e-12)
    q_max_kw = c_min_kw_k * max(chw_in_c - evap_temp_c, 0.0)
    effectiveness = capacity_kw / max(q_max_kw, 1e-12)
    limiting_side = "water/glycol side" if c_water_kw_k <= c_refrigerant_kw_k_equiv else "refrigerant side"

    velocity_status = "OK" if 0.6 <= velocity_used <= 2.8 else ("LOW" if velocity_used < 0.6 else "HIGH")
    dp_status = "OK" if dp_used <= max_water_dp_kpa else "HIGH"
    ref_dp = float(refcalc.get("ref_dp_total_kpa", 0.0))
    ref_dp_status = "OK" if ref_dp <= max_refrigerant_dp_kpa else "HIGH"

    # Convert refrigerant evaporator pressure drop into equivalent saturation-temperature loss.
    evap_temp_drop_k = 0.0
    effective_evap_temp_c = evap_temp_c
    try:
        if PropsSI is not None and ref_dp > 0:
            p0 = PropsSI("P", "T", evap_temp_c + 273.15, "Q", 1, refrigerant)
            p1 = max(1000.0, p0 - ref_dp*1000.0)
            effective_evap_temp_c = PropsSI("T", "P", p1, "Q", 1, refrigerant) - 273.15
            evap_temp_drop_k = evap_temp_c - effective_evap_temp_c
    except Exception:
        evap_temp_drop_k = 0.0
        effective_evap_temp_c = evap_temp_c
    superheat_assessment = "OK" if target_superheat_k >= 4.0 and ref_dp_status == "OK" else "CHECK"
    if ref_dp_status != "OK":
        notes.append("High refrigerant pressure drop reduces effective evaporating temperature at compressor suction and can increase superheat, reduce capacity and increase compressor lift.")
    if u_w_m2k > 0:
        notes.append("User-entered U overrides calculated U; calculated U is still shown for audit.")

    return {
        "capacity_required_kw": round(capacity_kw, 3),
        "capacity_possible_kw": round(q_possible_kw, 3),
        "calculated_Uo_w_m2k": round(Uo_calc, 1),
        "U_used_w_m2k": round(U_used, 1),
        "area_m2": round(area_o, 3),
        "lmtd_k": round(lmtd, 3),
        "water_flow_m3h": round(flow_m3h, 3),
        "water_design_flow_m3h_at_entered_deltaT": round(design_flow_m3h, 3),
        "estimated_leaving_water_from_flow_c": round(chw_out_from_flow_c, 2),
        "water_heat_capacity_rate_kw_per_k": round(c_water_kw_k, 3),
        "refrigerant_heat_capacity_rate_kw_per_k": "phase-change/very high",
        "capacity_ratio_cmin_cmax": round(capacity_ratio, 6),
        "limiting_side": limiting_side,
        "max_heat_transfer_possible_kw_by_cmin": round(q_max_kw, 3),
        "effectiveness_based_on_cmin": round(effectiveness, 3),
        "water_side_location": h_water_label,
        "water_htc_w_m2k": round(h_water, 0),
        "water_velocity_ms": round(velocity_used, 3),
        "water_velocity_status": velocity_status,
        "water_dp_kpa_est": round(dp_used, 3),
        "water_dp_status": dp_status,
        "bundle_od_mm_est": round(bundle_od*1000, 1),
        "shell_id_mm_est": round(shell_id_m*1000, 1),
        "baffle_spacing_mm": round(baffle_spacing_m*1000, 1),
        "shell_side_est_re": round(shell.get("shell_re", 0.0), 0),
        "shell_side_htc_w_m2k": round(shell.get("shell_h_corrected_w_m2k", 0.0), 0),
        "refrigerant_htc_w_m2k": round(refcalc.get("ref_evap_htc_w_m2k", 0.0), 0),
        "refrigerant_boiling_number": round(refcalc.get("ref_boiling_number", 0.0), 6),
        "refrigerant_evap_multiplier": round(refcalc.get("ref_evap_multiplier", 1.0), 2),
        "refrigerant_dp_kpa_est": round(ref_dp, 3),
        "refrigerant_dp_status": ref_dp_status,
        "effective_evaporating_temp_after_ref_dp_c": round(effective_evap_temp_c, 2),
        "evaporating_temp_loss_due_to_ref_dp_k": round(evap_temp_drop_k, 3),
        "target_superheat_k": round(target_superheat_k, 2),
        "superheat_assessment": superheat_assessment,
        "status": "OK" if q_possible_kw >= capacity_kw and velocity_status != "HIGH" and dp_status == "OK" and ref_dp_status == "OK" and effectiveness <= 1.0 else "CHECK",
        "engineering_note": " ".join(notes),
    }


# --- Air-cooled coil psychrometric helpers ---
def _psat_water_pa(T_C: float) -> float:
    return 611.21 * math.exp((18.678 - T_C/234.5) * (T_C/(257.14 + T_C)))


def _W_from_T_RH(T_C: float, RH: float, P: float = P_ATM) -> float:
    pv = _clamp(RH, 0.0, 1.0) * _psat_water_pa(T_C)
    return 0.62198 * pv / max(P - pv, 1.0)


def _W_from_T_WB(Tdb_C: float, Twb_C: float, P: float = P_ATM) -> float:
    W_sat_wb = _W_from_T_RH(Twb_C, 1.0, P)
    h_fg_wb = 2501000.0 - 2369.0*Twb_C
    numer = W_sat_wb*(h_fg_wb + 1860.0*Twb_C) - 1006.0*(Tdb_C - Twb_C)
    denom = h_fg_wb + 1860.0*Tdb_C
    return max(0.0, numer/max(denom, 1e-12))


def _h_moist(T_C: float, W: float) -> float:
    return 1006.0*T_C + W*(2501000.0 + 1860.0*T_C)


def _T_from_h_W(h: float, W: float) -> float:
    return (h - W*2501000.0)/max(1006.0 + 1860.0*W, 1e-12)


def airside_wang_style_htc_dp(face_velocity: float, rows: int, fpi: float, tube_od_m: float = 0.00952,
                              fin_thickness_m: float = 0.00012) -> Dict[str, float]:
    """Compact-fin air-side screening based on j/f ranges from Wang/Kays-London practice.

    Not a substitute for exact fin pattern data. It gives plausible trend with velocity,
    FPI and rows and exposes j and f for audit.
    """
    rho = 1.18
    mu = 1.85e-5
    cp = 1006.0
    k = 0.026
    pr = cp*mu/k
    # v14: compact heat-exchanger j/f data (Kays-London, Wang) are defined at the
    # velocity through the MINIMUM free-flow area, not the face velocity. Using
    # face velocity under-predicted both HTC and ΔP by (1/σ) and (1/σ²) factors.
    sigma = _clamp(0.72 - 0.010*(fpi-12.0) - fin_thickness_m*fpi/0.0254, 0.35, 0.85)
    v_max = face_velocity / max(sigma, 0.1)
    re_d = rho*v_max*tube_od_m/max(mu,1e-12)
    # j decreases with Re and increases slightly with more fins/rows
    j = 0.108 * max(re_d, 1.0)**(-0.29) * (fpi/12.0)**0.12 * (rows/4.0)**0.08
    h = j * rho * v_max * cp / max(pr**(2/3), 1e-12)
    # friction factor, conservative for wavy/louvered fin packs
    f = 0.33 * max(re_d, 1.0)**(-0.20) * (fpi/12.0)**0.35 * (rows/4.0)**0.25
    # Core friction + entrance/exit acceleration, both on max-velocity dynamic head
    dp = (4.0*f*rows + (1.0/sigma**2 - 1.0)*sigma**2) * 0.5*rho*v_max**2
    return {"air_re_d": re_d, "air_j": j, "air_f": f, "air_htc_w_m2k": h, "air_dp_pa": dp,
            "free_area_ratio": sigma, "air_v_max_ms": v_max}


def air_cooled_dx_coil_screening(capacity_kw: float, air_flow_m3s: float, db_in_c: float, wb_in_c: float,
                                 evap_temp_c: float, rows: int, face_area_m2: float, fpi: float = 12.0,
                                 circuit_count: int = 4, tube_type: str = "Smooth",
                                 input_method: str = "DB+WB", rh_pct: float = 50.0,
                                 face_width_m: Optional[float] = None, face_height_m: Optional[float] = None,
                                 face_velocity_input_ms: Optional[float] = None,
                                 tube_od_mm: float = 9.52, tube_wall_mm: float = 0.35,
                                 tube_pitch_longitudinal_mm: float = 22.0,
                                 tube_pitch_transverse_mm: float = 25.4,
                                 refrigerant: str = "R134a", refrigerant_mass_flow_kg_s: Optional[float] = None,
                                 condensing_temp_c: float = 45.0, target_superheat_k: float = 6.0,
                                 max_air_dp_pa: float = 180.0, max_refrigerant_dp_kpa: float = 80.0) -> dict:
    """Air-cooled DX coil screening with geometry, air-flow, psychrometric and refrigerant DP checks."""
    if face_width_m and face_height_m and face_width_m > 0 and face_height_m > 0:
        face_area_m2 = face_width_m * face_height_m
    if face_velocity_input_ms and face_velocity_input_ms > 0:
        air_flow_m3s = face_velocity_input_ms * max(face_area_m2, 1e-9)
    face_velocity = air_flow_m3s / max(face_area_m2, 1e-9)
    if input_method == "DB+RH":
        W_in = _W_from_T_RH(db_in_c, rh_pct/100.0)
        # equivalent WB not solved exactly; report RH mode separately
        wb_in_c = wb_in_c
    else:
        W_in = _W_from_T_WB(db_in_c, min(wb_in_c, db_in_c))
    h_in = _h_moist(db_in_c, W_in)
    rho_air = 1.18
    mdot_air = air_flow_m3s*rho_air
    W_adp = _W_from_T_RH(evap_temp_c, 1.0)
    h_adp = _h_moist(evap_temp_c, W_adp)
    required_dh = capacity_kw*1000.0/max(mdot_air, 1e-12)
    h_out_target = h_in - required_dh
    bf_required = (h_out_target - h_adp)/max(h_in - h_adp, 1e-12)
    bf_required = _clamp(bf_required, 0.01, 0.99)
    ntu_required = -math.log(bf_required)

    tube_od_m = tube_od_mm/1000.0
    tube_id_m = max(0.001, (tube_od_mm - 2.0*tube_wall_mm)/1000.0)
    air = airside_wang_style_htc_dp(face_velocity, rows, fpi, tube_od_m=tube_od_m)
    # Estimate available UA from finned area density. Typical coils have large outside area.
    area_density = 55.0 * (fpi/12.0) * max(rows,1)  # m2 outside per m2 face, rough compact coil value
    Ao = face_area_m2 * area_density
    eta_o = _clamp(0.78 - 0.006*(fpi-12.0), 0.55, 0.90)
    UA_air = air["air_htc_w_m2k"] * eta_o * Ao
    ntu_available = UA_air / max(mdot_air*1006.0, 1e-12)
    bf_available = math.exp(-ntu_available)
    h_out = h_adp + bf_available*(h_in - h_adp)
    W_out = W_adp + bf_available*(W_in - W_adp)
    T_out = _T_from_h_W(h_out, W_out)
    q_possible_kw = mdot_air*(h_in-h_out)/1000.0

    # Refrigerant side screening by tube type
    tube_factor = {"Smooth": 1.0, "Microfin": 1.35, "Microchannel/flat": 1.55}.get(tube_type, 1.0)
    refrig_dp_index = {"Smooth": 1.0, "Microfin": 1.25, "Microchannel/flat": 1.55}.get(tube_type, 1.0)
    sensible_ref_kw = mdot_air*1006.0*(db_in_c-T_out)/1000.0
    latent_kw = max(0.0, q_possible_kw - sensible_ref_kw)
    shr = _clamp(sensible_ref_kw/max(q_possible_kw,1e-12), 0.0, 1.0)
    face_status = "OK" if 1.5 <= face_velocity <= 3.2 else ("LOW" if face_velocity < 1.5 else "HIGH")
    dp_status = "OK" if air["air_dp_pa"] <= max_air_dp_pa else "HIGH"
    row_status = "OK" if rows >= max(2, math.ceil(ntu_required/0.55)) else "LOW_ROWS"

    # Refrigerant side screening based on coil geometry. This intentionally mirrors
    # the standalone air-coil app idea: width, height and tube pitch define tube count
    # and therefore refrigerant circuit length/area.
    tubes_per_row = max(1, int((face_height_m or math.sqrt(face_area_m2)) / max(tube_pitch_transverse_mm/1000.0, 1e-6)))
    total_tubes = max(1, tubes_per_row * int(rows))
    circuits = max(1, int(circuit_count))
    tubes_per_circuit = max(1, math.ceil(total_tubes / circuits))
    tube_length_each_m = face_width_m if face_width_m and face_width_m > 0 else math.sqrt(face_area_m2)
    ref_path_length_m = tubes_per_circuit * tube_length_each_m
    area_i = math.pi * tube_id_m * ref_path_length_m * circuits
    if refrigerant_mass_flow_kg_s is None:
        sat = _sat_props(refrigerant, evap_temp_c)
        refrigerant_mass_flow_kg_s = capacity_kw*1000.0 / max(sat["h_fg"]*0.75, 1.0)
    refcalc = dx_refrigerant_tube_evaporation(refrigerant, evap_temp_c, refrigerant_mass_flow_kg_s, tube_id_m, circuits, ref_path_length_m, capacity_kw, area_i)
    ref_dp = refcalc.get("ref_dp_total_kpa", 0.0) * refrig_dp_index
    ref_dp_status = "OK" if ref_dp <= max_refrigerant_dp_kpa else "HIGH"
    evap_temp_drop_k = 0.0
    effective_evap_temp_c = evap_temp_c
    try:
        if PropsSI is not None and ref_dp > 0:
            p0 = PropsSI("P", "T", evap_temp_c+273.15, "Q", 1, refrigerant)
            p1 = max(1000.0, p0-ref_dp*1000.0)
            effective_evap_temp_c = PropsSI("T", "P", p1, "Q", 1, refrigerant)-273.15
            evap_temp_drop_k = evap_temp_c-effective_evap_temp_c
    except Exception:
        pass
    expected_issue = "OK" if ref_dp_status == "OK" and dp_status == "OK" else "CHECK: excessive air or refrigerant pressure drop can lower effective SST, raise compressor lift/discharge temperature, and reduce capacity."
    return {
        "capacity_required_kw": round(capacity_kw, 3),
        "capacity_possible_kw": round(q_possible_kw*tube_factor, 3),
        "entering_air_input_method": input_method,
        "entering_air_db_c": round(db_in_c, 2),
        "entering_air_wb_c": round(wb_in_c, 2),
        "entering_air_rh_pct": round(rh_pct, 1),
        "air_flow_m3s": round(air_flow_m3s, 3),
        "face_width_m": round(face_width_m or math.sqrt(face_area_m2), 3),
        "face_height_m": round(face_height_m or math.sqrt(face_area_m2), 3),
        "face_area_m2": round(face_area_m2, 3),
        "leaving_air_db_est_c": round(T_out, 2),
        "leaving_air_w_kgkg_est": round(W_out, 5),
        "sensible_heat_ratio_est": round(shr, 3),
        "face_velocity_ms": round(face_velocity, 3),
        "face_velocity_status": face_status,
        "air_side_htc_w_m2k": round(air["air_htc_w_m2k"], 1),
        "air_side_j_factor": round(air["air_j"], 5),
        "air_side_f_factor": round(air["air_f"], 5),
        "air_dp_pa_est": round(air["air_dp_pa"], 1),
        "air_dp_status": dp_status,
        "bypass_factor_required": round(bf_required, 3),
        "bypass_factor_available": round(bf_available, 3),
        "ntu_required": round(ntu_required, 2),
        "ntu_available": round(ntu_available, 2),
        "rows_status": row_status,
        "tube_type": tube_type,
        "tube_od_mm": round(tube_od_mm, 2),
        "tube_id_mm": round(tube_id_m*1000, 2),
        "tube_pitch_transverse_mm": round(tube_pitch_transverse_mm, 2),
        "tube_pitch_longitudinal_mm": round(tube_pitch_longitudinal_mm, 2),
        "tubes_per_row_est": tubes_per_row,
        "total_tubes_est": total_tubes,
        "circuits": circuits,
        "refrigerant_path_length_m_est": round(ref_path_length_m, 2),
        "tube_type_factor": tube_factor,
        "refrigerant_dp_index": refrig_dp_index,
        "refrigerant_dp_kpa_est": round(ref_dp, 3),
        "refrigerant_dp_status": ref_dp_status,
        "effective_evaporating_temp_after_ref_dp_c": round(effective_evap_temp_c, 2),
        "evaporating_temp_loss_due_to_ref_dp_k": round(evap_temp_drop_k, 3),
        "condensing_temp_c": round(condensing_temp_c, 2),
        "target_superheat_k": round(target_superheat_k, 2),
        "expected_issue_due_to_dp": expected_issue,
        "status": "OK" if q_possible_kw*tube_factor >= capacity_kw and face_status == "OK" and dp_status == "OK" and row_status == "OK" and ref_dp_status == "OK" else "CHECK",
        "engineering_note": "Air-side uses compact-fin j/f screening with user geometry. For manufacture, replace with exact fin pattern/Wang coefficients and detailed distributor/header DP from the standalone coil engine.",
    }


def correlation_audit_table() -> pd.DataFrame:
    rows = [
        ["Air coil air-side HTC", "v14: j-factor now applied at minimum-free-area velocity (Kays-London basis)", "Medium", "Needs exact fin pattern coefficients for final manufacture"],
        ["Air coil air-side DP", "v14: core friction + entrance/exit losses at max velocity", "Medium", "Needs exact fin collar/louver/wavy geometry"],
        ["Air coil refrigerant evaporation", "Only tube-type factor in suite; detailed legacy code has Shah-like modules", "Low-Medium", "Integrate full row-by-row refrigerant side next"],
        ["Shell-tube water/glycol shell side", "v14: corrected Kern Nu=0.36 Re^0.55 (previous exponent bug halved HTC) with Jc/Jl/Jb/Jr factors", "Medium", "Enter actual clearances, seal strips and window geometry for final design"],
        ["Shell-tube refrigerant tube side", "v14: Shah multiplier on correct liquid-fraction Re basis, MSH DP", "Medium", "Validate against refrigerant-specific experimental data"],
        ["Flooded shell-side boiling", "v14: Cooper pool boiling solved self-consistently with q''=U*LMTD fixed point", "Medium", "Add Gorenflo/Stephan alternatives and enhanced-tube calibration"],
        ["Condenser tube-side water", "v14: Gnielinski with T-dependent water/seawater properties and library id_enhancement", "Medium-High", "Confirm internal-rib enhancement against supplier datasheet"],
        ["Condenser shell-side condensation", "v14: Beatty-Katz low-fin model on envelope basis with iterated film deltaT", "Medium", "Calibrate surface-tension enhancement vs supplier/test data"],
        ["Evaporative condenser", "v14: NTU-effectiveness Merkel with two-resistance film temperature solution; K estimated from air mass velocity", "Medium", "Calibrate K and coil U against a vendor selection"],
    ]
    return pd.DataFrame(rows, columns=["Area", "Current method", "Confidence", "Remaining work"])


def recommended_improvement_table() -> pd.DataFrame:
    rows = [
        [1, "Integrate row-by-row coil engine", "Move the detailed air-coil legacy code into modules and replace the tube-type factor with calculated refrigerant HTC/DP."],
        [2, "Full Bell-Delaware", "Add shell/baffle clearances, window zones, bypass lanes, seal strips, and unequal end spacing."],
        [3, "Enhanced evaporator tubes", "Add GEWA-B/Turbo-B/flooded evaporator tube library and Cooper/Gorenflo boiling correlations."],
        [4, "Validation examples", "Add HSTAR/Bitzer/Wieland benchmark cases and show deviation percentage."],
        [5, "Automatic optimizer", "Auto-select tube count, passes, length, shell ID, baffle spacing and coil rows to meet kW/DP/size constraints."],
    ]
    return pd.DataFrame(rows, columns=["Priority", "Improvement", "Reason"])


def evaporator_table(result: dict) -> pd.DataFrame:
    return pd.DataFrame([[k, v] for k, v in result.items()], columns=["Parameter", "Value"])

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
    g = _clamp(glycol_pct, 0.0, 60.0) / 100.0
    rho = 1000.0 * (1.0 + 0.09 * g - 0.00025 * (temp_c - 20.0))
    cp = 4180.0 * (1.0 - 0.18 * g)
    k = 0.60 * (1.0 - 0.38 * g)
    mu_water = 0.001002 * math.exp(-0.033 * (temp_c - 20.0))
    mu = mu_water * math.exp(4.2 * g)
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
    h_liq = gnielinski_htc(mdot_ref_kg_s, sp["rho_l"], sp["mu_l"], sp["k_l"], sp["cp_l"], tube_id_m, flow_area, length_m)
    x_avg = _clamp((x_in + x_out) / 2.0, 0.02, 0.98)
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
                                    tube_layout: str = "triangular") -> dict:
    """Screen a shell-and-tube DX or flooded evaporator with calculated U when possible."""
    props = glycol_props(glycol_pct, 0.5 * (chw_in_c + chw_out_c), fluid)
    cp_kj = props["cp"] / 1000.0
    rho = props["rho"]
    flow_m3h = water_flow_m3h(capacity_kw, max(chw_in_c - chw_out_c, 0.1), cp_kj, rho)
    mdot_w = flow_m3h * rho / 3600.0

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
    velocity_status = "OK" if 0.6 <= velocity_used <= 2.8 else ("LOW" if velocity_used < 0.6 else "HIGH")
    dp_status = "OK" if dp_used <= 80.0 else "HIGH"
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
        "refrigerant_dp_kpa_est": round(refcalc.get("ref_dp_total_kpa", 0.0), 3),
        "status": "OK" if q_possible_kw >= capacity_kw and velocity_status != "HIGH" and dp_status == "OK" else "CHECK",
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
    re_d = rho*face_velocity*tube_od_m/max(mu,1e-12)
    # j decreases with Re and increases slightly with more fins/rows
    j = 0.108 * max(re_d, 1.0)**(-0.29) * (fpi/12.0)**0.12 * (rows/4.0)**0.08
    h = j * rho * face_velocity * cp / max(pr**(2/3), 1e-12)
    # friction factor, conservative for wavy/louvered fin packs
    f = 0.33 * max(re_d, 1.0)**(-0.20) * (fpi/12.0)**0.35 * (rows/4.0)**0.25
    sigma = _clamp(0.72 - 0.010*(fpi-12.0) - fin_thickness_m*fpi/0.0254, 0.35, 0.85)
    dp = (4.0*f*rows/max(sigma,0.1) + (1.0/sigma**2 - 1.0)) * 0.5*rho*face_velocity**2
    return {"air_re_d": re_d, "air_j": j, "air_f": f, "air_htc_w_m2k": h, "air_dp_pa": dp, "free_area_ratio": sigma}


def air_cooled_dx_coil_screening(capacity_kw: float, air_flow_m3s: float, db_in_c: float, wb_in_c: float,
                                 evap_temp_c: float, rows: int, face_area_m2: float, fpi: float = 12.0,
                                 circuit_count: int = 4, tube_type: str = "Smooth") -> dict:
    """Air-cooled DX coil screening with air-side j/f and wet-coil enthalpy method."""
    face_velocity = air_flow_m3s / max(face_area_m2, 1e-9)
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

    air = airside_wang_style_htc_dp(face_velocity, rows, fpi)
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
    dp_status = "OK" if air["air_dp_pa"] <= 180.0 else "HIGH"
    row_status = "OK" if rows >= max(2, math.ceil(ntu_required/0.55)) else "LOW_ROWS"
    return {
        "capacity_required_kw": round(capacity_kw, 3),
        "capacity_possible_kw": round(q_possible_kw*tube_factor, 3),
        "entering_air_db_c": round(db_in_c, 2),
        "entering_air_wb_c": round(wb_in_c, 2),
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
        "tube_type_factor": tube_factor,
        "refrigerant_dp_index": refrig_dp_index,
        "status": "OK" if q_possible_kw*tube_factor >= capacity_kw and face_status == "OK" and dp_status == "OK" and row_status == "OK" else "CHECK",
        "engineering_note": "Air-side uses compact-fin j/f screening. For manufacture, replace with exact fin geometry/Wang correlation coefficients and refrigerant distributor/header DP.",
    }


def correlation_audit_table() -> pd.DataFrame:
    rows = [
        ["Air coil air-side HTC", "v7 uses Wang/Kays-London style j-factor screening", "Medium", "Needs exact fin pattern coefficients for final manufacture"],
        ["Air coil air-side DP", "v7 uses compact-fin f-factor and free-area estimate", "Medium", "Needs exact fin collar/louver/wavy geometry"],
        ["Air coil refrigerant evaporation", "Only tube-type factor in suite; detailed legacy code has Shah-like modules", "Low-Medium", "Integrate full row-by-row refrigerant side next"],
        ["Shell-tube water/glycol shell side", "v8 uses shared Bell-Delaware/Kern screening with Jc/Jl/Jb/Jr factors", "Medium", "Enter actual clearances, seal strips and window geometry for final design"],
        ["Shell-tube refrigerant tube side", "v8 uses correct Bo=q''/(G*hfg), Shah-style multiplier and MSH DP", "Medium", "Validate against refrigerant-specific experimental data"],
        ["Flooded shell-side boiling", "v8 uses Cooper pool-boiling screening", "Medium", "Add Gorenflo/Stephan alternatives and enhanced-tube calibration"],
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

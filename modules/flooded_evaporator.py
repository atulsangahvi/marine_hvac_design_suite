"""Flooded shell-and-tube evaporator preliminary design module.

This module is a practical engineering-screening engine, not an HTRI replacement.
It gives the chiller designer the key quantities needed to iterate a flooded
cooler: water/glycol tube velocity and DP, shell-side boiling HTC, U, approach,
refrigerant inventory, oil-management warnings and design guidance.
"""
from __future__ import annotations

import math
from typing import Dict, Optional

try:
    from CoolProp.CoolProp import PropsSI
except Exception:  # pragma: no cover
    PropsSI = None

from modules.evaporator import glycol_props, water_flow_m3h, gnielinski_htc, darcy_dp_kpa
from modules.correlations import cooper_pool_boiling


def _sat_props(ref: str, evap_temp_c: float) -> Dict[str, float]:
    if PropsSI is None:
        return {"rho_l": 1150.0, "rho_v": 20.0, "h_fg": 180000.0, "p_sat": 400000.0, "p_crit": 4000000.0, "mw": 100.0}
    T = evap_temp_c + 273.15
    return {
        "rho_l": float(PropsSI("D", "T", T, "Q", 0, ref)),
        "rho_v": float(PropsSI("D", "T", T, "Q", 1, ref)),
        "h_fg": float(PropsSI("H", "T", T, "Q", 1, ref) - PropsSI("H", "T", T, "Q", 0, ref)),
        "p_sat": float(PropsSI("P", "T", T, "Q", 1, ref)),
        "p_crit": float(PropsSI("Pcrit", ref)),
        "mw": float(PropsSI("M", ref) * 1000.0),
    }


def flooded_evaporator_design(
    capacity_kw: float,
    refrigerant: str,
    evap_temp_c: float,
    chw_in_c: float,
    chw_out_c: float,
    fluid: str = "Water/Glycol",
    glycol_pct: float = 0.0,
    water_flow_m3h_input: Optional[float] = None,
    tube_od_mm: float = 15.88,
    tube_wall_mm: float = 0.8,
    tube_length_m: float = 1.2,
    tube_count: int = 80,
    tube_passes: int = 2,
    pitch_ratio: float = 1.25,
    shell_id_mm: Optional[float] = None,
    shell_length_allowance_m: float = 0.25,
    liquid_level_pct_shell_dia: float = 55.0,
    enhanced_boiling_multiplier: float = 1.5,
    fouling_water_m2k_w: float = 0.00018,
    fouling_ref_m2k_w: float = 0.00005,
    tube_k_w_mk: float = 330.0,
    max_water_dp_kpa: float = 80.0,
    max_water_velocity_ms: float = 2.8,
    min_water_velocity_ms: float = 0.6,
    oil_return_type: str = "Oil pot / eductor return",
) -> Dict[str, object]:
    """Preliminary flooded evaporator design.

    Assumptions:
    - Water/glycol flows inside tubes.
    - Refrigerant boils outside tubes in a flooded shell.
    - Shell-side pressure drop is normally small; the module estimates a small
      vapor disengagement DP allowance and focuses on inventory and level.
    - Cooper pool-boiling is the base HTC; enhanced tubes apply a visible
      multiplier requiring supplier/test validation.
    """
    capacity_kw = float(capacity_kw)
    do = tube_od_mm / 1000.0
    di = max(0.001, (tube_od_mm - 2.0 * tube_wall_mm) / 1000.0)
    tube_count = max(1, int(tube_count))
    tube_passes = max(1, int(tube_passes))
    tubes_per_pass = max(1, tube_count // tube_passes)
    props = glycol_props(glycol_pct, 0.5 * (chw_in_c + chw_out_c), fluid)
    cp_kj = props["cp"] / 1000.0
    design_flow = water_flow_m3h(capacity_kw, max(chw_in_c - chw_out_c, 0.1), cp_kj, props["rho"])
    flow_m3h = float(water_flow_m3h_input) if water_flow_m3h_input and water_flow_m3h_input > 0 else design_flow
    mdot_w = flow_m3h * props["rho"] / 3600.0
    flow_area = tubes_per_pass * math.pi * di * di / 4.0
    h_w = gnielinski_htc(mdot_w, props["rho"], props["mu"], props["k"], props["cp"], di, flow_area, tube_length_m * tube_passes)
    dp_w = darcy_dp_kpa(mdot_w, props["rho"], props["mu"], di, tube_length_m * tube_passes, flow_area, minor_k=2.0*tube_passes)

    area_o = math.pi * do * tube_length_m * tube_count
    area_i = math.pi * di * tube_length_m * tube_count
    pitch = max(pitch_ratio * do, 1.05 * do)
    bundle_od_m = math.sqrt(max(tube_count, 1) / 0.866) * pitch
    shell_id_m = (shell_id_mm / 1000.0) if shell_id_mm and shell_id_mm > 0 else bundle_od_m + max(0.08, 0.25 * bundle_od_m)
    shell_len_m = tube_length_m + shell_length_allowance_m

    sat = _sat_props(refrigerant, evap_temp_c)
    pr_red = sat["p_sat"] / max(sat["p_crit"], 1.0)
    r_wall_o = do * math.log(do / di) / max(2.0 * tube_k_w_mk, 1e-12)

    dt1 = max(chw_in_c - evap_temp_c, 0.1)
    dt2 = max(chw_out_c - evap_temp_c, 0.1)
    lmtd = (dt1 - dt2) / math.log(dt1 / dt2) if abs(dt1 - dt2) > 1e-9 else dt1

    # v14: Cooper pool-boiling HTC depends on the heat flux (h ∝ q''^0.67), and the
    # achievable flux depends on U — a circular dependency the previous code broke
    # by simply assuming the REQUIRED duty is transferred. That over-stated h and U
    # for undersized bundles and under-stated them for oversized ones. Solve the
    # fixed point q'' = U(q'')·LMTD instead (converges in a few iterations because
    # the exponent is < 1).
    q_flux = max(capacity_kw * 1000.0 / max(area_o, 1e-12), 500.0)
    h_pool = cooper_pool_boiling(pr_red, sat["mw"], q_flux)
    Uo = 1000.0
    for _ in range(20):
        h_pool = cooper_pool_boiling(pr_red, sat["mw"], q_flux)
        h_ref = max(600.0, min(25000.0, h_pool * max(1.0, enhanced_boiling_multiplier)))
        Uo = 1.0 / max(1.0/h_ref + fouling_ref_m2k_w + r_wall_o + (do/di)*(1.0/h_w["h"] + fouling_water_m2k_w), 1e-12)
        q_flux_new = max(Uo * lmtd, 500.0)
        if abs(q_flux_new - q_flux) < 0.005 * q_flux:
            q_flux = q_flux_new
            break
        q_flux = 0.5 * (q_flux + q_flux_new)
    h_ref = max(600.0, min(25000.0, h_pool * max(1.0, enhanced_boiling_multiplier)))

    q_possible = Uo * area_o * lmtd / 1000.0
    approach_leaving = chw_out_c - evap_temp_c

    # v14: the liquid level is a fraction of shell DIAMETER, which is NOT the same
    # as a fraction of shell VOLUME — the correct wetted cross-section is a circular
    # segment. The previous linear approximation over-stated charge at low levels
    # and under-stated it at high levels. Tube displacement is now also limited to
    # the tubes actually submerged below the liquid level.
    shell_vol = math.pi * shell_id_m**2 / 4.0 * shell_len_m
    liquid_level_frac = max(0.25, min(0.85, liquid_level_pct_shell_dia/100.0))
    R = shell_id_m / 2.0
    h_liq = liquid_level_frac * shell_id_m                     # liquid depth from bottom
    theta = 2.0 * math.acos(max(-1.0, min(1.0, (R - h_liq) / R)))
    seg_area = 0.5 * R * R * (theta - math.sin(theta))         # wetted cross-section
    liquid_vol_gross = seg_area * shell_len_m
    liquid_area_frac = seg_area / max(math.pi * R * R, 1e-12)
    # Bundle sits low in the shell; assume tubes are uniformly distributed over the
    # bundle circle and submerged in proportion to the liquid depth over the bundle.
    bundle_bottom = max(0.0, R - bundle_od_m / 2.0)            # gap below bundle
    submerged_frac = max(0.0, min(1.0, (h_liq - bundle_bottom) / max(bundle_od_m, 1e-6)))
    bundle_displacement = tube_count * math.pi * do**2 / 4.0 * tube_length_m * submerged_frac
    active_liq_vol = max(0.0, liquid_vol_gross - bundle_displacement)
    # Add ~15% for vapor bubbles displacing liquid in the boiling zone (void) as a
    # deduction, and ~10% back for liquid in level legs/piping — net small effect.
    refrigerant_charge_kg = active_liq_vol * sat["rho_l"] * 0.90 + \
        (shell_vol - liquid_vol_gross) * sat["rho_v"]          # include vapor space mass
    vapor_space_pct = (1.0 - liquid_area_frac) * 100.0

    # flooded evaporator shell-side vapor DP is normally small but vapor disengagement
    # and suction nozzle losses matter; use a conservative screening allowance based on heat flux.
    shell_ref_dp_kpa = max(0.5, min(15.0, 0.0025 * q_flux + 0.5))
    effective_evap_temp_c = evap_temp_c
    temp_loss_k = 0.0
    try:
        if PropsSI is not None:
            p1 = max(1000.0, sat["p_sat"] - shell_ref_dp_kpa*1000.0)
            effective_evap_temp_c = float(PropsSI("T", "P", p1, "Q", 1, refrigerant) - 273.15)
            temp_loss_k = evap_temp_c - effective_evap_temp_c
    except Exception:
        pass

    c_water = mdot_w * cp_kj
    qmax = c_water * max(chw_in_c - evap_temp_c, 0.0)
    effectiveness = capacity_kw / max(qmax, 1e-12)
    velocity_status = "OK" if min_water_velocity_ms <= h_w["v"] <= max_water_velocity_ms else ("LOW" if h_w["v"] < min_water_velocity_ms else "HIGH")
    dp_status = "OK" if dp_w["dp_kpa"] <= max_water_dp_kpa else "HIGH"

    warnings = []
    if approach_leaving < 1.0:
        warnings.append("Very low leaving approach; flooded evaporator may need enhanced tubes, careful level control and validated supplier data.")
    if q_flux > 25000:
        warnings.append("High boiling heat flux; check dryout/nucleate boiling stability and oil concentration.")
    if refrigerant_charge_kg > 150:
        warnings.append("High estimated refrigerant inventory; consider spray evaporator or low-charge design if regulations or class rules require.")
    if "eductor" not in oil_return_type.lower() and "jet" not in oil_return_type.lower():
        warnings.append("Flooded evaporators need positive oil return strategy. Add oil pot, eductor/jet pump, skimmer or manufacturer-approved oil system.")

    guidance = []
    if q_possible < capacity_kw:
        guidance.append("Increase tube count/length, use enhanced flooded evaporator tubes, reduce leaving approach, or increase water flow if Cmin limits duty.")
    if velocity_status == "LOW":
        guidance.append("Water velocity is low; reduce tubes per pass or increase passes to improve tube-side HTC and fouling resistance.")
    if dp_status == "HIGH":
        guidance.append("Water pressure drop is high; reduce passes, increase tube ID/count, or increase shell size.")
    if not guidance:
        guidance.append("Flooded evaporator screening is acceptable; validate with supplier tube data and operating charge limits before manufacture.")

    return {
        "evaporator_type": "Flooded shell-and-tube",
        "capacity_required_kw": round(capacity_kw, 3),
        "capacity_possible_kw": round(q_possible, 3),
        "status": "OK" if q_possible >= capacity_kw and velocity_status == "OK" and dp_status == "OK" and effectiveness <= 1.0 else "CHECK",
        "refrigerant": refrigerant,
        "evaporating_temp_c": round(evap_temp_c, 2),
        "leaving_approach_k": round(approach_leaving, 3),
        "lmtd_k": round(lmtd, 3),
        "Uo_w_m2k": round(Uo, 1),
        "outside_area_m2": round(area_o, 3),
        "inside_area_m2": round(area_i, 3),
        "heat_flux_w_m2": round(q_flux, 1),
        "water_flow_m3h": round(flow_m3h, 3),
        "water_design_flow_m3h_at_entered_deltaT": round(design_flow, 3),
        "water_velocity_ms": round(h_w["v"], 3),
        "water_velocity_status": velocity_status,
        "water_Re": round(h_w["re"], 0),
        "water_Pr": round(h_w["pr"], 3),
        "water_htc_w_m2k": round(h_w["h"], 0),
        "water_dp_kpa": round(dp_w["dp_kpa"], 3),
        "water_dp_status": dp_status,
        "pool_boiling_htc_plain_w_m2k": round(h_pool, 0),
        "enhanced_boiling_multiplier": round(enhanced_boiling_multiplier, 2),
        "shell_side_boiling_htc_w_m2k": round(h_ref, 0),
        "shell_refrigerant_dp_kpa_est": round(shell_ref_dp_kpa, 3),
        "evap_temp_loss_due_to_shell_dp_k": round(temp_loss_k, 3),
        "effective_evap_temp_at_suction_nozzle_c": round(effective_evap_temp_c, 2),
        "tube_count": tube_count,
        "tube_passes": tube_passes,
        "tubes_per_pass": tubes_per_pass,
        "tube_od_mm": tube_od_mm,
        "tube_id_mm": round(di*1000, 2),
        "tube_length_m": tube_length_m,
        "bundle_od_mm_est": round(bundle_od_m*1000, 1),
        "shell_id_mm_est": round(shell_id_m*1000, 1),
        "shell_length_m_est": round(shell_len_m, 2),
        "liquid_level_pct_shell_dia": round(liquid_level_pct_shell_dia, 1),
        "vapor_disengagement_space_pct": round(vapor_space_pct, 1),
        "estimated_refrigerant_charge_kg": round(refrigerant_charge_kg, 1),
        "water_heat_capacity_rate_kw_per_k": round(c_water, 3),
        "limiting_side": "water/glycol side; refrigerant is phase-change at nearly constant temperature",
        "max_heat_transfer_possible_kw_by_cmin": round(qmax, 3),
        "effectiveness_based_on_cmin": round(effectiveness, 3),
        "oil_return_strategy": oil_return_type,
        "warnings": "; ".join(warnings) if warnings else "None",
        "guidance": " ".join(guidance),
        "engineering_note": "Flooded design requires final validation of refrigerant inventory, oil return, shell nozzle velocities, demister/suction baffle and enhanced tube performance before manufacture.",
    }

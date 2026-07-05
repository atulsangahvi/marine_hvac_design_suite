"""Evaporative condenser preliminary design module.

The model combines: refrigerant heat rejection, sprayed-water/air evaporative
enthalpy driving force, coil geometry, water spray rate, air flow, fan power and
make-up water estimates. It is intentionally transparent so it can be calibrated
against a known closed-circuit cooler / evaporative condenser selection.
"""
from __future__ import annotations

import math
from typing import Dict, Optional

try:
    from CoolProp.CoolProp import PropsSI
except Exception:  # pragma: no cover
    PropsSI = None

# psychrometric functions are based on the uploaded cooling-tower and evaporative-coil apps

def p_ws_kpa(T_c: float) -> float:
    return 0.61094 * math.exp((17.625 * T_c) / (T_c + 243.04))


def humidity_ratio_from_db_wb(T_db: float, T_wb: float, P_kpa: float = 101.325) -> float:
    if T_wb > T_db:
        T_wb = T_db
    pws_wb = p_ws_kpa(T_wb)
    A = 0.00066 * (1.0 + 0.00115 * T_wb)
    p_w = pws_wb - A * P_kpa * (T_db - T_wb)
    p_w = max(0.0001, min(p_w, 0.98 * P_kpa))
    return max(0.0, 0.621945 * p_w / max(P_kpa - p_w, 1e-9))


def enthalpy_air(T_db: float, w: float) -> float:
    return 1.006 * T_db + w * (2501.0 + 1.86 * T_db)


def sat_air_enthalpy(T_c: float, P_kpa: float = 101.325) -> float:
    pws = min(p_ws_kpa(T_c), 0.98 * P_kpa)
    w = 0.621945 * pws / max(P_kpa - pws, 1e-9)
    return enthalpy_air(T_c, w)


def air_density(T_db: float, w: float, P_kpa: float = 101.325) -> float:
    P = P_kpa * 1000.0
    Tk = T_db + 273.15
    p_w = P * w / (0.621945 + w)
    p_da = P - p_w
    return p_da/(287.055*Tk) + p_w/(461.495*Tk)


def _lmtd_const_hot(T_hot: float, T_cold_in: float, T_cold_out: float) -> float:
    dt1 = max(T_hot - T_cold_out, 0.1)
    dt2 = max(T_hot - T_cold_in, 0.1)
    return (dt1 - dt2) / math.log(dt1/dt2) if abs(dt1-dt2) > 1e-9 else dt1


def _ref_condensing_pressure(ref: str, cond_temp_c: float) -> float:
    if PropsSI is None:
        return 1.2e6
    return float(PropsSI("P", "T", cond_temp_c+273.15, "Q", 0, ref))


def evaporative_condenser_design(
    heat_rejection_kw: float,
    refrigerant: str,
    condensing_temp_c: float,
    ambient_db_c: float,
    ambient_wb_c: float,
    coil_area_m2: Optional[float] = None,
    tube_od_mm: float = 19.05,
    tube_length_m: float = 1.5,
    tube_count: int = 80,
    rows_depth: int = 6,
    face_width_m: float = 1.5,
    face_height_m: float = 1.5,
    air_flow_m3s: Optional[float] = None,
    face_velocity_ms: float = 2.5,
    spray_rate_m3h_m2: float = 6.0,
    k_merkel_kg_s_m2: Optional[float] = None,
    overall_u_w_m2k_dry_basis: float = 450.0,
    fan_static_pa: float = 180.0,
    fan_efficiency: float = 0.60,
    pump_efficiency: float = 0.50,
    pump_head_m: float = 12.0,
    drift_loss_pct_circulation: float = 0.005,
    cycles_of_concentration: float = 3.0,
    pressure_kpa: float = 101.325,
) -> Dict[str, object]:
    q = float(heat_rejection_kw)
    face_area = max(face_width_m * face_height_m, 0.01)
    if air_flow_m3s is None or air_flow_m3s <= 0:
        air_flow_m3s = face_velocity_ms * face_area
    face_velocity = air_flow_m3s / face_area
    w_in = humidity_ratio_from_db_wb(ambient_db_c, ambient_wb_c, pressure_kpa)
    rho_air = air_density(ambient_db_c, w_in, pressure_kpa)
    m_air = rho_air * air_flow_m3s

    # v14: when no calibrated Merkel/mass-transfer coefficient is supplied, estimate
    # it from air mass velocity through the wetted bundle (Parker & Treybal-style
    # hD = C·G^0.9, with G at the minimum free area, σ ≈ 0.55 for a wet plain-tube
    # bank). The previous fixed default of 0.0015 kg/s·m² was 1-2 orders of
    # magnitude below published evaporative-condenser data and made every realistic
    # selection report SHORT. This estimate must still be calibrated against a
    # vendor selection before manufacture.
    if k_merkel_kg_s_m2 is None or k_merkel_kg_s_m2 <= 0:
        g_face = m_air / face_area
        g_max = g_face / 0.55
        # Published Parker-Treybal data span roughly hD = 0.05-0.16 kg/s·m² for
        # G_max = 1.4-5 kg/s·m²; cap the estimate inside that envelope.
        k_merkel_kg_s_m2 = max(0.02, min(0.16, 0.049 * g_max ** 0.905))
        merkel_k_source = "estimated from air mass velocity (Parker-Treybal form)"
    else:
        merkel_k_source = "user/vendor-calibrated input"

    h_air_in = enthalpy_air(ambient_db_c, w_in)

    tube_area = math.pi * (tube_od_mm/1000.0) * tube_length_m * max(1, int(tube_count))
    area = coil_area_m2 if coil_area_m2 and coil_area_m2 > 0 else tube_area

    # v14: two coupled resistances solved simultaneously instead of a guessed
    # "condensing minus 3 K" film temperature and a single-point enthalpy driving
    # force (which let predicted duty exceed what the air stream could physically
    # absorb).
    #
    #   Inside path:  q = U_i · A · (T_cond - T_film)          [refrigerant→tube→spray film]
    #   Outside path: q = ε · ṁ_air · (h_sat(T_film) - h_in)   [Merkel, NTU-effectiveness]
    #   with NTU = K·A / ṁ_air  and  ε = 1 - exp(-NTU)
    #
    # The NTU form correctly caps the air-side enthalpy pickup: as area grows, the
    # leaving air approaches saturation at the film temperature instead of q growing
    # without bound. T_film is found by bisection between WB and condensing temp.
    ntu = k_merkel_kg_s_m2 * area / max(m_air, 1e-9)
    eff = 1.0 - math.exp(-min(ntu, 30.0))

    def q_air_kw(t_film: float) -> float:
        return eff * m_air * max(sat_air_enthalpy(t_film, pressure_kpa) - h_air_in, 0.0)

    def q_ref_kw(t_film: float) -> float:
        return overall_u_w_m2k_dry_basis * area * max(condensing_temp_c - t_film, 0.0) / 1000.0

    lo, hi_t = ambient_wb_c + 0.05, condensing_temp_c - 0.05
    surface_temp_c = 0.5 * (lo + hi_t)
    if hi_t > lo:
        for _ in range(60):
            mid = 0.5 * (lo + hi_t)
            # imbalance: inside delivery minus outside removal; decreasing in T_film
            if q_ref_kw(mid) > q_air_kw(mid):
                lo = mid
            else:
                hi_t = mid
            if hi_t - lo < 0.01:
                break
        surface_temp_c = 0.5 * (lo + hi_t)
    q_possible = min(q_ref_kw(surface_temp_c), q_air_kw(surface_temp_c)) if hi_t > lo else 0.0
    h_sat_surface = sat_air_enthalpy(surface_temp_c, pressure_kpa)
    driving_h = max(0.0, h_sat_surface - h_air_in)
    q_merkel = q_air_kw(surface_temp_c)
    q_ua = q_ref_kw(surface_temp_c)
    # Spray-water temperatures reported around the solved film temperature
    spray_water_in = max(ambient_wb_c + 1.0, surface_temp_c - 2.0)
    spray_water_out = min(condensing_temp_c - 0.5, surface_temp_c + 2.0)
    lmtd = _lmtd_const_hot(condensing_temp_c, spray_water_in, spray_water_out)

    spray_flow_m3h = spray_rate_m3h_m2 * face_area
    evap_loss_m3h = 0.00153 * q  # approx m3/h evaporation per kW heat rejection
    drift_m3h = spray_flow_m3h * drift_loss_pct_circulation / 100.0
    blowdown_m3h = evap_loss_m3h / max(cycles_of_concentration - 1.0, 1.0)
    makeup_m3h = evap_loss_m3h + drift_m3h + blowdown_m3h

    fan_kw = air_flow_m3s * fan_static_pa / max(fan_efficiency, 1e-9) / 1000.0
    pump_kw = (spray_flow_m3h/3600.0) * 1000.0 * 9.81 * pump_head_m / max(pump_efficiency, 1e-9) / 1000.0
    approach_wb = condensing_temp_c - ambient_wb_c
    p_cond_bar_g = _ref_condensing_pressure(refrigerant, condensing_temp_c)/1e5 - 1.01325

    air_dp_status = "OK" if fan_static_pa <= 300 else "HIGH"
    face_status = "OK" if 1.5 <= face_velocity <= 4.0 else ("LOW" if face_velocity < 1.5 else "HIGH")
    spray_status = "OK" if 4.0 <= spray_rate_m3h_m2 <= 10.0 else "CHECK"
    status = "OK" if q_possible >= q and air_dp_status == "OK" and face_status == "OK" else "SHORT"

    guidance = []
    if q_possible < q:
        guidance.append("Increase coil area/tube count/length, increase airflow, improve spray distribution/K value, or accept higher condensing temperature.")
    if face_status != "OK":
        guidance.append("Adjust fan airflow or coil face area to keep face velocity roughly 1.5–4.0 m/s.")
    if spray_status != "OK":
        guidance.append("Review spray rate; typical closed-circuit cooler/evaporative condenser spray loading is about 4–10 m³/h per m² plan area.")
    if approach_wb < 7:
        guidance.append("Very low condensing-to-wet-bulb approach; validate with vendor data and expect larger coil/fan power.")
    if not guidance:
        guidance.append("Evaporative condenser screening is acceptable; calibrate Merkel K and fan/static pressure against a vendor selection before manufacture.")

    return {
        "condenser_type": "Evaporative condenser / closed-circuit condenser",
        "heat_rejection_required_kw": round(q, 3),
        "heat_rejection_possible_kw": round(q_possible, 3),
        "status": status,
        "refrigerant": refrigerant,
        "condensing_temp_c": round(condensing_temp_c, 2),
        "condensing_pressure_bar_g_est": round(p_cond_bar_g, 2),
        "ambient_db_c": round(ambient_db_c, 2),
        "ambient_wb_c": round(ambient_wb_c, 2),
        "condensing_to_wb_approach_k": round(approach_wb, 2),
        "coil_area_m2": round(area, 3),
        "tube_area_from_geometry_m2": round(tube_area, 3),
        "tube_count": int(tube_count),
        "tube_length_m": round(tube_length_m, 3),
        "tube_od_mm": round(tube_od_mm, 2),
        "rows_depth": int(rows_depth),
        "face_area_m2": round(face_area, 3),
        "face_velocity_ms": round(face_velocity, 3),
        "face_velocity_status": face_status,
        "air_flow_m3s": round(air_flow_m3s, 3),
        "air_mass_flow_kg_s": round(m_air, 3),
        "air_inlet_h_kj_kgda": round(h_air_in, 3),
        "saturated_surface_h_kj_kgda": round(h_sat_surface, 3),
        "enthalpy_driving_force_kj_kgda": round(driving_h, 3),
        "solved_spray_film_temp_c": round(surface_temp_c, 2),
        "merkel_ntu": round(ntu, 3),
        "merkel_air_effectiveness": round(eff, 4),
        "merkel_k_kg_s_m2": round(k_merkel_kg_s_m2, 6),
        "merkel_k_source": merkel_k_source,
        "q_merkel_possible_kw": round(q_merkel, 3),
        "q_ua_possible_kw": round(q_ua, 3),
        "lmtd_spray_water_k": round(lmtd, 3),
        "overall_u_w_m2k_dry_basis": round(overall_u_w_m2k_dry_basis, 1),
        "spray_rate_m3h_m2": round(spray_rate_m3h_m2, 3),
        "spray_rate_status": spray_status,
        "spray_water_flow_m3h": round(spray_flow_m3h, 3),
        "evaporation_loss_m3h": round(evap_loss_m3h, 3),
        "drift_loss_m3h": round(drift_m3h, 4),
        "blowdown_m3h": round(blowdown_m3h, 3),
        "makeup_water_m3h": round(makeup_m3h, 3),
        "cycles_of_concentration": round(cycles_of_concentration, 2),
        "fan_static_pa": round(fan_static_pa, 1),
        "air_dp_status": air_dp_status,
        "fan_power_kw": round(fan_kw, 3),
        "spray_pump_power_kw": round(pump_kw, 3),
        "guidance": " ".join(guidance),
        "engineering_note": "Uses Merkel/enthalpy method from cooling-tower and evaporative-fluid-cooler practice. K and U must be calibrated against vendor test data before manufacture.",
    }

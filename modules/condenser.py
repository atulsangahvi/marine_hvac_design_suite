from __future__ import annotations
import math
import pandas as pd
from .thermo import water_flow_m3h
from .correlations import nusselt_horizontal_condensation, enhanced_lowfin_area_ratio, bell_delaware_screening, BellKernInput
from data.tube_library import filter_tubes
from data.materials import material_k, velocity_limits



def _lmtd(dt1: float, dt2: float) -> float:
    dt1 = max(float(dt1), 0.05)
    dt2 = max(float(dt2), 0.05)
    if abs(dt1 - dt2) < 1e-9:
        return dt1
    return (dt2 - dt1) / max(math.log(dt2 / dt1), 1e-9)


def estimate_bundle_diameter_mm(n_tubes: int, tube_od_mm: float, pitch_ratio: float = 1.25, layout: str = "triangular") -> float:
    """Approximate bundle OD from tube count and pitch.

    This is a screening estimate, not a replacement for a TEMA tube-count chart.
    It is deliberately conservative so shell ID is not shown as zero.
    """
    n_tubes = max(int(n_tubes), 1)
    pitch = float(tube_od_mm) * max(float(pitch_ratio), 1.05)
    packing = 0.78 if str(layout).lower().startswith("tri") else 0.70
    area_per_tube = pitch * pitch / packing
    bundle_area = n_tubes * area_per_tube
    return max(math.sqrt(4.0 * bundle_area / math.pi), tube_od_mm * 3.0)


def estimate_shell_id_mm(bundle_od_mm: float) -> float:
    clearance = max(10.0, 0.04 * float(bundle_od_mm) + 6.0)
    return float(bundle_od_mm) + 2.0 * clearance


def estimate_shell_od_mm(shell_id_mm: float, shell_thk_mm: float = 6.0) -> float:
    return float(shell_id_mm) + 2.0 * max(float(shell_thk_mm), 0.0)


def tube_velocity_status(material: str, velocity_m_s: float) -> tuple[str, str]:
    lo, hi = velocity_limits(material, "seawater" if "CuNi" in str(material) or "Titanium" in str(material) else "plain water")
    if velocity_m_s < lo:
        return "LOW", f"Below recommended range {lo:.1f}-{hi:.1f} m/s; heat transfer and fouling resistance may suffer."
    if velocity_m_s > hi:
        return "HIGH", f"Above recommended range {lo:.1f}-{hi:.1f} m/s; check erosion, noise and pressure drop."
    return "OK", f"Within recommended range {lo:.1f}-{hi:.1f} m/s."


def tube_dp_kpa(flow_velocity_m_s: float, id_mm: float, tube_length_m: float, passes: int, rho: float, mu: float, minor_k: float = 2.5) -> float:
    d = max(float(id_mm) / 1000.0, 1e-6)
    l_total = max(float(tube_length_m), 0.0) * max(int(passes), 1)
    re = rho * max(flow_velocity_m_s, 0.0) * d / max(mu, 1e-9)
    if re <= 0:
        return 0.0
    if re < 2300:
        f = 64.0 / max(re, 1.0)
    else:
        f = 0.3164 / (re ** 0.25)
    dp = (f * l_total / d + minor_k * max(int(passes), 1)) * rho * flow_velocity_m_s**2 / 2.0
    return dp / 1000.0


def evaluate_condenser(q_rej_kw: float, water_type: str, water_in_c: float, water_out_c: float,
                       n_tubes: int, tube_passes: int, tube_length_m: float, tube: dict,
                       condensing_htc_multiplier: float = 2.5, pitch_ratio: float = 1.25,
                       shell_thk_mm: float = 6.0, fouling_m2kw: float | None = None,
                       condensing_temp_c: float = 45.0, layout: str = "triangular",
                       refrigerant: str = "R407C", baffle_spacing_mm: float | None = None,
                       baffle_cut_pct: float = 25.0) -> dict:
    """Screen a water-cooled Freon condenser design.

    Heat transfer uses a conservative overall-U model. The GEWA/low-fin tube data is
    used for geometry, ID, weight and envelope area; the shell-side multiplier remains
    user-visible because exact GEWA performance requires supplier/test correlations.
    """
    water_key = (water_type or "").lower().replace(" ", "_")
    is_sea = "sea" in water_key
    cp = 3.99 if is_sea else 4.186
    rho = 1025.0 if is_sea else 998.0
    mu = 0.00095 if is_sea else 0.00075
    k_water = 0.60

    dtw = max(float(water_out_c) - float(water_in_c), 0.1)
    flow_m3h = water_flow_m3h(float(q_rej_kw), dtw, cp, rho)
    tubes_per_pass = max(1, int(n_tubes) // max(1, int(tube_passes)))
    flow_area = tubes_per_pass * math.pi * (float(tube["id_mm"]) / 1000.0) ** 2 / 4.0
    velocity = (flow_m3h / 3600.0) / max(flow_area, 1e-12)

    pr = cp * 1000.0 * mu / k_water
    re = rho * velocity * float(tube["id_mm"]) / 1000.0 / mu
    nu = 0.023 * max(re, 1.0) ** 0.8 * pr ** 0.4 if re > 3000 else 4.36
    hi = nu * k_water / max(float(tube["id_mm"]) / 1000.0, 1e-9)

    # Shell-side condensation coefficient from Nusselt film condensation as a base.
    # Enhanced tubes then apply an explicit multiplier that remains visible to the user.
    try:
        from CoolProp.CoolProp import PropsSI
        T = float(condensing_temp_c) + 273.15
        rho_l_r = float(PropsSI("D", "T", T, "Q", 0, refrigerant))
        rho_v_r = float(PropsSI("D", "T", T, "Q", 1, refrigerant))
        mu_l_r = float(PropsSI("V", "T", T, "Q", 0, refrigerant))
        k_l_r = float(PropsSI("L", "T", T, "Q", 0, refrigerant))
        hfg_r = float(PropsSI("H", "T", T, "Q", 1, refrigerant) - PropsSI("H", "T", T, "Q", 0, refrigerant))
    except Exception:
        rho_l_r, rho_v_r, mu_l_r, k_l_r, hfg_r = 1050.0, 35.0, 0.00016, 0.08, 170000.0
    tube_rows_est = max(1, int(math.sqrt(max(int(n_tubes),1)) / 2))
    # wall temperature estimate halfway between condensing and outlet water.
    wall_est = 0.5*(float(condensing_temp_c) + float(water_out_c))
    cond_htc = nusselt_horizontal_condensation(k_l_r, rho_l_r, rho_v_r, mu_l_r, hfg_r, float(tube.get("fin_od_mm", tube["od_mm"]))/1000.0, float(condensing_temp_c), wall_est, tube_rows_est)
    ho_plain = cond_htc["h_plain_w_m2k"]
    ho = ho_plain * max(float(condensing_htc_multiplier), 1.0)

    ao = math.pi * (float(tube.get("fin_od_mm", tube["od_mm"])) / 1000.0) * float(tube_length_m) * int(n_tubes)
    area_ratio_info = None
    if tube.get("enhanced_surface") in ["low-fin", "GEWA-C", "GEWA-CLF", "GEWA-CPL"]:
        area_ratio_info = enhanced_lowfin_area_ratio(float(tube.get("fin_od_mm", tube["od_mm"])), float(tube.get("root_od_mm", tube.get("fin_od_mm", tube["od_mm"]))), float(tube.get("fpi", 26.0)), float(tube.get("fin_thickness_mm", 0.25)))
    ai = math.pi * (float(tube["id_mm"]) / 1000.0) * float(tube_length_m) * int(n_tubes)
    k_wall = material_k(tube.get("material", ""))
    wall = max((float(tube.get("root_od_mm", tube["od_mm"])) - float(tube["id_mm"])) / 2000.0, 1e-4)
    rf_i = 0.000088 if is_sea else 0.000044
    rf_o = 0.00005
    if fouling_m2kw is not None:
        rf_i = max(float(fouling_m2kw), 0.0)

    # Uo on outside/envelope area basis.
    uo_inv = 1.0 / max(ho, 1.0) + (ao / max(ai, 1e-12)) / max(hi, 1.0) + rf_i + rf_o + wall / max(k_wall, 1e-9)
    uo = 1.0 / max(uo_inv, 1e-12)

    dt_hot_out = max(float(condensing_temp_c) - float(water_out_c), 0.05)
    dt_hot_in = max(float(condensing_temp_c) - float(water_in_c), 0.05)
    lmtd = _lmtd(dt_hot_out, dt_hot_in)
    q_possible_kw = uo * ao * lmtd / 1000.0

    bundle = estimate_bundle_diameter_mm(int(n_tubes), float(tube["od_mm"]), pitch_ratio, layout)
    sid = estimate_shell_id_mm(bundle)
    baffle_spacing_m = (float(baffle_spacing_mm)/1000.0) if baffle_spacing_mm else max(0.08, min(float(tube_length_m)/6.0, sid/1000.0/2.0))
    shell_calc = bell_delaware_screening(BellKernInput(mdot_kg_s=flow_m3h*rho/3600.0, rho=rho, mu=mu, cp=cp*1000.0, k=k_water, shell_id_m=sid/1000.0, tube_od_m=float(tube["od_mm"])/1000.0, pitch_m=float(tube["od_mm"])/1000.0*float(pitch_ratio), baffle_spacing_m=baffle_spacing_m, baffle_cut_pct=float(baffle_cut_pct), tube_count=int(n_tubes), layout=layout))
    sod = estimate_shell_od_mm(sid, shell_thk_mm)
    shell_weight = math.pi * (sid / 1000.0) * float(tube_length_m) * (float(shell_thk_mm) / 1000.0) * 7850.0
    tube_weight = float(tube.get("kg_m", 0.0)) * float(tube_length_m) * int(n_tubes)
    dry_weight = tube_weight + shell_weight + 0.20 * tube_weight
    dp_kpa = tube_dp_kpa(velocity, float(tube["id_mm"]), float(tube_length_m), int(tube_passes), rho, mu)
    vel_status, vel_note = tube_velocity_status(tube.get("material", ""), velocity)

    status = "OK" if q_possible_kw >= float(q_rej_kw) and vel_status != "HIGH" else "SHORT" if q_possible_kw < float(q_rej_kw) else "CHECK"
    guidance = []
    if q_possible_kw < float(q_rej_kw):
        guidance.append("Increase tube length/count, select a higher-performance enhanced tube, increase condensing temperature, or reduce fouling/design margin.")
    if vel_status == "LOW":
        guidance.append("Reduce passes/tubes per pass or increase water flow if pressure drop allows; low velocity can reduce water-side HTC.")
    if vel_status == "HIGH":
        guidance.append("Increase passes/tube count/diameter or reduce water flow; high velocity may cause erosion.")
    if not guidance:
        guidance.append("Preliminary thermal and water velocity checks are acceptable; verify pressure vessel, vibration and supplier data.")

    return {
        "q_required_kw": float(q_rej_kw), "q_possible_kw": q_possible_kw, "status": status,
        "condensing_temp_c": float(condensing_temp_c), "lmtd_k": lmtd,
        "water_flow_m3h": flow_m3h, "water_velocity_ms": velocity, "velocity_status": vel_status,
        "velocity_note": vel_note, "tube_dp_kpa": dp_kpa,
        "re": re, "pr": pr, "hi_w_m2k": hi, "ho_plain_w_m2k": ho_plain, "ho_w_m2k": ho,
        "condensation_row_factor": cond_htc.get("row_factor", 1.0),
        "uo_w_m2k": uo, "area_m2": ao, "actual_area_ratio_est": (area_ratio_info or {}).get("area_ratio_actual_to_envelope", 1.0), "tubes_per_pass": tubes_per_pass,
        "baffle_spacing_mm": baffle_spacing_m*1000.0, "bell_shell_water_velocity_ms": shell_calc.get("shell_velocity_ms", 0.0), "bell_shell_jc": shell_calc.get("shell_jc", 1.0), "bell_shell_jl": shell_calc.get("shell_jl", 1.0), "bell_shell_jb": shell_calc.get("shell_jb", 1.0),
        "bundle_od_mm": bundle, "shell_id_mm": sid, "shell_od_mm": sod,
        "tube_weight_kg": tube_weight, "shell_weight_kg": shell_weight, "dry_weight_kg": dry_weight,
        "tube": tube["name"], "tube_material": tube.get("material", ""), "guidance": " ".join(guidance),
    }


def auto_select_tubes(q_rej_kw, water_type, water_in_c, water_out_c, n_tubes, tube_passes, tube_length_m,
                      od_filter="All", condensing_htc_multiplier: float = 2.5, pitch_ratio: float = 1.25,
                      shell_thk_mm: float = 6.0, condensing_temp_c: float = 45.0) -> pd.DataFrame:
    rows=[]
    for tube in filter_tubes(water_type, od_filter):
        r = evaluate_condenser(q_rej_kw, water_type, water_in_c, water_out_c, n_tubes, tube_passes, tube_length_m,
                               tube, condensing_htc_multiplier, pitch_ratio, shell_thk_mm,
                               condensing_temp_c=condensing_temp_c)
        rows.append(r)
    df = pd.DataFrame(rows)
    if not df.empty:
        df["thermal_margin_kw"] = df["q_possible_kw"] - float(q_rej_kw)
        df["rank_score"] = (
            df["status"].eq("OK").astype(int) * 100000
            - df["thermal_margin_kw"].abs() * 10
            - df["tube_dp_kpa"] * 2
            - 0.03 * df["dry_weight_kg"]
            - df["velocity_status"].eq("HIGH").astype(int) * 50000
        )
        df = df.sort_values("rank_score", ascending=False).reset_index(drop=True)
    return df

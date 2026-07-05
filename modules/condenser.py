from __future__ import annotations
import math
import pandas as pd
from .thermo import water_flow_m3h
from .correlations import (nusselt_horizontal_condensation, enhanced_lowfin_area_ratio,
                           bell_delaware_screening, BellKernInput, water_properties,
                           gnielinski, friction_factor, beatty_katz_lowfin_condensation)
from data.tube_library import filter_tubes
from data.materials import material_k, velocity_limits



def _lmtd(dt1: float, dt2: float) -> float:
    # v15: order-independent. The old form clamped log() at +1e-9, so passing the
    # larger ΔT first returned a huge negative value instead of the LMTD.
    dt1 = max(float(dt1), 0.05)
    dt2 = max(float(dt2), 0.05)
    if abs(dt1 - dt2) < 1e-9:
        return dt1
    return (dt1 - dt2) / math.log(dt1 / dt2)


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
    # v14: Swamee-Jain with drawn-tube roughness instead of smooth-tube Blasius,
    # so fouled/enhanced-bore condenser tubes are not optimistically smooth.
    f = friction_factor(re, roughness_m=1.5e-6, d_m=d)
    dp = (f * l_total / d + minor_k * max(int(passes), 1)) * rho * flow_velocity_m_s**2 / 2.0
    return dp / 1000.0




def estimate_shell_refrigerant_dp_kpa(q_rej_kw: float, refrigerant: str, condensing_temp_c: float,
                                      shell_id_mm: float, bundle_od_mm: float, tube_length_m: float,
                                      baffle_spacing_mm: float, baffle_cut_pct: float,
                                      tube_count: int, tube_od_mm: float, pitch_ratio: float,
                                      htc_multiplier: float = 1.0) -> dict:
    """Preliminary shell-side refrigerant pressure-drop estimate for shell-side condensation.

    This is a screening calculation. It estimates average condensing vapor/liquid
    properties, equivalent crossflow area and number of baffle spaces. Final
    manufacture still requires detailed Bell-Delaware/two-phase shell-side DP and
    nozzle-loss verification.
    """
    try:
        from CoolProp.CoolProp import PropsSI
        T = float(condensing_temp_c) + 273.15
        rho_v = float(PropsSI("D", "T", T, "Q", 1, refrigerant))
        rho_l = float(PropsSI("D", "T", T, "Q", 0, refrigerant))
        mu_v = float(PropsSI("V", "T", T, "Q", 1, refrigerant))
        mu_l = float(PropsSI("V", "T", T, "Q", 0, refrigerant))
        hfg = float(PropsSI("H", "T", T, "Q", 1, refrigerant) - PropsSI("H", "T", T, "Q", 0, refrigerant))
    except Exception:
        rho_v, rho_l, mu_v, mu_l, hfg = 35.0, 1050.0, 1.5e-5, 1.6e-4, 170000.0

    mdot_ref = max(float(q_rej_kw) * 1000.0 / max(hfg, 1.0), 1e-6)
    # Average mixture properties through condensing zone, weighted toward vapor for DP.
    x_avg = 0.5
    void = 1.0 / (1.0 + ((1.0 - x_avg) / max(x_avg, 1e-6)) * (rho_v / max(rho_l, 1e-9)) ** (2.0/3.0))
    rho_mix = 1.0 / max(x_avg / max(rho_v, 1e-9) + (1.0 - x_avg) / max(rho_l, 1e-9), 1e-12)
    mu_mix = x_avg * mu_v + (1.0 - x_avg) * mu_l

    shell_id_m = max(float(shell_id_mm) / 1000.0, 0.05)
    tube_od_m = max(float(tube_od_mm) / 1000.0, 0.003)
    pitch_m = tube_od_m * max(float(pitch_ratio), 1.05)
    b_m = max(float(baffle_spacing_mm) / 1000.0, 0.02)
    cut = max(min(float(baffle_cut_pct), 45.0), 15.0) / 100.0

    # Crossflow free area near shell centerline. This is approximate but responsive
    # to baffle spacing, pitch and baffle cut.
    pitch_clearance = max((pitch_m - tube_od_m) / max(pitch_m, 1e-9), 0.05)
    cut_factor = max(0.35, 1.0 - 0.9 * cut)
    bypass_factor = max(0.55, min(1.1, (shell_id_m - min(float(bundle_od_mm)/1000.0, shell_id_m*0.98)) / shell_id_m + 0.75))
    area_cross = max(shell_id_m * b_m * pitch_clearance * cut_factor * bypass_factor, 1e-5)
    mass_velocity = mdot_ref / area_cross
    v_mix = mass_velocity / max(rho_mix, 1e-9)
    re_shell = rho_mix * v_mix * tube_od_m / max(mu_mix, 1e-12)
    if re_shell < 2300:
        f = 64.0 / max(re_shell, 1.0)
    else:
        f = 0.35 * max(re_shell, 1.0) ** -0.20
    n_cross = max(1.0, float(tube_length_m) / max(b_m, 1e-9))
    two_phase_mult = 1.5 + 1.2 * max(float(htc_multiplier) - 1.0, 0.0) / 4.0
    dp_core = f * n_cross * rho_mix * v_mix**2 / 2.0 * two_phase_mult
    # Add entrance/exit/nozzle allowance as screening.
    dp_nozzle = 0.8 * rho_mix * v_mix**2 / 2.0
    dp_kpa = (dp_core + dp_nozzle) / 1000.0

    if dp_kpa < 10:
        status = "OK"
        note = "Low preliminary shell-side refrigerant ΔP. Verify nozzle and detailed two-phase Bell-Delaware DP."
    elif dp_kpa <= 30:
        status = "CHECK"
        note = "Moderate preliminary shell-side refrigerant ΔP. Check compressor condensing pressure allowance."
    else:
        status = "HIGH"
        note = "High preliminary shell-side refrigerant ΔP. Increase baffle spacing/shell diameter, reduce baffle count, or reduce refrigerant mass velocity."

    return {
        "shell_ref_dp_kpa": dp_kpa,
        "shell_ref_dp_status": status,
        "shell_ref_dp_note": note,
        "shell_ref_mdot_kg_s_est": mdot_ref,
        "shell_ref_mass_velocity_kg_m2s": mass_velocity,
        "shell_ref_velocity_m_s": v_mix,
        "shell_ref_re": re_shell,
        "shell_ref_crossflow_area_m2": area_cross,
        "shell_ref_baffle_spaces": n_cross,
    }

def evaluate_condenser(q_rej_kw: float, water_type: str, water_in_c: float, water_out_c: float,
                       n_tubes: int, tube_passes: int, tube_length_m: float, tube: dict,
                       condensing_htc_multiplier: float = 2.5, pitch_ratio: float = 1.25,
                       shell_thk_mm: float = 6.0, fouling_m2kw: float | None = None,
                       condensing_temp_c: float = 45.0, layout: str = "triangular",
                       refrigerant: str = "R407C", baffle_spacing_mm: float | None = None,
                       baffle_cut_pct: float = 25.0, fouling_ref_m2kw: float = 0.00005,
                       discharge_temp_c: float | None = None, subcool_k: float = 3.0) -> dict:
    """Screen a water-cooled Freon condenser design.

    Heat transfer uses a conservative overall-U model. The GEWA/low-fin tube data is
    used for geometry, ID, weight and envelope area; the shell-side multiplier remains
    user-visible because exact GEWA performance requires supplier/test correlations.
    """
    water_key = (water_type or "").lower().replace(" ", "_")
    is_sea = "sea" in water_key
    # v14: temperature-dependent water/seawater properties evaluated at the mean
    # water temperature, replacing fixed constants that mis-stated Re/Pr.
    t_mean_w = 0.5 * (float(water_in_c) + float(water_out_c))
    wp = water_properties(t_mean_w, seawater=is_sea)
    cp = wp["cp"] / 1000.0     # kJ/kgK for flow calc
    rho = wp["rho"]
    mu = wp["mu"]
    k_water = wp["k"]

    dtw = max(float(water_out_c) - float(water_in_c), 0.1)
    flow_m3h = water_flow_m3h(float(q_rej_kw), dtw, cp, rho)
    tubes_per_pass = max(1, int(n_tubes) // max(1, int(tube_passes)))
    di_m = float(tube["id_mm"]) / 1000.0
    flow_area = tubes_per_pass * math.pi * di_m ** 2 / 4.0
    velocity = (flow_m3h / 3600.0) / max(flow_area, 1e-12)

    pr = wp["pr"]
    re = rho * velocity * di_m / mu
    # v14: Gnielinski replaces Dittus-Boelter (+laminar 4.36 jump). Gnielinski is
    # valid 3000 < Re < 5e6 and handles the transition region far better; below
    # Re=2300 the constant-wall-temperature laminar limit is used.
    hi = gnielinski(re, pr, k_water, di_m)
    # Internal enhancement (ribbed/grooved bore) if declared in the tube library.
    id_enh = float(tube.get("id_enhancement", 1.0))
    hi *= max(id_enh, 1.0)

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
    is_lowfin = tube.get("enhanced_surface") in ["low-fin", "GEWA-C", "GEWA-CLF", "GEWA-CPL"]
    k_wall_htc = material_k(tube.get("material", ""))

    # v14: the condensation film ΔT is now solved self-consistently instead of a
    # fixed guess. h_cond ∝ ΔT_film^(-1/4), and ΔT_film is the fraction of the
    # overall (T_sat - T_water) that falls across the condensate film, i.e. it is
    # set by the ratio of the outside-film resistance to the total resistance.
    # A short fixed-point loop converges in 3-5 iterations.
    t_water_mean = 0.5*(float(water_in_c) + float(water_out_c))
    dt_total = max(float(condensing_temp_c) - t_water_mean, 0.3)
    wall_est = float(condensing_temp_c) - 0.5*dt_total
    ho_plain = 0.0
    ho = 0.0
    bk_info = None
    for _ in range(6):
        cond_htc = nusselt_horizontal_condensation(
            k_l_r, rho_l_r, rho_v_r, mu_l_r, hfg_r,
            float(tube.get("root_od_mm", tube.get("fin_od_mm", tube["od_mm"])))/1000.0,
            float(condensing_temp_c), wall_est, tube_rows_est)
        ho_plain = cond_htc["h_plain_w_m2k"]
        if is_lowfin:
            # Beatty-Katz integral low-fin model on envelope-area basis; the user
            # multiplier now calibrates surface-tension enhancement ABOVE Beatty-Katz
            # (GEWA-CLF class typically 1.0-1.6 vs BK) instead of scaling bare Nusselt.
            bk_info = beatty_katz_lowfin_condensation(
                k_l_r, rho_l_r, rho_v_r, mu_l_r, hfg_r,
                float(condensing_temp_c), wall_est,
                float(tube.get("root_od_mm", tube["od_mm"])),
                float(tube.get("fin_od_mm", tube["od_mm"])),
                float(tube.get("fpi", 26.0)),
                float(tube.get("fin_thickness_mm", 0.25)),
                fin_k_w_mk=k_wall_htc, rows=tube_rows_est)
            bk_mult = min(max(float(condensing_htc_multiplier), 1.0), 1.8) if float(condensing_htc_multiplier) > 1.0 else 1.0
            ho = bk_info["h_envelope_w_m2k"] * bk_mult
        else:
            ho = ho_plain * max(float(condensing_htc_multiplier), 1.0)
        # Update wall temperature from resistance split (outside film vs rest),
        # referred to the outside/envelope area.
        di_ratio = float(tube.get("fin_od_mm", tube["od_mm"])) / max(float(tube["id_mm"]), 1e-6)
        r_out = 1.0/max(ho, 1.0)
        r_rest = di_ratio/max(hi, 1.0) + 0.00005 + (0.000088 if is_sea else 0.000044)
        frac_film = r_out/max(r_out + r_rest, 1e-12)
        new_wall = float(condensing_temp_c) - frac_film*dt_total
        if abs(new_wall - wall_est) < 0.05:
            wall_est = new_wall
            break
        wall_est = 0.5*(wall_est + new_wall)

    ao = math.pi * (float(tube.get("fin_od_mm", tube["od_mm"])) / 1000.0) * float(tube_length_m) * int(n_tubes)
    area_ratio_info = None
    if tube.get("enhanced_surface") in ["low-fin", "GEWA-C", "GEWA-CLF", "GEWA-CPL"]:
        area_ratio_info = enhanced_lowfin_area_ratio(float(tube.get("fin_od_mm", tube["od_mm"])), float(tube.get("root_od_mm", tube.get("fin_od_mm", tube["od_mm"]))), float(tube.get("fpi", 26.0)), float(tube.get("fin_thickness_mm", 0.25)))
    ai = math.pi * (float(tube["id_mm"]) / 1000.0) * float(tube_length_m) * int(n_tubes)
    k_wall = material_k(tube.get("material", ""))
    wall = max((float(tube.get("root_od_mm", tube["od_mm"])) - float(tube["id_mm"])) / 2000.0, 1e-4)
    rf_i = 0.000088 if is_sea else 0.000044
    rf_o = max(float(fouling_ref_m2kw), 0.0)
    if fouling_m2kw is not None:
        rf_i = max(float(fouling_m2kw), 0.0)

    # Uo on outside/envelope area basis.
    uo_inv = 1.0 / max(ho, 1.0) + (ao / max(ai, 1e-12)) / max(hi, 1.0) + rf_i + rf_o + wall / max(k_wall, 1e-9)
    uo = 1.0 / max(uo_inv, 1e-12)

    dt_hot_out = max(float(condensing_temp_c) - float(water_out_c), 0.05)
    dt_hot_in = max(float(condensing_temp_c) - float(water_in_c), 0.05)
    lmtd = _lmtd(dt_hot_out, dt_hot_in)
    q_possible_kw = uo * ao * lmtd / 1000.0

    # ---- v15: three-zone analysis (desuperheat / condense / subcool) ----
    # The single-zone model above treats the whole rejection as latent at T_cond.
    # In reality ~10-20% of the duty is desuperheating hot gas (low gas-phase HTC,
    # large ΔT) and a few percent is subcooling liquid. The zoned check computes
    # the area each zone actually needs in counterflow (water meets the subcool
    # zone first, leaves against the entering hot gas) and rescales capacity by
    # available/required area. Falls back silently to single-zone if CoolProp or
    # the discharge state is unavailable.
    zone_info = {"zone_model": "single-zone (latent only)"}
    q_possible_zoned_kw = q_possible_kw
    try:
        from CoolProp.CoolProp import PropsSI as _P
        Tk = float(condensing_temp_c) + 273.15
        p2 = float(_P("P", "T", Tk, "Q", 1, refrigerant))
        h_g = float(_P("H", "T", Tk, "Q", 1, refrigerant))
        h_f = float(_P("H", "T", Tk, "Q", 0, refrigerant))
        t_disc = float(discharge_temp_c) if discharge_temp_c else float(condensing_temp_c) + 25.0
        t_disc = max(t_disc, float(condensing_temp_c) + 2.0)
        h_disc = float(_P("H", "P", p2, "T", t_disc + 273.15, refrigerant))
        sc = max(float(subcool_k), 0.0)
        # Blend-safe subcooled enthalpy: PT flash near the bubble line fails for
        # pseudo-pure zeotropes (R407C, R404A...), so use h_f - cp_l·SC instead.
        cp_l_sat = float(_P("C", "T", Tk, "Q", 0, refrigerant))
        h_sub = h_f - cp_l_sat * sc if sc > 0.05 else h_f
        dh_desup = max(h_disc - h_g, 0.0)
        dh_lat = max(h_g - h_f, 1.0)
        dh_sub = max(h_f - h_sub, 0.0)
        dh_tot = dh_desup + dh_lat + dh_sub
        mdot_r = float(q_rej_kw) * 1000.0 / dh_tot
        q_desup = mdot_r * dh_desup / 1000.0
        q_lat = mdot_r * dh_lat / 1000.0
        q_sub = mdot_r * dh_sub / 1000.0
        # Counterflow water temperature marks: water_in -> subcool -> condense -> desuperheat -> water_out
        tw0 = float(water_in_c)
        tw1 = tw0 + dtw * (q_sub / float(q_rej_kw))
        tw2 = tw1 + dtw * (q_lat / float(q_rej_kw))
        tw3 = float(water_out_c)
        # Zone HTCs: gas desuperheating and liquid subcooling are single-phase
        # crossflow over the bundle — far weaker than film condensation. Screening
        # ratios anchored to the condensing coefficient.
        ho_desup = max(0.10 * ho, 250.0)
        ho_sub = max(0.30 * ho, 400.0)
        def _u_from_ho(h_out):
            inv = 1.0/max(h_out, 1.0) + (ao/max(ai, 1e-12))/max(hi, 1.0) + rf_i + rf_o + wall/max(k_wall, 1e-9)
            return 1.0/max(inv, 1e-12)
        u_desup = _u_from_ho(ho_desup)
        u_sub = _u_from_ho(ho_sub)
        # Zone LMTDs (hot side: gas cools t_disc->Tcond; latent at Tcond; liquid Tcond->Tcond-sc)
        lmtd_desup = _lmtd(max(t_disc - tw3, 0.05), max(float(condensing_temp_c) - tw2, 0.05))
        lmtd_lat = _lmtd(max(float(condensing_temp_c) - tw2, 0.05), max(float(condensing_temp_c) - tw1, 0.05))
        lmtd_sub = _lmtd(max(float(condensing_temp_c) - tw1, 0.05), max(float(condensing_temp_c) - sc - tw0, 0.05)) if q_sub > 1e-6 else 1.0
        a_desup = q_desup * 1000.0 / max(u_desup * lmtd_desup, 1e-9)
        a_lat = q_lat * 1000.0 / max(uo * lmtd_lat, 1e-9)
        a_sub = q_sub * 1000.0 / max(u_sub * lmtd_sub, 1e-9) if q_sub > 1e-6 else 0.0
        a_req = a_desup + a_lat + a_sub
        q_possible_zoned_kw = float(q_rej_kw) * ao / max(a_req, 1e-9)
        zone_info = {
            "zone_model": "three-zone (desuperheat/condense/subcool)",
            "zone_q_desuperheat_kw": round(q_desup, 2),
            "zone_q_condense_kw": round(q_lat, 2),
            "zone_q_subcool_kw": round(q_sub, 2),
            "zone_area_desuperheat_m2": round(a_desup, 3),
            "zone_area_condense_m2": round(a_lat, 3),
            "zone_area_subcool_m2": round(a_sub, 3),
            "zone_area_required_m2": round(a_req, 3),
            "zone_u_desuperheat_w_m2k": round(u_desup, 1),
            "zone_u_subcool_w_m2k": round(u_sub, 1),
            "assumed_discharge_temp_c": round(t_disc, 1),
            "assumed_subcool_k": round(sc, 1),
        }
    except Exception:
        # Fallback three-zone split when CoolProp is unavailable or a blend state
        # call fails. This keeps the engineering/report logic active in test and
        # non-CoolProp environments while marking it clearly as an approximate
        # screening split. Typical HVAC condensers reject about 8-15% in
        # desuperheating and 2-6% in subcooling.
        t_disc = float(discharge_temp_c) if discharge_temp_c else float(condensing_temp_c) + 25.0
        sc = max(float(subcool_k), 0.0)
        f_desup = min(max((t_disc - float(condensing_temp_c)) / 250.0, 0.06), 0.15)
        f_sub = min(max(sc / 100.0, 0.0), 0.07)
        f_lat = max(0.70, 1.0 - f_desup - f_sub)
        norm = f_desup + f_lat + f_sub
        q_desup = float(q_rej_kw) * f_desup / norm
        q_lat = float(q_rej_kw) * f_lat / norm
        q_sub = float(q_rej_kw) * f_sub / norm
        tw0 = float(water_in_c)
        tw1 = tw0 + dtw * (q_sub / float(q_rej_kw))
        tw2 = tw1 + dtw * (q_lat / float(q_rej_kw))
        tw3 = float(water_out_c)
        ho_desup = max(0.10 * ho, 250.0)
        ho_sub = max(0.30 * ho, 400.0)
        def _u_from_ho_fb(h_out):
            inv = 1.0/max(h_out, 1.0) + (ao/max(ai, 1e-12))/max(hi, 1.0) + rf_i + rf_o + wall/max(k_wall, 1e-9)
            return 1.0/max(inv, 1e-12)
        u_desup = _u_from_ho_fb(ho_desup)
        u_sub = _u_from_ho_fb(ho_sub)
        lmtd_desup = _lmtd(max(t_disc - tw3, 0.05), max(float(condensing_temp_c) - tw2, 0.05))
        lmtd_lat = _lmtd(max(float(condensing_temp_c) - tw2, 0.05), max(float(condensing_temp_c) - tw1, 0.05))
        lmtd_sub = _lmtd(max(float(condensing_temp_c) - sc - tw0, 0.05), max(float(condensing_temp_c) - sc - tw1, 0.05)) if q_sub > 1e-6 else 1.0
        a_desup = q_desup * 1000.0 / max(u_desup * lmtd_desup, 1e-9)
        a_lat = q_lat * 1000.0 / max(uo * lmtd_lat, 1e-9)
        a_sub = q_sub * 1000.0 / max(u_sub * lmtd_sub, 1e-9) if q_sub > 1e-6 else 0.0
        a_req = a_desup + a_lat + a_sub
        q_possible_zoned_kw = float(q_rej_kw) * ao / max(a_req, 1e-9)
        zone_info = {
            "zone_model": "three-zone approximate fallback (no CoolProp)",
            "zone_q_desuperheat_kw": round(q_desup, 2),
            "zone_q_condense_kw": round(q_lat, 2),
            "zone_q_subcool_kw": round(q_sub, 2),
            "zone_area_desuperheat_m2": round(a_desup, 3),
            "zone_area_condense_m2": round(a_lat, 3),
            "zone_area_subcool_m2": round(a_sub, 3),
            "zone_area_required_m2": round(a_req, 3),
            "zone_u_desuperheat_w_m2k": round(u_desup, 1),
            "zone_u_subcool_w_m2k": round(u_sub, 1),
            "assumed_discharge_temp_c": round(t_disc, 1),
            "assumed_subcool_k": round(sc, 1),
        }
    # Use the more conservative (physically stricter) of the two estimates.
    q_possible_kw = min(q_possible_kw, q_possible_zoned_kw)

    bundle = estimate_bundle_diameter_mm(int(n_tubes), float(tube["od_mm"]), pitch_ratio, layout)
    sid = estimate_shell_id_mm(bundle)
    baffle_spacing_m = (float(baffle_spacing_mm)/1000.0) if baffle_spacing_mm else max(0.08, min(float(tube_length_m)/6.0, sid/1000.0/2.0))
    shell_ref_dp = estimate_shell_refrigerant_dp_kpa(
        float(q_rej_kw), refrigerant, float(condensing_temp_c), sid, bundle, float(tube_length_m),
        baffle_spacing_m * 1000.0, float(baffle_cut_pct), int(n_tubes), float(tube["od_mm"]),
        float(pitch_ratio), float(condensing_htc_multiplier)
    )
    # Keep this liquid-side Bell/Kern helper only as a geometry sensitivity indicator.
    # For condenser service, the actual shell fluid is refrigerant, so the report now
    # uses shell_ref_dp_* as the shell-side pressure-drop result.
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
        "q_possible_single_zone_kw": round(uo * ao * lmtd / 1000.0, 2),
        **zone_info,
        "condensing_temp_c": float(condensing_temp_c), "lmtd_k": lmtd,
        "water_flow_m3h": flow_m3h, "water_velocity_ms": velocity, "velocity_status": vel_status,
        "velocity_note": vel_note, "tube_dp_kpa": dp_kpa,
        "re": re, "pr": pr, "hi_w_m2k": hi, "ho_plain_w_m2k": ho_plain, "ho_w_m2k": ho,
        "condensation_model": ("Beatty-Katz low-fin (envelope basis)" if is_lowfin else "Nusselt horizontal-tube film"),
        "condensation_wall_temp_c": wall_est,
        "condensation_film_dt_k": max(float(condensing_temp_c) - wall_est, 0.0),
        "beatty_katz_fin_efficiency": (bk_info or {}).get("fin_efficiency", None),
        "beatty_katz_area_ratio": (bk_info or {}).get("area_ratio", None),
        "condensation_row_factor": (bk_info or cond_htc).get("row_factor", 1.0),
        "uo_w_m2k": uo, "area_m2": ao, "actual_area_ratio_est": (area_ratio_info or {}).get("area_ratio_actual_to_envelope", 1.0), "tubes_per_pass": tubes_per_pass,
        "baffle_spacing_mm": baffle_spacing_m*1000.0, "baffle_cut_pct": float(baffle_cut_pct),
        "shell_ref_dp_kpa": shell_ref_dp.get("shell_ref_dp_kpa", 0.0),
        "shell_ref_dp_status": shell_ref_dp.get("shell_ref_dp_status", "CHECK"),
        "shell_ref_dp_note": shell_ref_dp.get("shell_ref_dp_note", "Preliminary shell-side refrigerant pressure drop; verify by detailed design."),
        "shell_ref_mdot_kg_s_est": shell_ref_dp.get("shell_ref_mdot_kg_s_est", 0.0),
        "shell_ref_mass_velocity_kg_m2s": shell_ref_dp.get("shell_ref_mass_velocity_kg_m2s", 0.0),
        "shell_ref_velocity_m_s": shell_ref_dp.get("shell_ref_velocity_m_s", 0.0),
        "shell_ref_re": shell_ref_dp.get("shell_ref_re", 0.0),
        "shell_ref_crossflow_area_m2": shell_ref_dp.get("shell_ref_crossflow_area_m2", 0.0),
        "shell_ref_baffle_spaces": shell_ref_dp.get("shell_ref_baffle_spaces", 0.0),
        "bell_geometry_jc": shell_calc.get("shell_jc", 1.0), "bell_geometry_jl": shell_calc.get("shell_jl", 1.0), "bell_geometry_jb": shell_calc.get("shell_jb", 1.0),
        "bundle_od_mm": bundle, "shell_id_mm": sid, "shell_od_mm": sod,
        "tube_weight_kg": tube_weight, "shell_weight_kg": shell_weight, "dry_weight_kg": dry_weight,
        "tube": tube["name"], "tube_material": tube.get("material", ""), "guidance": " ".join(guidance),
    }


def auto_select_tubes(q_rej_kw, water_type, water_in_c, water_out_c, n_tubes, tube_passes, tube_length_m,
                      od_filter="All", condensing_htc_multiplier: float = 2.5, pitch_ratio: float = 1.25,
                      shell_thk_mm: float = 6.0, condensing_temp_c: float = 45.0,
                      refrigerant: str = "R407C", baffle_spacing_mm: float | None = None,
                      baffle_cut_pct: float = 25.0) -> pd.DataFrame:
    rows=[]
    for tube in filter_tubes(water_type, od_filter):
        r = evaluate_condenser(q_rej_kw, water_type, water_in_c, water_out_c, n_tubes, tube_passes, tube_length_m,
                               tube, condensing_htc_multiplier, pitch_ratio, shell_thk_mm,
                               condensing_temp_c=condensing_temp_c, refrigerant=refrigerant,
                               baffle_spacing_mm=baffle_spacing_mm, baffle_cut_pct=baffle_cut_pct)
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

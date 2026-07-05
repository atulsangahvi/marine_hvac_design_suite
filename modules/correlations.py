"""Engineering correlations for Marine Chiller Suite v8.

This module is the beginning of Milestone 1 engineering core: common single-phase,
condensation, boiling, Bell/Kern shell-side and enhanced-tube geometry functions.
Correlations are deliberately exposed with intermediate outputs for audit.
"""
from __future__ import annotations
import math
from dataclasses import dataclass, asdict
from typing import Dict

G = 9.80665


def clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def water_properties(temp_c: float, seawater: bool = False, salinity_g_kg: float = 35.0) -> Dict[str, float]:
    """Temperature-dependent liquid water / seawater transport properties.

    v14: replaces the previous fixed constants (e.g. mu = 0.00075 Pa·s regardless of
    temperature) that skewed Re, Pr and HTC. Fresh-water fits are standard
    engineering polynomials valid 0-90 °C; seawater corrections follow the
    Sharqawy/MIT seawater property correlations trend at standard salinity.

    Returns rho [kg/m3], cp [J/kgK], k [W/mK], mu [Pa·s], pr [-].
    """
    t = clamp(float(temp_c), 0.0, 95.0)
    # Fresh water density (Kell-style polynomial, ±0.01%)
    rho = (999.842594 + 6.793952e-2*t - 9.095290e-3*t*t + 1.001685e-4*t**3
           - 1.120083e-6*t**4 + 6.536332e-9*t**5)
    # Dynamic viscosity, Vogel equation fit for water (±1%)
    mu = 1e-3*math.exp(-3.7188 + 578.919/(t + 273.15 - 137.546))
    # Thermal conductivity quadratic fit (±1%)
    k = 0.5706 + 1.756e-3*t - 6.46e-6*t*t
    # Isobaric specific heat, weak minimum near 35 °C
    cp = 4217.4 - 3.720283*t + 0.1412855*t*t - 2.654387e-3*t**3 + 2.093236e-5*t**4
    if seawater:
        s = clamp(salinity_g_kg, 0.0, 45.0)
        rho *= 1.0 + 7.6e-4*s            # ≈ +2.7% at S=35
        mu *= 1.0 + 2.7e-3*s             # ≈ +9.5% at S=35
        k *= 1.0 - 4.0e-4*s              # slight reduction
        cp *= 1.0 - 1.55e-3*s            # ≈ 3.99 kJ/kgK at S=35, 25 °C
    pr = cp*mu/max(k, 1e-12)
    return {"rho": rho, "cp": cp, "k": k, "mu": mu, "pr": pr}


def beatty_katz_lowfin_condensation(k_l: float, rho_l: float, rho_v: float, mu_l: float,
                                    h_fg: float, t_sat_c: float, wall_temp_c: float,
                                    root_od_mm: float, fin_od_mm: float, fpi: float,
                                    fin_thickness_mm: float = 0.25, fin_k_w_mk: float = 45.0,
                                    rows: int = 1) -> Dict[str, float]:
    """Beatty-Katz (1948) film condensation on integral low-fin horizontal tubes.

    h_BK = 0.689 [k³ ρ_l(ρ_l-ρ_v) g h'_fg / (μ_l ΔT)]^0.25 * (1/D_eq)^0.25 basis,
    expressed through the area-weighted equivalent diameter:

        A_eff/D_eq^0.25 = η_f·A_f/L_f^0.25 + A_root/D_root^0.25
        with L_f = π(D_fin² - D_root²)/(4 D_fin)  (mean fin height dimension)

    The result is returned per unit ENVELOPE area (π·D_fin·L) so it can be used
    directly with the envelope-basis Uo bookkeeping in the condenser module.
    Beatty-Katz is conservative for surface-tension-drained tubes (GEWA-CLF /
    Turbo-C class typically exceed it by 20-60%); a visible calibration
    multiplier on top remains appropriate for supplier-validated designs.
    """
    dT = max(t_sat_c - wall_temp_c, 0.2)
    d_r = max(root_od_mm, 1.0)/1000.0
    d_f = max(fin_od_mm, root_od_mm + 0.2)/1000.0
    fins_per_m = max(fpi, 1.0)/0.0254
    pitch = 1.0/fins_per_m
    t_fin = min(max(fin_thickness_mm/1000.0, 1e-5), 0.8*pitch)
    # Areas per metre of tube
    a_fin = fins_per_m*(2.0*(math.pi/4.0)*(d_f*d_f - d_r*d_r) + math.pi*d_f*t_fin)
    a_root = math.pi*d_r*max(pitch - t_fin, 0.0)*fins_per_m
    a_total = a_fin + a_root
    a_envelope = math.pi*d_f
    # Fin efficiency for a short annular fin in condensation (h guessed then refined once)
    fin_h = 0.5*(d_f - d_r)
    nusselt_const = 0.689*((k_l**3*rho_l*max(rho_l - rho_v, 1.0)*G*
                            (h_fg + 0.68*0.0))/(max(mu_l, 1e-12)*dT))**0.25
    l_fin = math.pi*(d_f*d_f - d_r*d_r)/(4.0*d_f)
    h_guess = nusselt_const*(1.0/max(l_fin, 1e-6))**0.25
    eta_f = 1.0
    for _ in range(2):
        m = math.sqrt(2.0*max(h_guess, 1.0)/(fin_k_w_mk*t_fin))
        mL = clamp(m*fin_h, 1e-6, 30.0)
        eta_f = math.tanh(mL)/mL
        h_guess = nusselt_const*(1.0/max(l_fin, 1e-6))**0.25
    # Beatty-Katz area-weighted composite, per unit total area
    comp = (eta_f*a_fin*(1.0/max(l_fin, 1e-6))**0.25 + a_root*(1.0/d_r)**0.25)/max(a_total, 1e-12)
    h_total_area = 1.30/1.30*nusselt_const*comp  # per actual (finned) area
    row_factor = max(int(rows), 1)**(-1.0/6.0)   # inundation milder on finned tubes than plain (Kern N^-1/6)
    h_envelope = h_total_area*(a_total/max(a_envelope, 1e-12))*row_factor
    return {
        "h_envelope_w_m2k": h_envelope,
        "h_actual_area_w_m2k": h_total_area*row_factor,
        "fin_efficiency": eta_f,
        "area_ratio": a_total/max(a_envelope, 1e-12),
        "row_factor": row_factor,
        "film_delta_t_k": dT,
    }


def lmtd_counterflow(hot_in: float, hot_out: float, cold_in: float, cold_out: float) -> float:
    dt1 = max(hot_in - cold_out, 0.05)
    dt2 = max(hot_out - cold_in, 0.05)
    if abs(dt1 - dt2) < 1e-9:
        return dt1
    return (dt1 - dt2) / max(math.log(dt1 / dt2), 1e-12)


def friction_factor(re: float, roughness_m: float = 1.5e-6, d_m: float = 0.01) -> float:
    re = max(re, 1e-9)
    if re < 2300:
        return 64.0/re
    eod = roughness_m/max(d_m, 1e-12)
    # Swamee-Jain explicit turbulent factor
    return 0.25/(math.log10(eod/3.7 + 5.74/(re**0.9))**2)


def gnielinski(re: float, pr: float, k: float, d_m: float, f: float | None = None) -> float:
    if re < 2300:
        return max(3.66*k/max(d_m, 1e-12), 0.0)
    f = friction_factor(re, d_m=d_m) if f is None else f
    nu = ((f/8)*(re-1000)*pr)/max(1 + 12.7*math.sqrt(f/8)*(pr**(2/3)-1), 1e-12)
    return max(nu*k/max(d_m, 1e-12), 0.0)


def nusselt_horizontal_condensation(k_l: float, rho_l: float, rho_v: float, mu_l: float,
                                    h_fg: float, tube_od_m: float, t_sat_c: float,
                                    wall_temp_c: float, rows: int = 1) -> Dict[str, float]:
    """Nusselt laminar film condensation outside horizontal tubes.

    h = 0.725 [ k^3 rho_l (rho_l-rho_v) g h_fg / (mu_l D ΔT) ]^0.25
    Tube-bank inundation is approximated by rows^-0.25.
    """
    dT = max(t_sat_c - wall_temp_c, 0.2)
    base = 0.725*((k_l**3*rho_l*max(rho_l-rho_v, 1.0)*G*h_fg)/(max(mu_l,1e-12)*max(tube_od_m,1e-9)*dT))**0.25
    row_factor = max(int(rows), 1)**(-0.25)
    return {"h_plain_w_m2k": base*row_factor, "row_factor": row_factor, "film_delta_t_k": dT}


def cooper_pool_boiling(p_red: float, mol_weight: float, q_flux_w_m2: float, roughness_um: float = 1.0) -> float:
    """Cooper pool boiling screening correlation.

    h is returned in W/m²K. q_flux is W/m². Validity depends on refrigerant and surface;
    enhanced tubes need a calibrated multiplier.
    """
    pr = clamp(p_red, 0.001, 0.95)
    q = max(q_flux_w_m2, 1.0)
    rp = max(roughness_um, 0.01)
    h = 55.0*(pr**(0.12 - 0.2*math.log10(rp)))*((-math.log10(pr))**-0.55)*(max(mol_weight, 10.0)**-0.5)*(q**0.67)
    return max(h, 100.0)


def enhanced_lowfin_area_ratio(fin_od_mm: float, root_od_mm: float, fpi: float, fin_thickness_mm: float = 0.25) -> Dict[str, float]:
    """Calculate outside area ratio for an integral low-fin tube using simple annular fin geometry.

    Reference area is envelope/plain area π*fin_od*L. This is suitable for comparing
    actual finned area and envelope-area U reporting.
    """
    do = fin_od_mm/1000
    dr = root_od_mm/1000
    fins_per_m = fpi/0.0254
    pitch = 1.0/max(fins_per_m, 1e-12)
    t = min(max(fin_thickness_mm/1000, 1e-5), 0.8*pitch)
    bare_fraction = max((pitch-t)/pitch, 0.0)
    bare_area_per_m = math.pi*dr*bare_fraction
    fin_side_area_per_m = fins_per_m*2.0*(math.pi/4.0)*(do*do - dr*dr)
    fin_tip_area_per_m = fins_per_m*math.pi*do*t
    actual = bare_area_per_m + fin_side_area_per_m + fin_tip_area_per_m
    envelope = math.pi*do
    return {"actual_area_per_m2_per_m": actual, "envelope_area_per_m2_per_m": envelope, "area_ratio_actual_to_envelope": actual/max(envelope,1e-12)}


@dataclass
class BellKernInput:
    mdot_kg_s: float
    rho: float
    mu: float
    cp: float
    k: float
    shell_id_m: float
    tube_od_m: float
    pitch_m: float
    baffle_spacing_m: float
    baffle_cut_pct: float
    tube_count: int
    layout: str = "triangular"
    shell_bundle_clearance_m: float = 0.012
    diametral_baffle_shell_clearance_m: float = 0.003
    tube_baffle_clearance_m: float = 0.0008
    seal_strip_pairs: int = 0


def bell_delaware_screening(inp: BellKernInput) -> Dict[str, float]:
    """Bell-Delaware/Kern hybrid with explicit correction factors.

    This is not full HTRI, but it is a traceable step beyond simple Kern: it exposes
    Jc, Jl, Jb, Jr and Js factors. Clearances can be refined when mechanical detail
    is available.
    """
    p = max(inp.pitch_m, 1.05*inp.tube_od_m)
    ds = max(inp.shell_id_m, 5*inp.tube_od_m)
    bs = clamp(inp.baffle_spacing_m, 0.05, 2.0)
    cut = clamp(inp.baffle_cut_pct, 15.0, 45.0)
    clearance = max(p - inp.tube_od_m, 1e-5)
    as_cross = max(ds*bs*clearance/p, 1e-6)
    v = inp.mdot_kg_s/max(inp.rho*as_cross,1e-12)
    if inp.layout.lower().startswith("tri"):
        de = max(0.003, 1.10*(p*p - 0.917*inp.tube_od_m*inp.tube_od_m)/inp.tube_od_m)
    else:
        de = max(0.003, 1.27*(p*p - 0.785*inp.tube_od_m*inp.tube_od_m)/inp.tube_od_m)
    re = inp.rho*v*de/max(inp.mu,1e-12)
    pr = inp.cp*inp.mu/max(inp.k,1e-12)
    # Kern shell-side Nusselt form: Nu = 0.36 Re^0.55 Pr^(1/3) for 2e3 < Re < 1e6.
    # (v14 fix: the previous exponent -0.55 on jh produced Nu ∝ Re^0.45 and
    # under-predicted shell HTC by ~2-2.5x at typical Re. Correct Kern jh is
    # 0.36 Re^-0.45 so that jh*Re = 0.36 Re^0.55.)
    # Below Re=2000 blend smoothly toward a laminar crossflow floor Nu ≈ 0.6 Re^0.5 Pr^(1/3).
    if re >= 2000.0:
        nu_ideal = 0.36*re**0.55*pr**(1/3)
    else:
        nu_turb_at_2000 = 0.36*2000.0**0.55
        nu_lam = 0.60*max(re, 1.0)**0.5
        w = clamp(re/2000.0, 0.0, 1.0)
        nu_ideal = ((1.0-w)*nu_lam + w*nu_turb_at_2000*(re/2000.0)**0.55)*pr**(1/3)
    h_ideal = nu_ideal*inp.k/max(de,1e-12)
    # Correction factors (screening equations/trends)
    window_fraction = cut/100.0
    jc = clamp(0.55 + 0.72*(0.25 - abs(window_fraction-0.25)), 0.55, 1.05)
    leakage_area_ratio = clamp((inp.diametral_baffle_shell_clearance_m*ds + inp.tube_baffle_clearance_m*inp.tube_count*inp.tube_od_m)/(as_cross+1e-12), 0, 0.6)
    jl = clamp(math.exp(-1.33*leakage_area_ratio), 0.55, 1.0)
    bypass_ratio = clamp(inp.shell_bundle_clearance_m*bs/(as_cross+1e-12), 0, 0.7)
    seal_factor = clamp(1.0 - 0.08*inp.seal_strip_pairs, 0.45, 1.0)
    jb = clamp(math.exp(-1.25*bypass_ratio*seal_factor), 0.50, 1.0)
    jr = 1.0 if re > 100 else clamp((re/100.0)**0.18, 0.70, 1.0)
    js = 1.0  # unequal end-spacing correction when inlet/outlet spacing is known
    h_corr = h_ideal*jc*jl*jb*jr*js
    f = 8.0*max(re,1.0)**-0.18 if re > 100 else 64/max(re,1.0)
    n_cross = max(1.0, math.sqrt(max(inp.tube_count,1))/2.0)
    dp_cross = f*n_cross*0.5*inp.rho*v*v
    dp_window = (0.8 + 2.0*window_fraction)*0.5*inp.rho*v*v*max(1.0,n_cross/3.0)
    dp = (dp_cross + dp_window)/(max(jl*jb,0.25))
    return {
        "shell_cross_area_m2": as_cross, "shell_de_m": de, "shell_velocity_ms": v,
        "shell_re": re, "shell_pr": pr, "shell_h_ideal_w_m2k": h_ideal,
        "shell_jc": jc, "shell_jl": jl, "shell_jb": jb, "shell_jr": jr, "shell_js": js,
        "shell_h_corrected_w_m2k": h_corr, "shell_dp_kpa": dp/1000.0,
        "leakage_area_ratio": leakage_area_ratio, "bypass_area_ratio": bypass_ratio,
    }

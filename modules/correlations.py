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
    # Kern Colburn factor approximation
    if re < 100:
        jh = 0.9*max(re,1)**-0.5
    elif re < 1000:
        jh = 0.52*re**-0.5
    else:
        jh = 0.36*re**-0.55
    h_ideal = jh*re*pr**(1/3)*inp.k/max(de,1e-12)
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

from __future__ import annotations
import math
import pandas as pd

try:
    from CoolProp.CoolProp import PropsSI
except Exception:  # pragma: no cover
    PropsSI = None

# v15: EN 12735-1 / ACR-style copper tube wall thicknesses replace the previous
# guessed id = max(od-1.2, od*0.88), which was up to 1.3 mm off on large sizes.
COPPER_TUBE_WALL_MM = {6: 0.8, 8: 0.8, 10: 0.8, 12: 0.8, 16: 1.0, 19: 1.0, 22: 1.1,
                       28: 1.2, 35: 1.4, 42: 1.5, 54: 2.0, 67: 2.0, 76: 2.0, 89: 2.5, 108: 2.5}
PIPE_OD_COPPER_MM = sorted(COPPER_TUBE_WALL_MM)

def _area(d_mm): return math.pi*(d_mm/1000)**2/4

def copper_id_mm(od_mm: float) -> float:
    wall = COPPER_TUBE_WALL_MM.get(int(round(od_mm)), max(0.8, 0.02*od_mm))
    return max(od_mm - 2.0*wall, 1.0)

def equivalent_length(actual_m: float, fittings: int=6, allowance_pct: float=40.0) -> float:
    return actual_m*(1+allowance_pct/100.0) + fittings*1.5

def line_conditions(ref: str, line: str, evap_c: float, cond_c: float,
                    superheat_k: float = 6.0, subcool_k: float = 3.0,
                    discharge_temp_c: float | None = None) -> dict:
    """Refrigerant density/viscosity at the actual line state.

    v15: previously a single default viscosity of 1.2e-5 Pa·s (a vapor value)
    was applied to all lines, understating liquid-line pressure drop ~15x.
    line: 'suction' | 'discharge' | 'liquid'
    """
    if PropsSI is None:
        fallback = {"suction": (12.0, 1.15e-5), "discharge": (55.0, 1.35e-5), "liquid": (1100.0, 1.7e-4)}
        rho, mu = fallback.get(line, fallback["suction"])
        return {"rho": rho, "mu": mu, "basis": "fallback constants (CoolProp missing)"}
    if line == "suction":
        p = PropsSI("P", "T", evap_c + 273.15, "Q", 1, ref)
        T = evap_c + superheat_k + 273.15
    elif line == "discharge":
        p = PropsSI("P", "T", cond_c + 273.15, "Q", 1, ref)
        T = (discharge_temp_c if discharge_temp_c else cond_c + 25.0) + 273.15
    else:  # liquid
        p = PropsSI("P", "T", cond_c + 273.15, "Q", 0, ref)
        T = cond_c - subcool_k + 273.15
    rho = float(PropsSI("D", "P", p, "T", T, ref))
    mu = float(PropsSI("V", "P", p, "T", T, ref))
    return {"rho": rho, "mu": mu, "p_pa": float(p), "t_c": T - 273.15, "basis": f"CoolProp {line} state"}

def line_velocity_from_mdot(mdot_kg_s: float, density_kg_m3: float, id_mm: float) -> float:
    if mdot_kg_s<=0 or density_kg_m3<=0 or id_mm<=0: return 0.0
    return mdot_kg_s/density_kg_m3/_area(id_mm)

def pressure_drop_simple(mdot_kg_s: float, density: float, mu: float, id_mm: float, length_m: float, roughness_m: float=1.5e-6) -> float:
    if min(mdot_kg_s,density,mu,id_mm,length_m) <= 0: return 0.0
    D=id_mm/1000; v=line_velocity_from_mdot(mdot_kg_s,density,id_mm); Re=density*v*D/mu
    if Re < 2300: f=64/max(Re,1)
    else:
        f=0.25/(math.log10(roughness_m/(3.7*D)+5.74/(Re**0.9))**2)
    return f*(length_m/D)*(density*v*v/2)/1000

def sat_temp_penalty_k(ref: str, line: str, evap_c: float, cond_c: float, dp_kpa: float) -> float:
    """Equivalent saturation-temperature loss caused by the line pressure drop."""
    if PropsSI is None or dp_kpa <= 0:
        return 0.0
    try:
        t_ref = evap_c if line == "suction" else cond_c
        p0 = PropsSI("P", "T", t_ref + 273.15, "Q", 1, ref)
        p1 = max(1000.0, p0 - dp_kpa*1000.0)
        return t_ref - (PropsSI("T", "P", p1, "Q", 1, ref) - 273.15)
    except Exception:
        return 0.0

def select_line_size(mdot_kg_s: float, density: float, target_v_low: float, target_v_high: float,
                     max_dp_kpa: float, length_m: float, mu: float=1.2e-5,
                     ref: str | None = None, line: str | None = None,
                     evap_c: float = 5.0, cond_c: float = 45.0) -> pd.DataFrame:
    rows=[]
    for od in PIPE_OD_COPPER_MM:
        id_mm=copper_id_mm(od)
        v=line_velocity_from_mdot(mdot_kg_s,density,id_mm)
        dp=pressure_drop_simple(mdot_kg_s,density,mu,id_mm,length_m)
        row={'OD mm':od,'ID mm':round(id_mm,1),'velocity m/s':round(v,2),'dp kPa':round(dp,2)}
        if ref and line in ("suction","discharge"):
            row['sat temp loss K']=round(sat_temp_penalty_k(ref,line,evap_c,cond_c,dp),3)
        row['status']='OK' if target_v_low<=v<=target_v_high and dp<=max_dp_kpa else 'CHECK'
        rows.append(row)
    return pd.DataFrame(rows)

def oil_return_guidance(compressor_type: str, suction_velocity: float, vertical_riser_m: float) -> dict:
    min_v = 7.5 if vertical_riser_m>1 else 4.0
    required = suction_velocity < min_v
    return {'oil_return_ok': not required, 'minimum_suction_velocity_m_s': min_v, 'actual_suction_velocity_m_s': suction_velocity, 'recommendation': 'Use smaller riser/double riser/oil separator and check part-load velocity.' if required else 'Oil return velocity appears acceptable for screening.'}

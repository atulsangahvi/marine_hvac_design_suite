from __future__ import annotations
import math
import pandas as pd

PIPE_OD_COPPER_MM = [6,8,10,12,16,19,22,28,35,42,54,67,76,89,108]

def _area(d_mm): return math.pi*(d_mm/1000)**2/4

def equivalent_length(actual_m: float, fittings: int=6, allowance_pct: float=40.0) -> float:
    return actual_m*(1+allowance_pct/100.0) + fittings*1.5

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

def select_line_size(mdot_kg_s: float, density: float, target_v_low: float, target_v_high: float, max_dp_kpa: float, length_m: float, mu: float=1.2e-5) -> pd.DataFrame:
    rows=[]
    for od in PIPE_OD_COPPER_MM:
        id_mm=max(od-1.2, od*0.88)
        v=line_velocity_from_mdot(mdot_kg_s,density,id_mm)
        dp=pressure_drop_simple(mdot_kg_s,density,mu,id_mm,length_m)
        status='OK' if target_v_low<=v<=target_v_high and dp<=max_dp_kpa else 'CHECK'
        rows.append({'OD mm':od,'ID mm':round(id_mm,1),'velocity m/s':round(v,2),'dp kPa':round(dp,2),'status':status})
    return pd.DataFrame(rows)

def oil_return_guidance(compressor_type: str, suction_velocity: float, vertical_riser_m: float) -> dict:
    min_v = 7.5 if vertical_riser_m>1 else 4.0
    required = suction_velocity < min_v
    return {'oil_return_ok': not required, 'minimum_suction_velocity_m_s': min_v, 'actual_suction_velocity_m_s': suction_velocity, 'recommendation': 'Use smaller riser/double riser/oil separator and check part-load velocity.' if required else 'Oil return velocity appears acceptable for screening.'}

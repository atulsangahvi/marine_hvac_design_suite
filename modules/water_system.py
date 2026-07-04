from __future__ import annotations
import math
import pandas as pd

def fluid_props(fluid: str='Water', glycol_pct: float=0.0, temp_c: float=7.0) -> dict:
    g=max(0,min(glycol_pct,60))/100
    rho=1000*(1+0.08*g)
    cp=4.186*(1-0.18*g)
    mu=0.001*(1+8*g)
    freeze_c = 0 - 0.55*glycol_pct if glycol_pct>0 else 0.0
    return {'rho_kg_m3':rho,'cp_kj_kgK':cp,'mu_Pa_s':mu,'freeze_point_c':freeze_c}

def flow_for_capacity(q_kw: float, tin_c: float, tout_c: float, fluid='Water', glycol_pct=0.0):
    props=fluid_props(fluid,glycol_pct,(tin_c+tout_c)/2)
    dt=abs(tin_c-tout_c)
    m=q_kw/max(props['cp_kj_kgK']*dt,1e-9)
    return {'mass_flow_kg_s':m,'volume_flow_m3_h':m/props['rho_kg_m3']*3600, **props}

def pump_head_summary(evap_dp_kpa: float, pipe_dp_kpa: float, valve_dp_kpa: float, margin_pct: float=15.0):
    total=(evap_dp_kpa+pipe_dp_kpa+valve_dp_kpa)*(1+margin_pct/100)
    return {'evaporator_dp_kpa':evap_dp_kpa,'pipe_dp_kpa':pipe_dp_kpa,'valve_dp_kpa':valve_dp_kpa,'pump_head_kpa':total,'pump_head_m_water':total/9.81}

def water_system_table(q_kw,tin,tout,pipe_id_mm,fluid='Water',glycol_pct=0,evap_dp_kpa=50,extra_dp_kpa=35):
    f=flow_for_capacity(q_kw,tin,tout,fluid,glycol_pct)
    area=math.pi*(pipe_id_mm/1000)**2/4
    vel=(f['volume_flow_m3_h']/3600)/max(area,1e-9)
    head=pump_head_summary(evap_dp_kpa, extra_dp_kpa, 20)
    rows={**f,'pipe_velocity_m_s':vel,**head}
    return pd.DataFrame([{'Parameter':k,'Value':round(v,3) if isinstance(v,(int,float)) else v} for k,v in rows.items()])

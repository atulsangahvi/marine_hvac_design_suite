import pandas as pd
from .thermo import water_flow_m3h, pipe_velocity_m_s

def water_piping_summary(q_kw, ewt_c, lwt_c, pipe_id_mm, fluid="water", glycol_pct=0):
    cp = max(3.2, 4.186*(1-0.006*glycol_pct))
    rho = 1000 + glycol_pct
    flow = water_flow_m3h(q_kw, max(ewt_c-lwt_c,0.1), cp, rho)
    vel = pipe_velocity_m_s(flow, pipe_id_mm)
    status = "OK" if 0.6 <= vel <= 2.8 else ("LOW" if vel < 0.6 else "HIGH")
    return {"flow_m3h": flow, "velocity_ms": vel, "status": status, "cp_kjkgk": cp, "rho_kgm3": rho}

def refrigerant_line_check(suction_velocity, discharge_velocity, liquid_velocity):
    rows = [
        ["Suction gas velocity", suction_velocity, "OK" if 4 <= suction_velocity <= 18 else "CHECK", "Oil return typically needs adequate suction velocity."],
        ["Discharge gas velocity", discharge_velocity, "OK" if 5 <= discharge_velocity <= 20 else "CHECK", "Avoid excessive pressure drop/noise."],
        ["Liquid velocity", liquid_velocity, "OK" if 0.3 <= liquid_velocity <= 1.5 else "CHECK", "Avoid flashing and water hammer."],
    ]
    return pd.DataFrame(rows, columns=["Check","Value m/s","Status","Guidance"])

import pandas as pd

def safety_checks(discharge_temp_c: float, max_discharge_temp_c: float, cond_pressure_margin_pct: float,
                  remaining_subcool_k: float, water_flow_ok: bool, eev_superheat_k: float) -> pd.DataFrame:
    rows=[]
    def add(check, status, note): rows.append([check,status,note])
    add("Discharge temperature", "OK" if discharge_temp_c <= max_discharge_temp_c else "ALARM", f"{discharge_temp_c:.1f} °C vs limit {max_discharge_temp_c:.1f} °C")
    add("High pressure margin", "OK" if cond_pressure_margin_pct >= 10 else "WARNING", f"Margin to HP trip {cond_pressure_margin_pct:.1f}%")
    add("Liquid subcooling", "OK" if remaining_subcool_k >= 2 else "WARNING", f"Remaining subcooling {remaining_subcool_k:.1f} K; low value can cause flash gas at EEV")
    add("Water flow proving", "OK" if water_flow_ok else "ALARM", "Flow switch must be proven before compressor start")
    add("EEV superheat", "OK" if 4 <= eev_superheat_k <= 10 else "CHECK", "Typical target 5–8 K; add low superheat cutback")
    return pd.DataFrame(rows, columns=["Safety check","Status","Engineering note"])

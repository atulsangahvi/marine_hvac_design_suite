from __future__ import annotations
import pandas as pd
from typing import Dict, List


def operating_envelope_checks(evap_c:float, cond_c:float, max_cond_c:float, min_evap_c:float, max_discharge_temp_c:float, actual_discharge_temp_c:float, comp_current_pct:float=85.0) -> pd.DataFrame:
    rows: List[Dict[str, object]] = []
    def status(ok, warn=False):
        return "WARN" if warn and ok else ("OK" if ok else "FAIL")
    rows.append({"Check":"Evaporating temperature envelope", "Value":f"{evap_c:.1f} °C", "Limit":f">= {min_evap_c:.1f} °C", "Status":status(evap_c>=min_evap_c), "Guidance":"Raise evaporating temperature, increase water flow, reduce refrigerant pressure drop or select different compressor."})
    rows.append({"Check":"Condensing temperature envelope", "Value":f"{cond_c:.1f} °C", "Limit":f"<= {max_cond_c:.1f} °C", "Status":status(cond_c<=max_cond_c), "Guidance":"Increase condenser area/water flow, clean condenser, reduce air/water inlet temperature or select different compressor."})
    rows.append({"Check":"Discharge temperature", "Value":f"{actual_discharge_temp_c:.1f} °C", "Limit":f"<= {max_discharge_temp_c:.1f} °C", "Status":status(actual_discharge_temp_c<=max_discharge_temp_c), "Guidance":"Lower compression ratio, improve suction cooling only if allowed, add liquid injection if compressor approved, or select different refrigerant/compressor."})
    rows.append({"Check":"Motor current margin", "Value":f"{comp_current_pct:.0f}%", "Limit":"<= 100% FLA/MCC", "Status":status(comp_current_pct<=100, warn=comp_current_pct>90), "Guidance":"Unload compressor or lower condensing pressure if current is high."})
    return pd.DataFrame(rows)


def predicted_condenser_shortfall_action(required_kw:float, possible_kw:float) -> pd.DataFrame:
    short = required_kw - possible_kw
    pct = 100*short/max(required_kw,1e-9)
    if short <= 0:
        rows = [["Thermal capacity", "OK", f"Margin {abs(short):.1f} kW", "No thermal action required; still verify pressure drop, vibration and fouling."]]
    elif pct <= 7:
        rows = [["Thermal capacity", "SMALL SHORTFALL", f"Short {short:.1f} kW ({pct:.1f}%)", "System may operate at slightly higher condensing temperature; check compressor derating, amps, HP margin and subcooling."]]
    else:
        rows = [["Thermal capacity", "FAIL", f"Short {short:.1f} kW ({pct:.1f}%)", "Increase tube count/length/enhancement, reduce fouling allowance, increase water flow if water-side limited, or select larger condenser."]]
    return pd.DataFrame(rows, columns=["Check","Status","Result","Action"])

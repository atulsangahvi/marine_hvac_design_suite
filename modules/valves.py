import math
import pandas as pd

def expansion_valve_screening(capacity_kw: float, refrigerant: str, evap_c: float, cond_c: float,
                              subcool_k: float, valve_type: str = "EEV") -> dict:
    # Preliminary only; vendor sizing requires refrigerant tables, pressure drop and selected valve family.
    valve_dp_bar = max(2.0, 0.55*(cond_c-evap_c))
    nominal_kw = capacity_kw * 1.15
    return {"valve_type": valve_type, "refrigerant": refrigerant, "nominal_capacity_kw": nominal_kw,
            "estimated_valve_dp_bar": valve_dp_bar, "selection_note": "Select exact valve from Danfoss/Carel/Sporlan by refrigerant, capacity, pressure drop and MOP."}

def solenoid_filter_drier_screening(liquid_line_mm: float, refrigerant: str, capacity_kw: float) -> pd.DataFrame:
    if liquid_line_mm <= 10: sol="EVR 6 / equivalent"
    elif liquid_line_mm <= 16: sol="EVR 10/15 / equivalent"
    else: sol="EVR 20+ / equivalent"
    rows=[
        ["Liquid solenoid", sol, "Match ODS size, MOPD, coil voltage, refrigerant approval"],
        ["Filter drier", "Replaceable core if serviceable marine unit", "Size by capacity and pressure drop"],
        ["Sight glass", "Moisture indicator type", "Install after filter drier before EEV"],
    ]
    return pd.DataFrame(rows, columns=["Component","Preliminary selection","Engineering note"])

import pandas as pd

def plc_logic_table(eev=True, compressor_control="Fixed speed", condenser_control="Pressure switches"):
    rows=[
        ["Start permissive", "Power healthy, emergency stop reset, phase relay OK, HP/LP healthy, water flow proven", "Do not start compressor without flow and safety chain."],
        ["Pump start", "Start chilled-water pump before compressor; prove flow after delay", "Typical 10-30 s flow proving delay."],
        ["Compressor start", "Start unloaded where possible; enforce anti-short-cycle timer", "Protect motor and refrigerant system."],
        ["Condenser control", condenser_control, "Maintain head pressure while avoiding excessive condensing pressure."],
        ["Expansion control", "EEV superheat PID" if eev else "TXV mechanical superheat", "EEV should include min/max opening, start opening, MOP, and low superheat cutback."],
        ["High head response", "Unload/VFD reduce capacity, increase condenser water/fan, alarm before HPS", "Never simply raise HPS to hide undersized condenser."],
        ["Low suction response", "Check load/flow/EEV; open HGBP if fitted before LPS trip", "Avoid freezing and compressor short cycling."],
        ["Shutdown", "Close liquid solenoid, pumpdown to LPS, stop compressor, pump overrun", "Sequence depends on compressor type."],
    ]
    return pd.DataFrame(rows, columns=["Control function","PLC logic","Engineering note"])

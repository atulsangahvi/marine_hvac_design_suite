from __future__ import annotations
import pandas as pd


def maintenance_schedule() -> pd.DataFrame:
    rows = [
        ["Daily/shift", "Check suction/discharge pressure, CHW/CW temperatures, superheat, subcooling, alarms", "Operator log"],
        ["Weekly", "Inspect sight glass, check abnormal noise/vibration, clean strainers if pressure drop rises", "Maintenance log"],
        ["Monthly", "Check electrical terminals, contactor condition, pump/fan current, refrigerant leak scan", "PM checklist"],
        ["Quarterly", "Check condenser approach and water-side pressure drop trend; inspect seawater strainers/anodes where applicable", "Performance trend"],
        ["Half-yearly", "Calibrate pressure/temperature sensors and verify HP/LP switch operation", "Calibration record"],
        ["Yearly", "Open water boxes if seawater service, inspect tubes/tubesheets, clean tubes, verify relief valves as per code", "Annual service report"],
    ]
    return pd.DataFrame(rows, columns=["Frequency", "Task", "Record"])


def factory_acceptance_tests() -> pd.DataFrame:
    rows = [
        ["Visual and dimensional inspection", "Shell, frame, access, nameplates, flow direction markings", "Before pressure test"],
        ["Hydro/pneumatic pressure test", "As per approved pressure vessel procedure", "Qualified inspector"],
        ["Electrical continuity/IR test", "Motor and control wiring", "Before energization"],
        ["Control logic simulation", "Flow fail, HP, LP, overload, freeze, E-stop, pump-down", "Panel FAT"],
        ["Vacuum/dehydration", "Hold vacuum and micron decay as per refrigeration practice", "Before charging"],
        ["Running test", "Record pressures, temperatures, current, SH/SC, capacity indication", "Factory or site"],
    ]
    return pd.DataFrame(rows, columns=["Test", "Scope", "Hold point"])

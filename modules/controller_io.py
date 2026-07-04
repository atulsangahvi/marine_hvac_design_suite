from __future__ import annotations
import pandas as pd
from typing import List, Dict


def controller_io_list(num_circuits:int=1, num_compressors:int=1, eev:bool=True, vfd_pump:bool=False, vfd_fans:bool=False, bms:bool=True) -> pd.DataFrame:
    rows: List[Dict[str, object]] = []
    def add(tag, signal, io_type, qty, note):
        rows.append({"Tag":tag,"Signal":signal,"I/O type":io_type,"Qty":qty,"Engineering note":note})
    add("E-STOP","Emergency stop healthy","DI",1,"Hardwired safety chain; PLC monitors status.")
    add("FS-CHW","Chilled water flow proven","DI",1,"Compressor permissive.")
    add("FS-CW","Condenser water flow proven","DI",1,"Compressor permissive for water-cooled units.")
    add("TS-CHW-IN","CHW inlet temperature","AI",1,"Control/monitoring.")
    add("TS-CHW-OUT","CHW outlet temperature","AI",1,"Primary capacity control sensor.")
    add("TS-CW-IN","Condenser water inlet temperature","AI",1,"Condenser performance monitoring.")
    add("TS-CW-OUT","Condenser water outlet temperature","AI",1,"Approach and fouling monitoring.")
    add("PT-HP","High-side pressure transmitter","AI",num_circuits,"Used for HP monitoring and condenser fan/water control.")
    add("PT-LP","Low-side pressure transmitter","AI",num_circuits,"Used for superheat, LPS logic and diagnostics.")
    add("TS-SUCT","Suction temperature","AI",num_circuits,"Superheat calculation.")
    add("TS-DISC","Discharge temperature","AI",num_circuits,"High discharge temperature alarm/trip.")
    add("TS-LIQ","Liquid line temperature","AI",num_circuits,"Subcooling/flash-gas diagnosis.")
    add("HPS","High pressure safety switch","DI",num_circuits,"Manual reset safety, hardwired in compressor chain.")
    add("LPS","Low pressure switch","DI",num_circuits,"Pump-down and low-pressure protection.")
    add("OL-COMP","Compressor overload healthy","DI",num_compressors,"Hardwired motor overload status.")
    add("KM-COMP","Compressor contactor command","DO",num_compressors,"Start command after permissives and timers.")
    add("KM-PUMP","CHW pump command","DO",1,"Start before compressor; stop after delay.")
    add("YV1","Liquid solenoid command","DO",num_circuits,"Open on cooling demand; close for pump-down.")
    if eev:
        add("EEV","Electronic expansion valve command","AO/Pulse",num_circuits,"Stepper/pulse/0-10 V depending on valve driver.")
    add("CPS/FAN","Condenser fan or water regulating command","DO/AO",max(1,num_circuits),"Pressure/temperature based condensing control.")
    if vfd_pump:
        add("VFD-PUMP","Pump speed command","AO",1,"Maintain flow or differential pressure.")
    if vfd_fans:
        add("VFD-FAN","Fan speed command","AO",1,"Maintain condensing pressure with stable minimum speed.")
    add("ALARM","Common fault output","DO",1,"BMS/dry contact.")
    add("RUN","Common run output","DO",1,"BMS/dry contact.")
    if bms:
        add("BMS","Modbus/BACnet interface","COMM",1,"Expose status, alarms, temperatures, pressures and setpoints.")
    return pd.DataFrame(rows)


def alarm_matrix(max_discharge_temp_c:float=115.0, min_superheat_k:float=3.0, min_subcool_k:float=2.0) -> pd.DataFrame:
    rows = [
        ["High pressure switch trip", "HPS opens", "Immediate compressor stop", "Manual reset after cause corrected"],
        ["Low pressure trip", "LP below LPS cut-out after bypass timer", "Stop compressor / pump-down stop", "Auto or manual as selected"],
        ["No chilled water flow", "FS-CHW not proven", "Block compressor start / stop running compressor", "Auto after flow returns"],
        ["No condenser water flow", "FS-CW not proven", "Block compressor start / stop running compressor", "Auto after flow returns"],
        ["High discharge temperature", f"Tdis > {max_discharge_temp_c:.0f} °C", "Unload then trip if not recovered", "Manual reset for trip"],
        ["Low superheat", f"SH < {min_superheat_k:.1f} K", "Close EEV / unload compressor", "Auto after stable SH"],
        ["Low subcooling / flash gas risk", f"SC < {min_subcool_k:.1f} K", "Alarm; check charge/condenser/liquid line", "Auto"],
        ["Freeze protection", "Leaving CHW below freeze setting", "Stop compressor, keep pump running", "Manual or auto after temp recovery"],
        ["Compressor overload", "OL-COMP opens", "Stop affected compressor", "Manual reset at overload"],
        ["Sensor fault", "AI open/short/out-of-range", "Fallback or stop depending on sensor", "Auto after sensor healthy"],
    ]
    return pd.DataFrame(rows, columns=["Alarm", "Trigger", "Controller action", "Reset philosophy"])


def eev_control_sequence(target_superheat_k:float=6.0) -> pd.DataFrame:
    rows = [
        ["Start", "Keep EEV closed during pump-down/off cycle", "Open to start position after flow and compressor permissives"],
        ["Pull-down", "Use conservative opening limit", "Avoid floodback while suction pressure stabilizes"],
        ["Normal", f"PID controls superheat to {target_superheat_k:.1f} K", "Use suction pressure + suction temperature"],
        ["Low SH", "Close EEV quickly, unload compressor if persistent", "Protect compressor from liquid return"],
        ["High SH", "Open EEV; if 100% open and SH still high, alarm starved evaporator/flash gas", "Check charge, filter drier, liquid line subcooling"],
        ["Shutdown", "Close liquid solenoid/EEV and pump down if enabled", "Stop compressor on LPS or timeout"],
    ]
    return pd.DataFrame(rows, columns=["Mode", "Control action", "Engineering note"])

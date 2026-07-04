import math
import pandas as pd
STD_BREAKERS=[6,10,16,20,25,32,40,50,63,80,100,125,160,200,250,320,400,500,630]
STD_CONTACTORS=[9,12,18,25,32,40,50,65,80,95,115,150,185,225,265,330,400]

def next_std(v, arr):
    for x in arr:
        if v <= x: return x
    return arr[-1]

def flc_3ph(kw, v=415, pf=0.85, eff=0.90):
    if kw <= 0: return 0
    return kw*1000/(math.sqrt(3)*v*pf*eff)

def cable_size(current_a):
    table=[(1.5,14),(2.5,18),(4,25),(6,32),(10,45),(16,61),(25,80),(35,99),(50,119),(70,151),(95,182),(120,210),(150,240),(185,273),(240,321)]
    req=current_a*1.25
    for s,a in table:
        if a>=req: return s
    return 300

def electrical_schedule(compressor_kw, compressor_flc, pump_kw, fan_kw_each, fan_qty, voltage=415, fault_ka=25):
    comp_a = compressor_flc or flc_3ph(compressor_kw, voltage)
    pump_a = flc_3ph(pump_kw, voltage)
    fan_a = flc_3ph(fan_kw_each, voltage)
    total = comp_a + pump_a + fan_a*fan_qty
    rows=[
        ["Q1", "Main MCCB", next_std(total*1.25, STD_BREAKERS), f"Icu >= {max(25, fault_ka):.0f} kA", f"Cable {cable_size(total)} sqmm Cu preliminary"],
        ["KM-C1", "Compressor contactor", next_std(comp_a*1.15, STD_CONTACTORS), "AC-3", f"Cable {cable_size(comp_a)} sqmm Cu preliminary"],
        ["OL-C1", "Compressor overload", round(comp_a,1), "Set to nameplate RLA", "Verify compressor manual"],
        ["KM-P1", "Pump contactor", next_std(pump_a*1.15, STD_CONTACTORS), "AC-3", f"Cable {cable_size(pump_a)} sqmm Cu preliminary"],
        ["KM-F", "Fan contactor", next_std(fan_a*1.15, STD_CONTACTORS), "AC-3", f"Each fan cable {cable_size(fan_a)} sqmm Cu preliminary"],
    ]
    return pd.DataFrame(rows, columns=["Tag","Item","Rating / Setting","Basis","Cable"])

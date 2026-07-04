def refrigerant_mermaid(include_hgb=False, include_receiver=True):
    lines=["flowchart LR","COMP[Compressor] --> COND[Condenser]","COND --> LR[Liquid Receiver]" if include_receiver else "COND --> LL[Liquid Line]","LR --> FD[Filter Drier]" if include_receiver else "LL --> FD[Filter Drier]","FD --> SG[Sight Glass]","SG --> SOL[Liquid Solenoid]","SOL --> EEV[EEV/TXV]","EEV --> EVAP[Evaporator]","EVAP --> COMP","COND -. water in/out .- WATER[Condenser Water]","EVAP -. chilled water/air .- LOAD[Load]"]
    if include_hgb: lines.append("COMP --> HGB[Hot Gas Bypass] --> EVAP")
    return "\n".join(lines)

def control_mermaid():
    return """flowchart TD
START[Start command] --> FLOW{Water/Air flow OK?}
FLOW -- No --> AL1[Alarm no flow]
FLOW -- Yes --> SAFE{Safety chain OK?}
SAFE -- No --> AL2[Safety alarm]
SAFE -- Yes --> PUMP[Start pump/fan]
PUMP --> SOL[Open liquid solenoid]
SOL --> COMP[Start compressor after delay]
COMP --> EEV[Control EEV superheat]
EEV --> MON[Monitor HP LP Tdischarge current]
MON --> LIM{Approaching limit?}
LIM -- Yes --> UNLOAD[Unload/reduce capacity/alarm]
LIM -- No --> RUN[Continue running]
"""

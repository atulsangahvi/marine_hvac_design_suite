import pandas as pd

def base_bom(include_hgb=False, include_oil_separator=False, include_receiver=True, include_accumulator=False, include_eev=True):
    items=[
        ["Compressor", "Selected compressor", 1, "From compressor module/datasheet"],
        ["Condenser", "Shell-and-tube condenser", 1, "From condenser module"],
        ["Evaporator", "Shell-and-tube or air coil evaporator", 1, "From evaporator module"],
        ["Expansion valve", "EEV" if include_eev else "TXV", 1, "Size by refrigerant, capacity, pressure drop"],
        ["Liquid solenoid", "NC refrigerant solenoid", 1, "Pumpdown/control"],
        ["Filter drier", "Replaceable core preferred", 1, "Liquid line"],
        ["Sight glass", "Moisture indicator", 1, "Liquid line"],
        ["HPS/LPS", "Pressure controls", 2, "Settings from pressure switch module"],
        ["Flow switch", "Water flow proving", 1, "Compressor interlock"],
        ["PLC/controller", "Chiller controller", 1, "Control module logic"],
    ]
    if include_receiver: items.append(["Liquid receiver", "High-side receiver", 1, "Size for pumpdown charge"])
    if include_hgb: items.append(["Hot gas bypass", "Modulating/solenoid arrangement", 1, "Low load stability"])
    if include_oil_separator: items.append(["Oil separator", "Discharge line", 1, "Screw/long lines/low temp"])
    if include_accumulator: items.append(["Suction accumulator", "Suction line", 1, "Floodback protection"])
    return pd.DataFrame(items, columns=["Item","Type","Qty","Remarks"])

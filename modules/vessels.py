import pandas as pd

def receiver_sizing(charge_kg: float, pumpdown_fraction: float = 0.80, fill_fraction: float = 0.80, liquid_density_kgm3: float = 1050.0) -> dict:
    required_liquid_kg = charge_kg * pumpdown_fraction
    volume_l = required_liquid_kg / max(liquid_density_kgm3,1e-9) * 1000 / max(fill_fraction,0.1)
    return {"charge_kg":charge_kg,"pumpdown_fraction":pumpdown_fraction,"max_fill_fraction":fill_fraction,"receiver_volume_l":volume_l,"note":"Preliminary. Confirm refrigerant charge, code volume, relief valve and pumpdown philosophy."}

def suction_accumulator_guidance(evaporator_type: str, compressor_type: str, floodback_risk: bool) -> dict:
    required = floodback_risk or "shell side refrigerant" in evaporator_type.lower() or compressor_type.lower().startswith("scroll")
    return {"required": required, "guidance": "Use suction accumulator when liquid floodback risk exists, during low load, defrost, long piping or uncertain EEV control."}

def vessels_table(receiver: dict, accumulator: dict) -> pd.DataFrame:
    return pd.DataFrame([
        ["Liquid receiver volume", f"{receiver.get('receiver_volume_l',0):.1f} L", receiver.get("note","")],
        ["Suction accumulator", "Required" if accumulator.get("required") else "Optional", accumulator.get("guidance","")],
    ], columns=["Item","Result","Note"])

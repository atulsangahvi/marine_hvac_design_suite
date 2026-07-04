from __future__ import annotations
import pandas as pd

MATERIAL_COST_USD_KG = {'Copper':12,'CuNi 90/10':18,'CuNi 70/30':24,'Titanium':35,'SS316L':9,'Carbon steel':2.5,'Aluminum brass':10}

def weight_cost_summary(dry_weight_kg: float, tube_material: str, shell_material: str='Carbon steel', factor_internals: float=1.25) -> dict:
    tube_share=0.45*dry_weight_kg
    shell_share=0.35*dry_weight_kg
    other_share=max(0,dry_weight_kg-tube_share-shell_share)
    tube_cost=tube_share*MATERIAL_COST_USD_KG.get(tube_material,15)
    shell_cost=shell_share*MATERIAL_COST_USD_KG.get(shell_material,3)
    other_cost=other_share*6
    material=tube_cost+shell_cost+other_cost
    fabrication=material*factor_internals
    return {'tube_weight_kg':tube_share,'shell_weight_kg':shell_share,'other_weight_kg':other_share,'estimated_material_usd':material,'estimated_fabricated_cost_usd':fabrication}

def cost_table(summary: dict) -> pd.DataFrame:
    return pd.DataFrame([{'Item':k,'Value':round(v,2) if isinstance(v,(int,float)) else v} for k,v in summary.items()])

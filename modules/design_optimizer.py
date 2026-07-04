"""Automatic design optimizers for Marine Chiller Suite v8."""
from __future__ import annotations
import pandas as pd
from data.tube_library import filter_tubes
from .condenser import evaluate_condenser


def condenser_geometry_optimizer(q_rej_kw: float, water_type: str, water_in_c: float, water_out_c: float,
                                 condensing_temp_c: float, max_shell_od_mm: float = 350.0,
                                 max_length_m: float = 2.0, max_dp_kpa: float = 60.0,
                                 od_filter: str = "All", manufacturers: list[str] | None = None,
                                 refrigerant: str = "R407C") -> pd.DataFrame:
    """Grid-search feasible condenser designs across tube library and geometry.

    This is a practical first-stage optimizer. It does not yet do continuous nonlinear
    optimization, but it automatically varies tube count, passes, length and tube family.
    """
    manufacturers = manufacturers or ["All"]
    tubes=[]
    for mf in manufacturers:
        tubes.extend(filter_tubes(water_type, od_filter, "condenser", mf))
    # de-duplicate by tube name
    seen=set(); tubes=[t for t in tubes if not (t["name"] in seen or seen.add(t["name"]))]
    rows=[]
    for tube in tubes:
        for passes in [1,2,4,6,8]:
            for n_tubes in range(max(12, passes*8), 301, 4):
                if n_tubes % passes != 0:
                    continue
                for length_m in [0.8,1.0,1.2,1.4,1.6,1.8,2.0,2.4,3.0]:
                    if length_m > max_length_m:
                        continue
                    r = evaluate_condenser(q_rej_kw, water_type, water_in_c, water_out_c, n_tubes, passes, length_m, tube,
                                           condensing_htc_multiplier=2.5, pitch_ratio=1.25, shell_thk_mm=6.0,
                                           condensing_temp_c=condensing_temp_c, refrigerant=refrigerant)
                    feasible = (r["q_possible_kw"] >= q_rej_kw and r["tube_dp_kpa"] <= max_dp_kpa and r["shell_od_mm"] <= max_shell_od_mm and r["velocity_status"] != "HIGH")
                    margin = r["q_possible_kw"] - q_rej_kw
                    score = (100000 if feasible else 0) - abs(margin)*4 - r["tube_dp_kpa"]*3 - r["shell_od_mm"]*0.5 - r["dry_weight_kg"]*0.04 - (0 if r["velocity_status"]=="OK" else 5000)
                    rows.append({
                        "feasible": feasible, "score": score, "tube": r["tube"], "material": r["tube_material"],
                        "n_tubes": n_tubes, "passes": passes, "length_m": length_m,
                        "q_kw": r["q_possible_kw"], "margin_kw": margin, "velocity_ms": r["water_velocity_ms"],
                        "velocity_status": r["velocity_status"], "dp_kpa": r["tube_dp_kpa"],
                        "shell_od_mm": r["shell_od_mm"], "shell_id_mm": r["shell_id_mm"],
                        "weight_kg": r["dry_weight_kg"], "Uo": r["uo_w_m2k"], "area_m2": r["area_m2"],
                    })
    df=pd.DataFrame(rows)
    if not df.empty:
        df=df.sort_values(["feasible","score"], ascending=[False,False]).reset_index(drop=True)
    return df

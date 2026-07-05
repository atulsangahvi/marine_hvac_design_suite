"""Benchmark validation cases for the engineering core."""
from __future__ import annotations
import pandas as pd
from data.tube_library import filter_tubes
from .condenser import evaluate_condenser

BENCHMARKS = [
    {
        "name": "HSTAR UCWT018A style R407C GEWA-CLF condenser",
        "type": "condenser",
        "refrigerant": "R407C",
        "q_kw": 53.0,
        "water_type": "seawater",
        "water_in_c": 37.0,
        "water_out_c": 42.0,
        "condensing_temp_c": 47.0,
        "tube_name_contains": "GEWA-CLF 5/8 x 0.80 L10",
        "n_tubes": 64,
        "passes": 2,
        "length_m": 1.041,
        "target_shell_id_mm": 212.0,
        "target_uo_w_m2k": 3955.0,
        "target_water_flow_m3h": 9.21,
    }
]


def run_benchmarks() -> pd.DataFrame:
    rows=[]
    for b in BENCHMARKS:
        if b["type"] == "condenser":
            tubes=filter_tubes(b["water_type"], '5/8"', 'condenser')
            tube=next((t for t in tubes if b["tube_name_contains"] in t["name"]), None)
            if not tube:
                rows.append({"benchmark": b["name"], "status": "MISSING_TUBE"})
                continue
            # v14: run the comparison at the vendor RATING basis (near-clean fouling
            # rf_i = 0.000018 m2K/W, rf_o = 0), not the DESIGN fouling used for sizing.
            # Comparing a fouled design U against a clean catalogue rating previously
            # made the model look ~40% pessimistic when it was not.
            r=evaluate_condenser(b["q_kw"], b["water_type"], b["water_in_c"], b["water_out_c"], b["n_tubes"], b["passes"], b["length_m"], tube,
                                 condensing_htc_multiplier=1.4, condensing_temp_c=b["condensing_temp_c"], refrigerant=b["refrigerant"],
                                 fouling_m2kw=b.get("rating_fouling_water_m2kw", 0.000018),
                                 fouling_ref_m2kw=b.get("rating_fouling_ref_m2kw", 0.0))
            rows.append({
                "benchmark": b["name"], "status": r["status"],
                "calc_q_kw": r["q_possible_kw"], "target_q_kw": b["q_kw"], "q_error_pct": 100*(r["q_possible_kw"]-b["q_kw"])/b["q_kw"],
                "calc_shell_id_mm": r["shell_id_mm"], "target_shell_id_mm": b["target_shell_id_mm"], "shell_id_error_pct": 100*(r["shell_id_mm"]-b["target_shell_id_mm"])/b["target_shell_id_mm"],
                "calc_uo": r["uo_w_m2k"], "target_uo": b["target_uo_w_m2k"], "uo_error_pct": 100*(r["uo_w_m2k"]-b["target_uo_w_m2k"])/b["target_uo_w_m2k"],
                "calc_flow_m3h": r["water_flow_m3h"], "target_flow_m3h": b["target_water_flow_m3h"],
                # Implied LMTD needed for the target duty at the target Uo and calculated
                # envelope area. If this differs from the water-temperature LMTD, the
                # published targets are not mutually consistent (different area basis or
                # condensing temperature) and only the Uo comparison is meaningful.
                "implied_lmtd_for_targets_k": b["q_kw"]*1000.0/max(b["target_uo_w_m2k"]*r["area_m2"], 1e-9),
                "calc_lmtd_k": r["lmtd_k"],
            })
    return pd.DataFrame(rows)

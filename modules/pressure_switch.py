import math
import pandas as pd
from .thermo import sat_pressure_pa, barg_to_pa_abs, pressure_text

def calculate_pressure_switches(ref: str, evap_c: float, cond_c: float, subcool_k: float,
                                max_high_barg: float, hps_margin_k: float,
                                lps_cutout_evap_c: float, lps_cutin_evap_c: float,
                                cps1_on_cond_c: float, cps1_off_cond_c: float,
                                cps2_on_cond_c: float, cps2_off_cond_c: float,
                                hgb_open_evap_c: float | None = None,
                                hgb_close_evap_c: float | None = None,
                                unit: str = "bar(g)") -> tuple[pd.DataFrame, list[str], dict]:
    warnings = []
    vals = {}
    try:
        vals["normal_suction"] = sat_pressure_pa(ref, evap_c, 1.0)
        vals["normal_condensing"] = sat_pressure_pa(ref, cond_c, 1.0)
        vals["subcooled_liquid_ref"] = sat_pressure_pa(ref, cond_c - subcool_k, 0.0)
        vals["hps_by_temp"] = sat_pressure_pa(ref, cond_c + hps_margin_k, 1.0)
        vals["hps_limit"] = barg_to_pa_abs(max_high_barg)
        vals["hps_cutout"] = min(vals["hps_by_temp"], vals["hps_limit"])
        vals["lps_cutout"] = sat_pressure_pa(ref, lps_cutout_evap_c, 1.0)
        vals["lps_cutin"] = sat_pressure_pa(ref, lps_cutin_evap_c, 1.0)
        vals["cps1_on"] = sat_pressure_pa(ref, cps1_on_cond_c, 1.0)
        vals["cps1_off"] = sat_pressure_pa(ref, cps1_off_cond_c, 1.0)
        vals["cps2_on"] = sat_pressure_pa(ref, cps2_on_cond_c, 1.0)
        vals["cps2_off"] = sat_pressure_pa(ref, cps2_off_cond_c, 1.0)
        if hgb_open_evap_c is not None:
            vals["hgb_open"] = sat_pressure_pa(ref, hgb_open_evap_c, 1.0)
            vals["hgb_close"] = sat_pressure_pa(ref, hgb_close_evap_c or hgb_open_evap_c + 2, 1.0)
    except Exception as exc:
        return pd.DataFrame(), [f"Pressure calculation error: {exc}"], vals
    if lps_cutin_evap_c <= lps_cutout_evap_c:
        warnings.append("LPS cut-in should be higher than cut-out.")
    if cps1_off_cond_c >= cps1_on_cond_c:
        warnings.append("CPS1 OFF should be lower than CPS1 ON.")
    if cps2_off_cond_c >= cps2_on_cond_c:
        warnings.append("CPS2 OFF should be lower than CPS2 ON.")
    if cps2_on_cond_c <= cps1_on_cond_c:
        warnings.append("CPS2 ON should normally be above CPS1 ON.")
    if vals["hps_cutout"] < vals["hps_by_temp"]:
        warnings.append("HPS setting limited by max high-side pressure.")
    rows = [
        ["HPS", "High pressure safety", "Manual reset", "—", pressure_text(vals["hps_cutout"], unit), f"Tcond + margin = {cond_c+hps_margin_k:.1f} °C; capped by {max_high_barg:.1f} bar(g) max"],
        ["LPS", "Low pressure / pump-down", "Auto reset", pressure_text(vals["lps_cutin"], unit), pressure_text(vals["lps_cutout"], unit), f"Cut-in {lps_cutin_evap_c:.1f} °C evap.; cut-out {lps_cutout_evap_c:.1f} °C evap."],
        ["CPS1", "Condenser fan stage 1", "Auto", pressure_text(vals["cps1_off"], unit), pressure_text(vals["cps1_on"], unit), f"ON {cps1_on_cond_c:.1f} °C cond.; OFF {cps1_off_cond_c:.1f} °C cond."],
        ["CPS2", "Condenser fan stage 2", "Auto", pressure_text(vals["cps2_off"], unit), pressure_text(vals["cps2_on"], unit), f"ON {cps2_on_cond_c:.1f} °C cond.; OFF {cps2_off_cond_c:.1f} °C cond."],
    ]
    if "hgb_open" in vals:
        rows.append(["YV2/HGBP", "Hot gas bypass", "Auto", pressure_text(vals["hgb_close"], unit), pressure_text(vals["hgb_open"], unit), "Open before LPS trip under low load."])
    df = pd.DataFrame(rows, columns=["Device", "Function", "Reset", "Cut-in / OFF", "Cut-out / ON", "Basis"])
    return df, warnings, vals

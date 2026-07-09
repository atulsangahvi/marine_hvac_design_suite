from __future__ import annotations

import math
import pandas as pd


def minimum_oil_return_velocity(compressor_type: str, line_orientation: str, refrigerant: str = "", load_fraction: float = 1.0) -> float:
    """Return screening minimum suction-gas velocity for oil return.

    This is a preliminary HVAC/R design rule, not a substitute for a compressor
    manufacturer's piping manual. Vertical risers need much higher velocity than
    horizontal runs. Part-load operation is penalized because oil return is most
    difficult when mass flow is low.
    """
    ct = (compressor_type or "").lower()
    ori = (line_orientation or "horizontal").lower()
    ref = (refrigerant or "").upper()
    if "vertical" in ori or "riser" in ori:
        base = 7.5
        if "screw" in ct:
            base = 8.5
        elif "recip" in ct or "piston" in ct:
            base = 8.0
        elif "scroll" in ct:
            base = 7.0
    else:
        base = 4.0
        if "screw" in ct:
            base = 4.5
    if ref in {"R134A", "R1234ZE(E)", "R1234YF"}:
        base += 0.5
    if load_fraction < 0.50:
        base += 1.0
    elif load_fraction < 0.75:
        base += 0.5
    return round(base, 2)


def assess_oil_return(
    compressor_type: str,
    refrigerant: str,
    actual_suction_velocity_m_s: float,
    vertical_riser_m: float = 0.0,
    horizontal_run_m: float = 0.0,
    load_fraction: float = 1.0,
    oil_separator: bool = False,
    flooded_evaporator: bool = False,
) -> dict:
    orientation = "Vertical riser" if vertical_riser_m > 1.0 else "Horizontal/short riser"
    min_v = minimum_oil_return_velocity(compressor_type, orientation, refrigerant, load_fraction)
    margin = float(actual_suction_velocity_m_s) - min_v
    ok = margin >= 0.0
    risk_points = 0
    risk_notes = []
    if not ok:
        risk_points += 3
        risk_notes.append("Suction velocity is below the screening minimum for reliable oil return.")
    if vertical_riser_m > 3.0:
        risk_points += 1
        risk_notes.append("Vertical riser height is significant; oil traps and part-load riser sizing should be checked.")
    if load_fraction < 0.5:
        risk_points += 2
        risk_notes.append("Low-load operation reduces refrigerant mass flow and is usually the worst oil-return case.")
    if flooded_evaporator:
        risk_points += 2
        risk_notes.append("Flooded evaporators require dedicated oil management because oil can accumulate in the shell.")
    if oil_separator:
        risk_points = max(0, risk_points - 1)
        risk_notes.append("Oil separator reduces circulating oil but does not remove the need for correct suction-riser velocity.")

    risk = "LOW" if risk_points <= 1 and ok else "MEDIUM" if risk_points <= 3 else "HIGH"
    if ok:
        rec = "Oil return velocity appears acceptable for screening. Verify against compressor manufacturer piping manual, especially at minimum capacity."
    else:
        rec = "Oil return may be unreliable. Consider smaller suction riser, double riser for part load, oil separator, proper P-traps, or higher minimum compressor loading."
    return {
        "status": "PASS" if ok else "CHECK",
        "oil_return_ok": ok,
        "risk_level": risk,
        "compressor_type": compressor_type,
        "refrigerant": refrigerant,
        "orientation_basis": orientation,
        "minimum_suction_velocity_m_s": round(min_v, 2),
        "actual_suction_velocity_m_s": round(float(actual_suction_velocity_m_s), 2),
        "velocity_margin_m_s": round(margin, 2),
        "vertical_riser_m": round(float(vertical_riser_m), 2),
        "horizontal_run_m": round(float(horizontal_run_m), 2),
        "load_fraction": round(float(load_fraction), 2),
        "oil_separator": bool(oil_separator),
        "flooded_evaporator": bool(flooded_evaporator),
        "risk_notes": risk_notes or ["No major oil-return risk flagged by this screening check."],
        "recommendation": rec,
    }


def oil_management_table(result: dict) -> pd.DataFrame:
    rows = [
        ["Status", result.get("status")],
        ["Risk level", result.get("risk_level")],
        ["Actual suction velocity", f"{result.get('actual_suction_velocity_m_s',0):.2f} m/s"],
        ["Minimum required suction velocity", f"{result.get('minimum_suction_velocity_m_s',0):.2f} m/s"],
        ["Velocity margin", f"{result.get('velocity_margin_m_s',0):+.2f} m/s"],
        ["Basis", result.get("orientation_basis")],
        ["Load fraction checked", result.get("load_fraction")],
        ["Oil separator fitted", "Yes" if result.get("oil_separator") else "No"],
        ["Flooded evaporator oil risk", "Yes" if result.get("flooded_evaporator") else "No"],
        ["Recommendation", result.get("recommendation")],
    ]
    return pd.DataFrame(rows, columns=["Item", "Value"])


def oil_management_notes_table(result: dict) -> pd.DataFrame:
    return pd.DataFrame({"Oil management notes": result.get("risk_notes", [])})

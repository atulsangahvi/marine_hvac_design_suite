import math
import pandas as pd
from .thermo import c_to_k, sat_pressure_pa, pressure_text
try:
    from CoolProp.CoolProp import PropsSI
except Exception:
    PropsSI = None

COMPRESSOR_TYPES = ["Scroll", "Reciprocating", "Screw", "Digital scroll", "VFD screw/scroll"]

def discharge_temperature(ref: str, evap_c: float, cond_c: float, superheat_k: float,
                          subcool_k: float, mdot_kg_s: float, cooling_kw: float,
                          power_kw: float | None = None, cop: float | None = None,
                          route: str = "Power-based", eta_mech: float = 1.0,
                          eta_is: float | None = None) -> dict:
    if PropsSI is None:
        return {"error": "CoolProp is not installed"}
    try:
        p1 = sat_pressure_pa(ref, evap_c, 1.0)
        p2 = sat_pressure_pa(ref, cond_c, 0.0)
        t1 = c_to_k(evap_c + superheat_k)
        h1 = PropsSI("H", "P", p1, "T", t1, ref)
        s1 = PropsSI("S", "P", p1, "T", t1, ref)
        h_liq = PropsSI("H", "P", p2, "T", c_to_k(cond_c - subcool_k), ref)
        if power_kw is None:
            power_kw = cooling_kw / max(cop or 3.0, 0.01)
        if route.lower().startswith("condenser"):
            h2 = h_liq + (cooling_kw + power_kw) * 1000 / max(mdot_kg_s, 1e-9)
        else:
            h2 = h1 + eta_mech * power_kw * 1000 / max(mdot_kg_s, 1e-9)
        t2_c = PropsSI("T", "P", p2, "H", h2, ref) - 273.15
        t2_is_c = None
        if eta_is:
            h2s = PropsSI("H", "P", p2, "S", s1, ref)
            h2_eta = h1 + (h2s - h1) / max(eta_is, 1e-6)
            t2_is_c = PropsSI("T", "P", p2, "H", h2_eta, ref) - 273.15
        return {
            "p_suction_pa": p1, "p_discharge_pa": p2, "t_suction_c": evap_c + superheat_k,
            "t_discharge_c": t2_c, "t_discharge_is_c": t2_is_c,
            "h1_kjkg": h1/1000, "h2_kjkg": h2/1000, "h_liq_kjkg": h_liq/1000,
            "power_kw": power_kw, "heat_rejection_kw": cooling_kw + power_kw,
        }
    except Exception as exc:
        return {"error": str(exc)}

def estimate_operating_point(ref: str, evap_c: float, design_cond_c: float, water_in_c: float,
                             condenser_ua_kw_k: float, cooling_kw: float, cop: float,
                             compressor_type: str = "Scroll", max_cond_c: float = 65.0) -> dict:
    """Simple condenser/compressor match. Uses approximate capacity/power derating with condensing temperature.
    This is a screening model; replace with compressor-map interpolation when map data is available.
    """
    type_factor = {"Scroll": 0.018, "Reciprocating": 0.025, "Screw": 0.014, "Digital scroll": 0.018, "VFD screw/scroll": 0.010}.get(compressor_type, 0.018)
    base_power = cooling_kw / max(cop, 0.1)
    rows=[]
    best=None
    for tc in [design_cond_c + i*0.5 for i in range(0, int((max_cond_c-design_cond_c)/0.5)+1)]:
        lift = tc - design_cond_c
        qevap = cooling_kw * max(0.55, 1.0 - type_factor * lift)
        power = base_power * (1.0 + 0.025 * lift)
        qrej_comp = qevap + power
        # Condenser capacity using a more realistic water-side LMTD estimate.
        # If water flow is unknown, assume a 5 K condenser-water rise for screening.
        water_out_c = water_in_c + 5.0
        dt1 = max(tc - water_out_c, 0.05)
        dt2 = max(tc - water_in_c, 0.05)
        if abs(dt1 - dt2) < 1e-9:
            lmtd = dt1
        else:
            lmtd = (dt2 - dt1) / max(math.log(dt2 / dt1), 1e-9)
        qrej_hx = condenser_ua_kw_k * lmtd
        err = qrej_hx - qrej_comp
        rows.append({"Condensing °C":tc,"Compressor cooling kW":qevap,"Compressor power kW":power,"Required heat rejection kW":qrej_comp,"HX heat rejection kW":qrej_hx,"Balance kW":err})
        if err >= 0 and best is None:
            best = rows[-1]
    if best is None:
        best = rows[-1] if rows else {}
    status = "OK" if best and best.get("Balance kW", -1) >= 0 else "NOT BALANCED"
    return {"status": status, "operating_point": best, "table": pd.DataFrame(rows)}

def compressor_summary_table(result: dict, unit="bar(g)") -> pd.DataFrame:
    if result.get("error"):
        return pd.DataFrame([["Error", result["error"]]], columns=["Parameter","Value"])
    rows = [
        ["Suction pressure", pressure_text(result["p_suction_pa"], unit)],
        ["Discharge pressure", pressure_text(result["p_discharge_pa"], unit)],
        ["Suction temperature", f"{result['t_suction_c']:.2f} °C"],
        ["Discharge temperature", f"{result['t_discharge_c']:.2f} °C"],
        ["Compressor power", f"{result['power_kw']:.2f} kW"],
        ["Heat rejection", f"{result['heat_rejection_kw']:.2f} kW"],
    ]
    if result.get("t_discharge_is_c") is not None:
        rows.append(["Discharge temp by isentropic efficiency", f"{result['t_discharge_is_c']:.2f} °C"])
    return pd.DataFrame(rows, columns=["Parameter","Value"])

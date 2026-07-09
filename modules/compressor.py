import math
import pandas as pd
from .thermo import c_to_k, sat_pressure_pa, pressure_text
try:
    from CoolProp.CoolProp import PropsSI
except Exception:
    PropsSI = None

COMPRESSOR_TYPES = ["Scroll", "Reciprocating", "Screw", "Digital scroll", "VFD screw/scroll"]


def _eta_curves(compressor_type: str) -> dict:
    """Typical isentropic/volumetric efficiency behaviour vs pressure ratio.

    eta_is = a - b (PR - PR_opt)^2 approximates published polytropic-efficiency
    hills for each machine class; eta_v uses the classic clearance-volume model
    eta_v = 1 - c (PR^(1/n) - 1) (recip) or a gentler linear slope (scroll/screw,
    which have no re-expansion clearance in the same sense). These are screening
    curves; a manufacturer map (compressor_map.interpolate_idw) always wins.
    """
    t = (compressor_type or "").lower()
    if "recip" in t or "piston" in t:
        return {"a": 0.76, "b": 0.012, "pr_opt": 3.0, "vol_model": "clearance", "c": 0.05, "n": 1.12}
    if "screw" in t:
        return {"a": 0.74, "b": 0.008, "pr_opt": 3.6, "vol_model": "linear", "c": 0.010, "n": 1.0}
    # scroll / digital scroll / default
    return {"a": 0.72, "b": 0.010, "pr_opt": 2.6, "vol_model": "linear", "c": 0.015, "n": 1.0}


def cycle_operating_point(ref: str, evap_c: float, cond_c: float, superheat_k: float = 6.0,
                          subcool_k: float = 3.0, compressor_type: str = "Scroll",
                          swept_flow_m3_s: float | None = None,
                          rated_cooling_kw: float | None = None,
                          rated_evap_c: float | None = None, rated_cond_c: float | None = None,
                          eta_mech: float = 0.95) -> dict:
    """Physics-based single-stage vapor-compression operating point.

    v15: replaces linear %/K derating. Capacity scales with suction density x
    volumetric efficiency x refrigeration effect from real refrigerant properties;
    power comes from the isentropic enthalpy rise divided by an eta_is(PR) curve.
    The swept volume flow is either given, or inferred from a rated point
    (rated_cooling_kw at rated_evap_c/rated_cond_c).
    """
    if PropsSI is None:
        raise RuntimeError("CoolProp is required for compressor cycle calculations. Install CoolProp and rerun this module.")
    cur = _eta_curves(compressor_type)

    def _state(te, tc):
        p1 = sat_pressure_pa(ref, te, 1.0)
        p2 = sat_pressure_pa(ref, tc, 0.0)
        t1 = c_to_k(te + superheat_k)
        h1 = PropsSI("H", "P", p1, "T", t1, ref)
        rho1 = PropsSI("D", "P", p1, "T", t1, ref)
        s1 = PropsSI("S", "P", p1, "T", t1, ref)
        h2s = PropsSI("H", "P", p2, "S", s1, ref)
        h4 = PropsSI("H", "P", p2, "T", c_to_k(tc - subcool_k), ref)  # h3=h4 across TXV
        pr = p2 / p1
        eta_is = max(0.45, cur["a"] - cur["b"] * (pr - cur["pr_opt"]) ** 2)
        if cur["vol_model"] == "clearance":
            eta_v = max(0.35, 1.0 - cur["c"] * (pr ** (1.0 / cur["n"]) - 1.0))
        else:
            eta_v = max(0.45, 1.0 - cur["c"] * pr)
        return {"p1": p1, "p2": p2, "h1": h1, "h2s": h2s, "h4": h4, "rho1": rho1,
                "pr": pr, "eta_is": eta_is, "eta_v": eta_v}

    st = _state(evap_c, cond_c)
    vs = swept_flow_m3_s
    if vs is None:
        if rated_cooling_kw is None:
            return {"error": "Provide swept_flow_m3_s or a rated point (rated_cooling_kw + rated conditions)"}
        r = _state(rated_evap_c if rated_evap_c is not None else evap_c,
                   rated_cond_c if rated_cond_c is not None else cond_c)
        mdot_rated = rated_cooling_kw * 1000.0 / max(r["h1"] - r["h4"], 1.0)
        vs = mdot_rated / max(r["rho1"] * r["eta_v"], 1e-9)

    mdot = st["rho1"] * st["eta_v"] * vs
    q_kw = mdot * (st["h1"] - st["h4"]) / 1000.0
    w_kw = mdot * (st["h2s"] - st["h1"]) / max(st["eta_is"], 1e-6) / max(eta_mech, 1e-6) / 1000.0
    h2 = st["h1"] + (st["h2s"] - st["h1"]) / max(st["eta_is"], 1e-6)
    try:
        t2_c = PropsSI("T", "P", st["p2"], "H", h2, ref) - 273.15
    except Exception:
        t2_c = float("nan")
    return {
        "cooling_kw": q_kw, "power_kw": w_kw, "heat_rejection_kw": q_kw + w_kw,
        "cop": q_kw / max(w_kw, 1e-9), "mass_flow_kg_s": mdot,
        "pressure_ratio": st["pr"], "eta_is": st["eta_is"], "eta_vol": st["eta_v"],
        "swept_flow_m3_s": vs, "discharge_temp_c": t2_c,
        "suction_density_kg_m3": st["rho1"],
    }

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
    """Condenser/compressor balance point.

    v15: compressor behaviour along the condensing-temperature sweep now comes
    from the thermodynamic cycle model (real suction density, eta_v(PR),
    eta_is(PR)) calibrated to the entered design point, instead of fixed %/K
    linear derating factors. Falls back to the old linear screening only if
    CoolProp is unavailable.
    """
    base_power = cooling_kw / max(cop, 0.1)
    use_cycle = PropsSI is not None
    type_factor = {"Scroll": 0.018, "Reciprocating": 0.025, "Screw": 0.014, "Digital scroll": 0.018, "VFD screw/scroll": 0.010}.get(compressor_type, 0.018)
    rows=[]
    best=None
    # Calibrate swept volume once at the design point.
    vs = None
    if use_cycle:
        cal = cycle_operating_point(ref, evap_c, design_cond_c, compressor_type=compressor_type,
                                    rated_cooling_kw=cooling_kw, rated_evap_c=evap_c, rated_cond_c=design_cond_c)
        if not cal.get("error"):
            vs = cal["swept_flow_m3_s"]
        else:
            use_cycle = False
    for tc in [design_cond_c + i*0.5 for i in range(0, int((max_cond_c-design_cond_c)/0.5)+1)]:
        lift = tc - design_cond_c
        if use_cycle:
            op = cycle_operating_point(ref, evap_c, tc, compressor_type=compressor_type, swept_flow_m3_s=vs)
            if op.get("error"):
                use_cycle = False
        if use_cycle:
            qevap = op["cooling_kw"]
            power = op["power_kw"]
        else:
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

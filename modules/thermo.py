import math
from dataclasses import dataclass
try:
    from CoolProp.CoolProp import PropsSI
except Exception:
    PropsSI = None

ATM_BAR = 1.01325
BAR_PER_PA = 1e-5
PSI_PER_PA = 0.0001450377377
REFS = ["R134a","R407C","R410A","R404A","R507A","R22","R1234yf","R1234ze(E)","R513A","R32","R290","R600a"]

def c_to_k(c: float) -> float:
    return c + 273.15

def sat_pressure_pa(ref: str, temp_c: float, quality: float = 1.0) -> float:
    if PropsSI is None:
        # Approximate saturation-pressure fallback for offline tests or hosts where
        # CoolProp wheels are unavailable. Anchored at 5 °C and 45 °C for common
        # HVAC refrigerants, with log-linear interpolation/extrapolation.
        anchors_bar_abs = {
            "R134a": (3.5, 11.6), "R407C": (5.5, 17.7), "R410A": (9.4, 27.3),
            "R404A": (6.2, 20.5), "R507A": (6.5, 21.1), "R22": (5.8, 17.3),
            "R32": (9.5, 28.0), "R1234yf": (3.6, 11.8), "R1234ze(E)": (2.8, 9.1),
            "R513A": (3.8, 12.3), "R290": (5.5, 15.3), "R600a": (1.6, 5.8),
        }
        p5, p45 = anchors_bar_abs.get(str(ref), (5.0, 16.0))
        import math as _math
        k = _math.log(p45 / p5) / 40.0
        return p5 * _math.exp(k * (float(temp_c) - 5.0)) * 1e5
    return float(PropsSI("P", "T", c_to_k(temp_c), "Q", quality, ref))

def pa_to_barg(pa: float) -> float:
    return pa * BAR_PER_PA - ATM_BAR

def pa_to_barabs(pa: float) -> float:
    return pa * BAR_PER_PA

def pa_to_psig(pa: float) -> float:
    return pa * PSI_PER_PA - 14.6959

def barg_to_pa_abs(barg: float) -> float:
    return (barg + ATM_BAR) / BAR_PER_PA

def pressure_text(pa: float, unit: str = "bar(g)") -> str:
    if pa is None or (isinstance(pa, float) and math.isnan(pa)):
        return "—"
    if unit == "bar(abs)":
        return f"{pa_to_barabs(pa):.2f} bar(abs)"
    if unit == "psig":
        return f"{pa_to_psig(pa):.0f} psig"
    return f"{pa_to_barg(pa):.2f} bar(g)"

def compressor_discharge_temperature(ref: str, tevap_c: float, tcond_c: float, subcool_k: float,
                                     sh_evap_k: float, sh_line_k: float, mdot_kg_s: float,
                                     qcool_kw: float, power_kw: float, eta_mech: float = 1.0,
                                     route: str = "power") -> dict:
    if PropsSI is None:
        return {"error": "CoolProp is not installed"}
    if mdot_kg_s <= 0:
        return {"error": "Mass flow must be > 0"}
    try:
        p1 = sat_pressure_pa(ref, tevap_c, 1.0)
        p2 = sat_pressure_pa(ref, tcond_c, 0.0)
        t1k = c_to_k(tevap_c + sh_evap_k + sh_line_k)
        h1 = PropsSI("H", "P", p1, "T", t1k, ref)
        s1 = PropsSI("S", "P", p1, "T", t1k, ref)
        h_liq = PropsSI("H", "P", p2, "T", c_to_k(tcond_c - subcool_k), ref)
        if route == "condenser_balance":
            h2 = h_liq + ((qcool_kw + power_kw) * 1000.0) / mdot_kg_s
        else:
            h2 = h1 + (eta_mech * power_kw * 1000.0) / mdot_kg_s
        t2c = PropsSI("T", "P", p2, "H", h2, ref) - 273.15
        try:
            h2s = PropsSI("H", "P", p2, "S", s1, ref)
            eta_is = (h2s - h1) / max(h2 - h1, 1e-9)
        except Exception:
            eta_is = float("nan")
        return {"p1_pa": p1, "p2_pa": p2, "t1_c": t1k-273.15, "t2_c": t2c,
                "h1_kjkg": h1/1000, "h2_kjkg": h2/1000, "h_liq_kjkg": h_liq/1000,
                "eta_is_implied": eta_is, "route": route}
    except Exception as exc:
        return {"error": str(exc)}

def water_flow_m3h(q_kw: float, dt_k: float, cp_kj_kgk: float = 4.186, rho_kg_m3: float = 1000.0) -> float:
    if dt_k <= 0 or cp_kj_kgk <= 0 or rho_kg_m3 <= 0:
        return 0.0
    return (q_kw / (cp_kj_kgk * dt_k)) * 3600.0 / rho_kg_m3

def pipe_velocity_m_s(flow_m3h: float, id_mm: float) -> float:
    if flow_m3h <= 0 or id_mm <= 0:
        return 0.0
    area = math.pi * (id_mm/1000)**2 / 4
    return flow_m3h / 3600 / area

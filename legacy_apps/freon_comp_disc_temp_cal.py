
import math
import streamlit as st
from CoolProp.CoolProp import PropsSI

st.set_page_config(page_title="Compressor Discharge Temperature (T2)", layout="wide")
st.title("Compressor Discharge Temperature (T2) — CoolProp")

with st.sidebar:
    st.header("Refrigerant & Operating Temps")
    fluid = st.selectbox("Refrigerant", [
        "R22","R134a","R404A","R407C","R410A","R32","R1234yf","R1234ze(E)","R290","R600a"
    ], index=4)
    TevapC   = st.number_input("Evaporating Temp (°C)", value=5.0, format="%.2f")
    TcondC   = st.number_input("Condensing Temp (°C)", value=45.0, format="%.2f")
    DTsubC   = st.number_input("Condenser Subcooling ΔT (°C)", value=5.0, min_value=0.0, format="%.2f")

    st.header("Suction Superheat (to compressor inlet)")
    SH_evapC  = st.number_input("Evap outlet superheat (°C)", value=5.0, min_value=0.0, format="%.2f")
    SH_lineC  = st.number_input("Additional suction-line superheat (°C)", value=0.0, min_value=0.0, format="%.2f")

    st.header("Mass Flow & Capacity")
    mdot = st.number_input("Mass flow rate (kg/s)", value=0.10, min_value=0.0001, format="%.4f")
    Qcool_kW = st.number_input("Cooling capacity Q_cool (kW)", value=20.0, min_value=0.0, format="%.2f")

    st.header("Power source")
    psrc = st.radio("How do you want to provide power?", ["Electrical power (kW)", "COP (Q_cool / W_elec)"], index=1, horizontal=True)
    if psrc == "Electrical power (kW)":
        Welec_kW = st.number_input("Electrical power to compressor (kW)", value=6.0, min_value=0.0, format="%.2f")
    else:
        COP = st.number_input("Compressor COP (= Q_cool / W_elec)", value=3.3, min_value=0.01, format="%.3f")
        Welec_kW = Qcool_kW / COP

    eta_mech = st.number_input("Motor+drive efficiency (fraction, optional)", value=1.00, min_value=0.50, max_value=1.00, step=0.01, format="%.2f")

    st.header("Route selection")
    route = st.radio("Choose calculation route", ["Route A — Power-based", "Route B — Condenser balance"], index=0)

    st.header("Optional: isentropic efficiency")
    use_eta_is = st.checkbox("Provide isentropic efficiency to predict T2 (comparison)")
    if use_eta_is:
        eta_is = st.number_input("Isentropic efficiency (fraction)", value=0.70, min_value=0.1, max_value=1.0, step=0.01, format="%.2f")
    else:
        eta_is = None

# --- Derived pressures & inlet state ---
try:
    P1 = PropsSI("P", "T", TevapC + 273.15, "Q", 1, fluid)  # Pa at evap temp (sat vap)
    P2 = PropsSI("P", "T", TcondC + 273.15, "Q", 0, fluid)  # Pa at cond temp (sat liq)

    T1K = TevapC + SH_evapC + SH_lineC + 273.15
    h1  = PropsSI("H", "P", P1, "T", T1K, fluid)            # J/kg
    s1  = PropsSI("S", "P", P1, "T", T1K, fluid)            # J/kg-K

    # Subcooled liquid enthalpy at condenser outlet
    T3K = (TcondC - DTsubC) + 273.15
    hL  = PropsSI("H", "P", P2, "T", T3K, fluid)            # J/kg
except Exception as e:
    st.error(f"CoolProp error while building states: {e}")
    st.stop()

# Power: electrical vs shaft-equivalent
W_elec_W = Welec_kW * 1000.0
W_comp_W = eta_mech * W_elec_W  # refrigerant-side work approximation

# --- Routes ---
h2_from_route = None
route_label = ""

try:
    if route.startswith("Route A"):
        # h2 = h1 + W_comp/mdot (work-based)
        h2_from_route = h1 + W_comp_W / mdot
        route_label = "Route A (power-based)"
    else:
        # Route B: condenser energy balance: Q_rej = Q_cool + W_elec
        Qrej_W = (Qcool_kW * 1000.0) + W_elec_W
        h2_from_route = hL + Qrej_W / mdot
        route_label = "Route B (condenser balance)"
except ZeroDivisionError:
    st.error("Mass flow rate must be > 0.")
    st.stop()

# Convert to discharge temperature
try:
    T2K = PropsSI("T", "P", P2, "H", h2_from_route, fluid)
    T2C = T2K - 273.15
except Exception as e:
    st.error(f"CoolProp error converting (P2, h2) → T2: {e}")
    st.stop()

# Optional: isentropic prediction (comparison)
T2C_is = None
if eta_is is not None:
    try:
        h2s = PropsSI("H", "P", P2, "S", s1, fluid)           # isentropic outlet enthalpy
        h2_eta = h1 + (h2s - h1)/eta_is                       # using compressor isentropic efficiency
        T2C_is = PropsSI("T", "P", P2, "H", h2_eta, fluid) - 273.15
    except Exception as e:
        st.warning(f"Isentropic path failed: {e}")
        T2C_is = None

# Display
st.subheader("Results")
c1, c2, c3 = st.columns(3)
c1.metric("Suction temperature T1 (°C)", f"{T1K-273.15:.2f}")
c2.metric("Discharge temperature T2 (°C)", f"{T2C:.2f}", route_label)
c3.metric("Discharge pressure (bar)", f"{P2/1e5:.2f}")

c4, c5, c6 = st.columns(3)
c4.metric("h1 (kJ/kg)", f"{h1/1000.0:.2f}")
c5.metric("h2 (kJ/kg)", f"{h2_from_route/1000.0:.2f}")
c6.metric("hL (kJ/kg)", f"{hL/1000.0:.2f}")

if T2C_is is not None:
    st.info(f"Isentropic model (η_is={eta_is:.2f}) → T2 ≈ {T2C_is:.2f} °C")

st.caption("Route A uses compressor work (electrical × efficiency). Route B uses condenser energy balance (Q_cool + W_elec). Subcooling sets the liquid enthalpy hL.")

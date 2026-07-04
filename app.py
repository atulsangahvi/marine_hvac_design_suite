import streamlit as st
import pandas as pd

from modules.thermo import REFS, pressure_text
from modules.compressor import discharge_temperature, compressor_summary_table, estimate_operating_point, COMPRESSOR_TYPES
from modules.pressure_switch import calculate_pressure_switches
from modules.condenser import evaluate_condenser, auto_select_tubes
from modules.evaporator import shell_tube_evaporator_screening, air_cooled_dx_coil_screening, evaporator_table, correlation_audit_table, recommended_improvement_table
from modules.piping import water_piping_summary, refrigerant_line_check
from modules.electrical import electrical_schedule
from modules.controls import plc_logic_table
from modules.valves import expansion_valve_screening, solenoid_filter_drier_screening
from modules.vessels import receiver_sizing, suction_accumulator_guidance, vessels_table
from modules.safety import safety_checks
from modules.bom import base_bom
from modules.drawings import refrigerant_mermaid, control_mermaid
from modules.reports import make_excel_report, make_pdf_report
from data.tube_library import filter_tubes, WIELAND_GEWA_C, tube_dataframe
from data.materials import MATERIALS
from data.compressor_library import compressor_library_df
from modules.compressor_map import interpolate_idw, derate_without_map
from modules.refrigerant_piping import select_line_size, oil_return_guidance, equivalent_length
from modules.water_system import water_system_table
from modules.marine_compliance import marine_compliance_checks
from modules.costing_weight import weight_cost_summary, cost_table
from modules.quality_docs import manufacturing_document_register, commissioning_checklist
from modules.heat_exchanger_datasheet import tema_datasheet
from modules.controller_io import controller_io_list, alarm_matrix, eev_control_sequence
from modules.operating_envelope import operating_envelope_checks, predicted_condenser_shortfall_action
from modules.service_docs import maintenance_schedule, factory_acceptance_tests
from modules.manufacturing_package import make_csv_zip
from modules.design_optimizer import condenser_geometry_optimizer
from modules.validation_benchmarks import run_benchmarks

APP_VERSION = "marine-chiller-suite-v8-milestone-1-2-core-db"

st.set_page_config(page_title="Marine Chiller Design Suite", layout="wide")

def check_password():
    try:
        expected = st.secrets.get("APP_PASSWORD", "")
    except Exception:
        expected = ""
    if not expected:
        st.warning("APP_PASSWORD not found in Streamlit secrets. Running without password for local engineering development.")
        return True
    if st.session_state.get("password_ok"):
        return True
    st.title("Marine Chiller Design Suite")
    pwd = st.text_input("Password", type="password")
    if st.button("Login"):
        if pwd == expected:
            st.session_state.password_ok = True
            st.rerun()
        else:
            st.error("Incorrect password")
    return False

if not check_password():
    st.stop()

st.title("Marine Chiller Design Suite")
st.caption(f"Version: {APP_VERSION}. Modular preliminary engineering tool for compressor, condenser, evaporator, controls, pressure switches, BOM and reports.")

with st.sidebar:
    st.header("Global inputs")
    project_name = st.text_input("Project name", "Marine Package Chiller")
    ref = st.selectbox("Refrigerant", REFS, index=REFS.index("R407C") if "R407C" in REFS else 0)
    compressor_type = st.selectbox("Compressor type", COMPRESSOR_TYPES)
    cooling_kw = st.number_input("Cooling capacity (kW)", 1.0, 5000.0, 42.2, step=1.0)
    cop = st.number_input("Compressor COP at design", 0.5, 10.0, 3.3, step=0.1)
    evap_c = st.number_input("Evaporating temperature (°C)", -40.0, 20.0, 5.0, step=0.5)
    cond_c = st.number_input("Condensing temperature (°C)", 20.0, 80.0, 45.0, step=0.5)
    superheat_k = st.number_input("Compressor inlet superheat (K)", 0.0, 40.0, 8.0, step=0.5)
    subcool_k = st.number_input("Condenser subcooling (K)", 0.0, 20.0, 5.0, step=0.5)
    water_type = st.radio("Condenser water", ["plain water", "seawater"], index=1)
    cw_in = st.number_input("Condenser water in (°C)", 0.0, 50.0, 35.0, step=0.5)
    cw_out = st.number_input("Condenser water out (°C)", 1.0, 60.0, 40.0, step=0.5)
    pressure_unit = st.radio("Pressure unit", ["bar(g)", "bar(abs)", "psig"], horizontal=True)

power_kw = cooling_kw / max(cop, 0.01)
heat_rejection_kw = cooling_kw + power_kw

# shared defaults
if "selected_tube" not in st.session_state:
    st.session_state.selected_tube = None

tabs = st.tabs([
    "1 Compressor", "2 Condenser", "3 Evaporator", "4 Pressure Switches", "5 Piping + Valves",
    "6 Electrical + Controls", "7 Controller I/O + Alarms", "8 Safety + BOM", "9 Drawings", "10 Reports", "11 Compliance + QA", "12 Datasheets + Cost", "13 Service + FAT"
])

with tabs[0]:
    st.header("Compressor operating point and discharge temperature")
    c1, c2, c3 = st.columns(3)
    with c1:
        mdot = st.number_input("Refrigerant mass flow (kg/s)", 0.001, 20.0, max(cooling_kw/160.0, 0.05), step=0.01, format="%.4f")
        route = st.radio("Discharge temperature route", ["Power-based", "Condenser balance"], horizontal=True)
    with c2:
        power_source = st.radio("Power input source", ["Use COP", "Enter compressor power"], horizontal=True)
        pkw = power_kw if power_source == "Use COP" else st.number_input("Compressor power (kW)", 0.0, 2000.0, power_kw, step=0.5)
        eta_mech = st.number_input("Motor/drive efficiency", 0.5, 1.0, 1.0, step=0.01)
    with c3:
        use_eta_is = st.checkbox("Also calculate by isentropic efficiency")
        eta_is = st.number_input("Isentropic efficiency", 0.1, 1.0, 0.70, step=0.01) if use_eta_is else None
        max_discharge_temp = st.number_input("Max allowed discharge temp (°C)", 60.0, 160.0, 115.0, step=1.0)
    comp_res = discharge_temperature(ref, evap_c, cond_c, superheat_k, subcool_k, mdot, cooling_kw, power_kw=pkw, cop=cop, route=route, eta_mech=eta_mech, eta_is=eta_is)
    st.dataframe(compressor_summary_table(comp_res, pressure_unit), hide_index=True, use_container_width=True)
    if not comp_res.get("error"):
        if comp_res["t_discharge_c"] > max_discharge_temp:
            st.error("Discharge temperature is above the entered limit. Consider lower condensing temperature, more suction cooling, liquid injection if allowed, or a different compressor operating point.")
        else:
            st.success("Discharge temperature is within the entered limit.")

    with st.expander("Milestone 2 compressor library schema"):
        st.dataframe(compressor_library_df(), hide_index=True, use_container_width=True)
        st.caption("These are starter records showing the database structure. Real manufacturer map points should be entered/validated before production selection.")

    st.subheader("Condenser/compressor operating point estimate")
    ua_kw_k = st.number_input("Estimated condenser UA (kW/K) for operating-point match", 0.1, 1000.0, 6.0, step=0.5)
    op = estimate_operating_point(ref, evap_c, cond_c, cw_in, ua_kw_k, cooling_kw, cop, compressor_type, max_cond_c=70.0)
    st.write(f"Status: **{op['status']}**")
    st.dataframe(op["table"], hide_index=True, use_container_width=True)

with tabs[1]:
    st.header("Shell-and-tube condenser module")
    mode = st.radio("Tube selection mode", ["Manual tube selection", "Auto-select from tube library"], horizontal=True)
    c1,c2,c3,c4 = st.columns(4)
    with c1:
        n_tubes = st.number_input("Number of tubes", 4, 2000, 64, step=4)
        tube_passes = st.number_input("Tube passes", 1, 12, 2, step=1)
    with c2:
        tube_length_m = st.number_input("Tube effective length (m)", 0.2, 10.0, 1.2, step=0.1)
        od_filter = st.selectbox("Tube OD filter", ["All", "5/8\"", "3/4\"", "1\""])
    with c3:
        pitch_ratio = st.number_input("TEMA tube pitch ratio", 1.1, 2.0, 1.25, step=0.05)
        shell_thk = st.number_input("Estimated shell thickness (mm)", 3.0, 30.0, 6.0, step=0.5)
    with c4:
        mult = st.number_input("Shell-side enhanced condensation multiplier", 1.0, 5.0, 2.5, step=0.1)

    tubes = filter_tubes(water_type, od_filter)
    if not tubes:
        st.error("No tubes found for selected water type and OD filter.")
        cond_res = {}
    elif mode == "Manual tube selection":
        tube_names = [t["name"] for t in tubes]
        tname = st.selectbox("Tube from library", tube_names)
        tube = next(t for t in tubes if t["name"] == tname)
        cond_res = evaluate_condenser(heat_rejection_kw, water_type, cw_in, cw_out, n_tubes, tube_passes, tube_length_m, tube, mult, pitch_ratio, shell_thk, condensing_temp_c=cond_c)
        st.session_state.selected_tube = tube
        st.dataframe(pd.DataFrame([[k,v] for k,v in cond_res.items() if k != "tube"], columns=["Parameter","Value"]), hide_index=True, use_container_width=True)
    else:
        df_auto = auto_select_tubes(heat_rejection_kw, water_type, cw_in, cw_out, n_tubes, tube_passes, tube_length_m, od_filter=od_filter, condensing_htc_multiplier=mult, pitch_ratio=pitch_ratio, shell_thk_mm=shell_thk, condensing_temp_c=cond_c)
        st.dataframe(df_auto, hide_index=True, use_container_width=True)
        if not df_auto.empty:
            best_name = df_auto.iloc[0]["tube"]
            tube = next(t for t in tubes if t["name"] == best_name)
            cond_res = evaluate_condenser(heat_rejection_kw, water_type, cw_in, cw_out, n_tubes, tube_passes, tube_length_m, tube, mult, pitch_ratio, shell_thk, condensing_temp_c=cond_c)
            st.session_state.selected_tube = tube
            st.success(f"Rank 1 selected for downstream report: {best_name}")
        else:
            cond_res = {}
    if cond_res:
        m1,m2,m3,m4 = st.columns(4)
        m1.metric("Required heat rejection", f"{heat_rejection_kw:.1f} kW")
        m2.metric("Possible heat rejection", f"{cond_res.get('q_possible_kw',0):.1f} kW")
        m3.metric("Shell OD", f"{cond_res.get('shell_od_mm',0):.0f} mm")
        m4.metric("Dry weight", f"{cond_res.get('dry_weight_kg',0):.0f} kg")
        if cond_res.get("status") == "OK":
            st.success(cond_res.get("guidance", "Condenser screening OK."))
        else:
            st.warning(cond_res.get("guidance", "Condenser needs review."))

    with st.expander("Milestone 1 automatic condenser optimizer"):
        max_sod = st.number_input("Optimizer max shell OD (mm)", 100.0, 1500.0, 350.0, step=10.0)
        max_len = st.number_input("Optimizer max tube length (m)", 0.5, 10.0, 2.0, step=0.1)
        max_dp = st.number_input("Optimizer max tube-side water ΔP (kPa)", 5.0, 300.0, 60.0, step=5.0)
        if st.button("Run condenser optimizer"):
            opt_df = condenser_geometry_optimizer(heat_rejection_kw, water_type, cw_in, cw_out, cond_c, max_sod, max_len, max_dp, od_filter, refrigerant=ref)
            st.dataframe(opt_df.head(50), hide_index=True, use_container_width=True)
            if not opt_df.empty:
                best = opt_df.iloc[0]
                st.success(f"Best option: {best['tube']} | {best['n_tubes']} tubes x {best['passes']} passes x {best['length_m']} m | shell OD {best['shell_od_mm']:.0f} mm")

    with st.expander("Milestone 2 tube/material database"):
        st.dataframe(tube_dataframe(water_type, 'condenser'), hide_index=True, use_container_width=True)
        st.dataframe(pd.DataFrame([{**{'material': k}, **v} for k,v in MATERIALS.items()]), hide_index=True, use_container_width=True)

    with st.expander("Validation benchmark: HSTAR/Wieland GEWA-CLF condenser"):
        st.dataframe(run_benchmarks(), hide_index=True, use_container_width=True)

with tabs[2]:
    st.header("Evaporator module")
    evap_mode = st.radio("Evaporator type", ["Shell-and-tube water/glycol", "Air-cooled DX coil"], horizontal=True)
    if evap_mode.startswith("Shell"):
        e1,e2,e3,e4 = st.columns(4)
        with e1:
            chw_in = st.number_input("CHW/glycol entering cooler (°C)", -20.0, 30.0, 12.0, step=0.5)
            chw_out = st.number_input("CHW/glycol leaving cooler (°C)", -25.0, 25.0, 7.0, step=0.5)
        with e2:
            glycol = st.number_input("Glycol %", 0.0, 60.0, 0.0, step=1.0)
            evap_tube_count = st.number_input("Evaporator tube count", 4, 2000, 80, step=4)
        with e3:
            evap_tube_len = st.number_input("Evaporator tube length (m)", 0.2, 10.0, 1.2, step=0.1)
            evap_passes = st.number_input("Evaporator passes", 1, 12, 2, step=1)
        with e4:
            evap_u = st.number_input("Override evaporator U (W/m²K, 0 = calculate)", 0.0, 5000.0, 0.0, step=50.0)
            ref_in_tubes = st.checkbox("DX mode: refrigerant in tubes", value=True, help="Recommended for DX shell-and-tube evaporator. Uncheck only for flooded/shell-side refrigerant screening.")
        with st.expander("Advanced shell-and-tube evaporator geometry"):
            ev_shell_id = st.number_input("Evaporator shell ID override (mm, 0 = estimate)", 0.0, 2000.0, 0.0, step=5.0)
            ev_baffle_spacing = st.number_input("Evaporator baffle spacing override (mm, 0 = estimate)", 0.0, 1000.0, 0.0, step=5.0)
            ev_baffle_cut = st.number_input("Evaporator baffle cut (%)", 15.0, 45.0, 25.0, step=1.0)
            ev_pitch_ratio = st.number_input("Evaporator tube pitch ratio", 1.10, 2.00, 1.25, step=0.05)
            ev_ref_mdot = st.number_input("Refrigerant mass flow for evaporator (kg/s, 0 = estimate)", 0.0, 20.0, 0.0, step=0.01, format="%.4f")
        evap_res = shell_tube_evaporator_screening(
            cooling_kw, chw_in, chw_out, "Water/Glycol", glycol, evap_c, 15.88, evap_tube_len,
            evap_tube_count, evap_passes, evap_u, refrigerant_in_tubes=ref_in_tubes,
            refrigerant=ref, shell_id_mm=(ev_shell_id or None), baffle_spacing_mm=(ev_baffle_spacing or None),
            baffle_cut_pct=ev_baffle_cut, pitch_ratio=ev_pitch_ratio,
            refrigerant_mass_flow_kg_s=(ev_ref_mdot or None)
        )
    else:
        a1,a2,a3,a4 = st.columns(4)
        with a1:
            air_flow = st.number_input("Air flow (m³/s)", 0.1, 200.0, 4.0, step=0.1)
            db = st.number_input("Entering DB (°C)", 0.0, 60.0, 27.0, step=0.5)
        with a2:
            wb = st.number_input("Entering WB (°C)", 0.0, 40.0, 19.0, step=0.5)
            rows = st.number_input("Coil rows", 1, 12, 4, step=1)
        with a3:
            face_area = st.number_input("Coil face area (m²)", 0.1, 100.0, 2.0, step=0.1)
            fpi = st.number_input("FPI", 4.0, 24.0, 12.0, step=1.0)
        with a4:
            tube_type = st.selectbox("Tube type", ["Smooth", "Microfin", "Microchannel/flat"], index=0)
        evap_res = air_cooled_dx_coil_screening(cooling_kw, air_flow, db, wb, evap_c, rows, face_area, fpi, tube_type=tube_type)
    st.dataframe(evaporator_table(evap_res), hide_index=True, use_container_width=True)
    with st.expander("Correlation audit for evaporator modules"):
        st.dataframe(correlation_audit_table(), hide_index=True, use_container_width=True)
        st.dataframe(recommended_improvement_table(), hide_index=True, use_container_width=True)

with tabs[3]:
    st.header("Pressure switch settings module")
    p1,p2,p3,p4 = st.columns(4)
    with p1:
        max_hp = st.number_input("Max high side pressure bar(g)", 5.0, 80.0, 30.0, step=0.5)
        hps_margin = st.number_input("HPS margin above condensing temp (K)", 1.0, 30.0, 10.0, step=0.5)
    with p2:
        lps_out = st.number_input("LPS cut-out evap equivalent (°C)", -50.0, 20.0, -2.0, step=0.5)
        lps_in = st.number_input("LPS cut-in evap equivalent (°C)", -40.0, 25.0, 4.0, step=0.5)
    with p3:
        cps1_on = st.number_input("CPS1 ON condensing equivalent (°C)", 20.0, 80.0, 42.0, step=0.5)
        cps1_off = st.number_input("CPS1 OFF condensing equivalent (°C)", 15.0, 75.0, 36.0, step=0.5)
    with p4:
        cps2_on = st.number_input("CPS2 ON condensing equivalent (°C)", 20.0, 85.0, 48.0, step=0.5)
        cps2_off = st.number_input("CPS2 OFF condensing equivalent (°C)", 15.0, 80.0, 42.0, step=0.5)
    ps_df, ps_warn, ps_vals = calculate_pressure_switches(ref, evap_c, cond_c, subcool_k, max_hp, hps_margin, lps_out, lps_in, cps1_on, cps1_off, cps2_on, cps2_off, unit=pressure_unit)
    for w in ps_warn:
        st.warning(w)
    st.dataframe(ps_df, hide_index=True, use_container_width=True)

with tabs[4]:
    st.header("Piping, EEV/TXV, solenoid and refrigerant accessories")
    p1,p2,p3 = st.columns(3)
    with p1:
        pipe_id = st.number_input("CHW pipe ID (mm)", 10.0, 1000.0, 65.0, step=5.0)
        glycol_pct = st.number_input("CHW glycol % for piping", 0.0, 60.0, 0.0, step=1.0)
    with p2:
        suction_v = st.number_input("Suction gas velocity (m/s)", 0.0, 50.0, 8.0, step=0.5)
        discharge_v = st.number_input("Discharge gas velocity (m/s)", 0.0, 60.0, 10.0, step=0.5)
    with p3:
        liquid_v = st.number_input("Liquid velocity (m/s)", 0.0, 5.0, 0.8, step=0.1)
        liquid_line_mm = st.number_input("Liquid line size (mm)", 4.0, 80.0, 16.0, step=1.0)
    wp = water_piping_summary(cooling_kw, 12.0, 7.0, pipe_id, glycol_pct=glycol_pct)
    st.subheader("Water piping")
    st.dataframe(pd.DataFrame([[k,v] for k,v in wp.items()], columns=["Parameter","Value"]), hide_index=True, use_container_width=True)
    st.subheader("Refrigerant line checks")
    st.dataframe(refrigerant_line_check(suction_v, discharge_v, liquid_v), hide_index=True, use_container_width=True)
    st.subheader("Expansion valve and liquid line components")
    exp = expansion_valve_screening(cooling_kw, ref, evap_c, cond_c, subcool_k, "EEV")
    st.dataframe(pd.DataFrame([[k,v] for k,v in exp.items()], columns=["Parameter","Value"]), hide_index=True, use_container_width=True)
    st.dataframe(solenoid_filter_drier_screening(liquid_line_mm, ref, cooling_kw), hide_index=True, use_container_width=True)

with tabs[5]:
    st.header("Electrical selections and PLC control logic")
    e1,e2,e3,e4 = st.columns(4)
    with e1:
        voltage = st.number_input("Main voltage (V)", 110.0, 690.0, 415.0, step=5.0)
        comp_flc = st.number_input("Compressor FLC/RLA (A), 0 = estimate", 0.0, 2000.0, 0.0, step=1.0)
    with e2:
        pump_kw = st.number_input("Pump motor kW", 0.0, 200.0, 3.7, step=0.1)
        fan_kw = st.number_input("Fan motor kW each", 0.0, 100.0, 0.75, step=0.05)
    with e3:
        fan_qty = st.number_input("Number of condenser fans", 0, 20, 2, step=1)
        fault_ka = st.number_input("Available fault level (kA)", 1.0, 100.0, 25.0, step=1.0)
    with e4:
        eev_control = st.checkbox("EEV control", True)
        compressor_control = st.selectbox("Compressor capacity control", ["Fixed speed", "Cylinder unloaders", "Digital scroll", "VFD", "Screw slide valve"])
    elec_df = electrical_schedule(power_kw, comp_flc, pump_kw, fan_kw, fan_qty, voltage, fault_ka)
    st.dataframe(elec_df, hide_index=True, use_container_width=True)
    plc_df = plc_logic_table(eev_control, compressor_control)
    st.dataframe(plc_df, hide_index=True, use_container_width=True)

with tabs[6]:
    st.header("Controller I/O, EEV sequence and alarm matrix")
    ci1,ci2,ci3,ci4 = st.columns(4)
    with ci1:
        num_circuits = st.number_input("Number of refrigerant circuits", 1, 4, 1, step=1)
        num_compressors = st.number_input("Number of compressors", 1, 8, 1, step=1)
    with ci2:
        use_vfd_pump = st.checkbox("Pump VFD", False)
        use_vfd_fans = st.checkbox("Fan VFD / EC fans", False)
    with ci3:
        bms_enabled = st.checkbox("BMS interface", True)
        target_sh = st.number_input("EEV target superheat (K)", 2.0, 15.0, 6.0, step=0.5)
    with ci4:
        comp_current_pct = st.number_input("Predicted compressor current (% FLA)", 0.0, 150.0, 85.0, step=1.0)
    io_df = controller_io_list(int(num_circuits), int(num_compressors), eev_control if 'eev_control' in globals() else True, use_vfd_pump, use_vfd_fans, bms_enabled)
    st.subheader("PLC / controller I/O list")
    st.dataframe(io_df, hide_index=True, use_container_width=True)
    st.subheader("EEV control sequence")
    eev_df = eev_control_sequence(target_sh)
    st.dataframe(eev_df, hide_index=True, use_container_width=True)
    st.subheader("Alarm and trip matrix")
    alarm_df = alarm_matrix(max_discharge_temp if 'max_discharge_temp' in globals() else 115.0, 3.0, 2.0)
    st.dataframe(alarm_df, hide_index=True, use_container_width=True)
    st.subheader("Compressor operating envelope checks")
    discharge_temp_val = comp_res.get("t_discharge_c", 0.0) if isinstance(comp_res, dict) else 0.0
    env_df = operating_envelope_checks(evap_c, cond_c, 65.0, -10.0, max_discharge_temp if 'max_discharge_temp' in globals() else 115.0, discharge_temp_val, comp_current_pct)
    st.dataframe(env_df, hide_index=True, use_container_width=True)

with tabs[7]:
    st.header("Safety checks, vessels and BOM")
    receiver_charge = st.number_input("Estimated refrigerant charge (kg)", 0.0, 2000.0, 25.0, step=1.0)
    floodback = st.checkbox("Floodback risk / uncertain low load operation", False)
    receiver = receiver_sizing(receiver_charge)
    accumulator = suction_accumulator_guidance("DX tube side refrigerant", compressor_type, floodback)
    st.subheader("Receiver / accumulator")
    st.dataframe(vessels_table(receiver, accumulator), hide_index=True, use_container_width=True)
    st.subheader("Safety checks")
    discharge_temp_val = comp_res.get("t_discharge_c", 0.0) if isinstance(comp_res, dict) else 0.0
    safe_df = safety_checks(discharge_temp_val, max_discharge_temp if 'max_discharge_temp' in globals() else 115.0, 15.0, subcool_k, True, superheat_k)
    st.dataframe(safe_df, hide_index=True, use_container_width=True)
    st.subheader("BOM")
    bom_df = base_bom(include_hgb=False, include_oil_separator=compressor_type in ["Screw", "VFD screw/scroll"], include_receiver=True, include_accumulator=accumulator["required"], include_eev=True)
    st.dataframe(bom_df, hide_index=True, use_container_width=True)

with tabs[8]:
    st.header("Drawings")
    st.caption("Mermaid diagrams are included for quick engineering logic. Export/production CAD drawings should be prepared separately from these schedules.")
    st.subheader("Refrigerant circuit")
    st.code(refrigerant_mermaid(include_hgb=False, include_receiver=True), language="mermaid")
    st.subheader("Control flow")
    st.code(control_mermaid(), language="mermaid")

with tabs[9]:
    st.header("Reports")
    tables = {
        "Compressor": compressor_summary_table(comp_res, pressure_unit),
        "Pressure Settings": ps_df if 'ps_df' in globals() else pd.DataFrame(),
        "Condenser": pd.DataFrame([[k,v] for k,v in (cond_res if 'cond_res' in globals() else {}).items()], columns=["Parameter","Value"]),
        "Evaporator": evaporator_table(evap_res) if 'evap_res' in globals() else pd.DataFrame(),
        "Electrical": elec_df if 'elec_df' in globals() else pd.DataFrame(),
        "PLC Logic": plc_df if 'plc_df' in globals() else pd.DataFrame(),
        "Controller IO": io_df if 'io_df' in globals() else pd.DataFrame(),
        "Alarm Matrix": alarm_df if 'alarm_df' in globals() else pd.DataFrame(),
        "Operating Envelope": env_df if 'env_df' in globals() else pd.DataFrame(),
        "Safety": safe_df if 'safe_df' in globals() else pd.DataFrame(),
        "BOM": bom_df if 'bom_df' in globals() else pd.DataFrame(),
    }
    excel_bytes = make_excel_report(tables)
    st.download_button("Download Excel report", excel_bytes, f"{project_name.replace(' ','_')}_report.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    try:
        pdf_bytes = make_pdf_report(f"{project_name} - Marine Chiller Preliminary Report", tables)
        st.download_button("Download PDF report", pdf_bytes, f"{project_name.replace(' ','_')}_report.pdf", "application/pdf")
    except Exception as exc:
        st.warning(f"PDF report could not be generated: {exc}")
    package_tables = dict(tables)
    package_tables.update({
        "Marine Compliance": comp_df if 'comp_df' in globals() else pd.DataFrame(),
        "Document Register": docreg_df if 'docreg_df' in globals() else pd.DataFrame(),
        "Commissioning Checklist": comm_df if 'comm_df' in globals() else pd.DataFrame(),
        "Maintenance Schedule": maint_df if 'maint_df' in globals() else pd.DataFrame(),
        "FAT Checklist": fat_df if 'fat_df' in globals() else pd.DataFrame(),
    })
    zip_bytes = make_csv_zip(package_tables, "Preliminary marine chiller manufacturing package. Verify all outputs before manufacture.\n")
    st.download_button("Download manufacturing CSV package ZIP", zip_bytes, f"{project_name.replace(' ','_')}_manufacturing_package.zip", "application/zip")



with tabs[10]:
    st.header("Marine compliance, QA and commissioning")
    c1,c2,c3=st.columns(3)
    with c1:
        install_location = st.selectbox("Installation location", ["Machinery room", "Deck package", "Accommodation HVAC room", "Hazardous area"])
    with c2:
        panel_location = st.selectbox("Electrical panel location", ["Indoor", "Outdoor under canopy", "Outdoor exposed"])
    with c3:
        atex_req = st.checkbox("ATEX / hazardous area certification required", install_location=="Hazardous area")
    comp_df = marine_compliance_checks(ref, install_location, water_type=="seawater", True, panel_location, atex_req)
    st.dataframe(comp_df, hide_index=True, use_container_width=True)
    st.subheader("Manufacturing document register")
    docreg_df = manufacturing_document_register()
    st.dataframe(docreg_df, hide_index=True, use_container_width=True)
    st.subheader("Commissioning checklist")
    comm_df = commissioning_checklist()
    st.dataframe(comm_df, hide_index=True, use_container_width=True)

with tabs[11]:
    st.header("Datasheets, detailed piping checks and cost/weight")
    selected_tube = st.session_state.get('selected_tube') or (filter_tubes(water_type, 'All')[0] if filter_tubes(water_type, 'All') else {'name':'Unknown','material':'Unknown','od_mm':15.88})
    shell_id = cond_res.get('shell_id_mm',0) if 'cond_res' in globals() and isinstance(cond_res,dict) else 0
    shell_od = cond_res.get('shell_od_mm',0) if 'cond_res' in globals() and isinstance(cond_res,dict) else 0
    dry_wt = cond_res.get('dry_weight_kg',0) if 'cond_res' in globals() and isinstance(cond_res,dict) else 0
    st.subheader("Preliminary TEMA condenser datasheet")
    tema_df = tema_datasheet(project_name, 'Refrigerant condenser - water tube side', heat_rejection_kw, shell_id, shell_od, int(n_tubes) if 'n_tubes' in globals() else 0, selected_tube.get('od_mm',0), tube_length_m if 'tube_length_m' in globals() else 0, int(tube_passes) if 'tube_passes' in globals() else 0, selected_tube.get('material',''), max_hp if 'max_hp' in globals() else 0, cond_c+20)
    st.dataframe(tema_df, hide_index=True, use_container_width=True)

    st.subheader("Detailed refrigerant line size screening")
    c1,c2,c3=st.columns(3)
    with c1:
        suction_density = st.number_input("Suction vapor density kg/m³", 0.1, 200.0, 18.0, step=0.5)
        suction_len = st.number_input("Suction actual length m", 1.0, 200.0, 12.0, step=1.0)
    with c2:
        discharge_density = st.number_input("Discharge vapor density kg/m³", 0.1, 300.0, 45.0, step=0.5)
        discharge_len = st.number_input("Discharge actual length m", 1.0, 200.0, 8.0, step=1.0)
    with c3:
        liquid_density = st.number_input("Liquid density kg/m³", 300.0, 1400.0, 1050.0, step=10.0)
        liquid_len = st.number_input("Liquid actual length m", 1.0, 200.0, 10.0, step=1.0)
    st.write("Suction line candidates")
    st.dataframe(select_line_size(mdot if 'mdot' in globals() else 0.1, suction_density, 6, 14, 25, equivalent_length(suction_len)), hide_index=True, use_container_width=True)
    st.write("Discharge line candidates")
    st.dataframe(select_line_size(mdot if 'mdot' in globals() else 0.1, discharge_density, 8, 18, 35, equivalent_length(discharge_len)), hide_index=True, use_container_width=True)
    st.write("Liquid line candidates")
    st.dataframe(select_line_size(mdot if 'mdot' in globals() else 0.1, liquid_density, 0.4, 1.5, 35, equivalent_length(liquid_len), mu=0.00025), hide_index=True, use_container_width=True)
    st.write("Oil return guidance")
    st.json(oil_return_guidance(compressor_type, suction_v if 'suction_v' in globals() else 8.0, 3.0))

    st.subheader("Water system detailed table")
    st.dataframe(water_system_table(cooling_kw, 12.0, 7.0, pipe_id if 'pipe_id' in globals() else 65.0, 'Water', glycol_pct if 'glycol_pct' in globals() else 0, 50, 35), hide_index=True, use_container_width=True)

    st.subheader("Weight and cost rough order estimate")
    cost = weight_cost_summary(dry_wt, selected_tube.get('material','CuNi 90/10'))
    st.dataframe(cost_table(cost), hide_index=True, use_container_width=True)


with tabs[12]:
    st.header("Service, maintenance and FAT planning")
    st.subheader("Preventive maintenance schedule")
    maint_df = maintenance_schedule()
    st.dataframe(maint_df, hide_index=True, use_container_width=True)
    st.subheader("Factory acceptance / pre-commissioning tests")
    fat_df = factory_acceptance_tests()
    st.dataframe(fat_df, hide_index=True, use_container_width=True)
    st.info("These are generic manufacturing/commissioning checklists. Add project-specific class society hold points, client ITP requirements and pressure-vessel inspection steps before issuing for manufacture.")

st.caption("Preliminary engineering tool only. Final pressure vessel, electrical, refrigeration and marine compliance design must be checked by qualified engineers and equipment suppliers.")

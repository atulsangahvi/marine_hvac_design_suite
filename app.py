import streamlit as st
import pandas as pd
import streamlit.components.v1 as components

from modules.thermo import REFS, pressure_text
from modules.compressor import discharge_temperature, compressor_summary_table, estimate_operating_point, COMPRESSOR_TYPES
from modules.pressure_switch import calculate_pressure_switches
from modules.condenser import evaluate_condenser, auto_select_tubes
from modules.evaporator import shell_tube_evaporator_screening, air_cooled_dx_coil_screening, evaporator_table, correlation_audit_table, recommended_improvement_table
from modules.flooded_evaporator import flooded_evaporator_design
from modules.evaporative_condenser import evaporative_condenser_design
from modules.system_balance import solve_balance_point, balance_table
from modules.vibration import tube_vibration_screening, vibration_table
from modules.mechanical import preliminary_tubesheet_screen, mechanical_screen_table
from modules.nozzles import condenser_nozzle_set, nozzle_summary_table
from modules.piping import water_piping_summary, refrigerant_line_check
from modules.electrical import electrical_schedule
from modules.controls import plc_logic_table
from modules.valves import expansion_valve_screening, solenoid_filter_drier_screening
from modules.vessels import receiver_sizing, suction_accumulator_guidance, vessels_table
from modules.safety import safety_checks
from modules.bom import base_bom
from modules.drawings import refrigerant_circuit_svg, control_flow_svg, shell_tube_section_svg, svg_html
from modules.reports import make_excel_report, make_pdf_report
from data.tube_library import filter_tubes, WIELAND_GEWA_C, tube_dataframe
from data.materials import MATERIALS
from data.compressor_library import compressor_library_df
from modules.compressor_map import interpolate_idw, derate_without_map
from modules.refrigerant_piping import select_line_size, oil_return_guidance, equivalent_length, line_conditions
from modules.oil_management import assess_oil_return, oil_management_table, oil_management_notes_table
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

APP_VERSION = "marine-chiller-suite-v21-coolprop-mandatory-oil-management"

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
    "6 Electrical + Controls", "7 Controller I/O + Alarms", "8 Safety + BOM", "9 Drawings", "10 Reports", "11 Compliance + QA", "12 Datasheets + Cost", "13 Service + FAT", "14 Evap Condenser", "15 System Balance + Mech", "16 Oil Management"
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
    st.header("Condenser module")
    condenser_submodule = st.radio(
        "Condenser type",
        ["Shell-and-tube water-cooled condenser", "Evaporative condenser / closed-circuit condenser"],
        horizontal=True,
        key="condenser_submodule_selector"
    )

    if condenser_submodule.startswith("Evaporative"):
        st.subheader("Evaporative condenser / closed-circuit condenser")
        st.caption("This is the same evaporative condenser engine also available in the far-right tab. It is shown here so condenser selection is in one place.")
        ec1, ec2, ec3, ec4 = st.columns(4)
        with ec1:
            ec_db = st.number_input("Entering air DB (°C)", -10.0, 60.0, 35.0, step=0.5, key="ec2_db")
            ec_wb = st.number_input("Entering air WB (°C)", -10.0, 45.0, 28.0, step=0.5, key="ec2_wb")
        with ec2:
            ec_air_mode = st.radio("Air input", ["Face velocity", "Air flow"], horizontal=True, key="ec2_air_mode")
            ec_face_v = st.number_input("Face velocity (m/s)", 0.5, 6.0, 2.5, step=0.1, key="ec2_face_v")
            ec_air_flow = st.number_input("Air flow (m³/s)", 0.0, 500.0, 0.0, step=0.5, disabled=(ec_air_mode=="Face velocity"), key="ec2_air_flow")
        with ec3:
            ec_face_w = st.number_input("Coil face width (m)", 0.2, 20.0, 1.5, step=0.1, key="ec2_face_w")
            ec_face_h = st.number_input("Coil face height (m)", 0.2, 20.0, 1.5, step=0.1, key="ec2_face_h")
        with ec4:
            ec_tubes = st.number_input("Tube count", 1, 5000, 120, step=4, key="ec2_tubes")
            ec_tube_len = st.number_input("Tube length (m)", 0.2, 20.0, 1.5, step=0.1, key="ec2_tube_len")
        with st.expander("Evaporative condenser coil, spray and fan inputs", expanded=True):
            eca, ecb, ecc, ecd = st.columns(4)
            with eca:
                ec_tube_od = st.selectbox("Tube OD", ["5/8 in", "3/4 in", "1 in"], index=1, key="ec2_tube_od")
                ec_tube_od_mm = {"5/8 in":15.88, "3/4 in":19.05, "1 in":25.4}[ec_tube_od]
                ec_rows = st.number_input("Rows in air depth", 1, 20, 6, step=1, key="ec2_rows")
            with ecb:
                ec_area_override = st.number_input("Coil outside area override (m², 0 = from tubes)", 0.0, 10000.0, 0.0, step=1.0, key="ec2_area")
                ec_K = st.number_input("Merkel K (kg/s·m², 0 = auto from air mass velocity)", 0.0, 0.30, 0.0, step=0.005, format="%.4f", key="ec2_K")
            with ecc:
                ec_U = st.number_input("Overall U dry/wet basis (W/m²K)", 50.0, 3000.0, 450.0, step=25.0, key="ec2_U")
                ec_spray = st.number_input("Spray rate (m³/h·m² plan)", 1.0, 20.0, 6.0, step=0.5, key="ec2_spray")
            with ecd:
                ec_static = st.number_input("Fan static pressure (Pa)", 20.0, 1000.0, 180.0, step=10.0, key="ec2_static")
                ec_cycles = st.number_input("Cycles of concentration", 1.5, 10.0, 3.0, step=0.5, key="ec2_cycles")
        evap_cond_res = evaporative_condenser_design(
            heat_rejection_kw=heat_rejection_kw, refrigerant=ref, condensing_temp_c=cond_c,
            ambient_db_c=ec_db, ambient_wb_c=ec_wb, coil_area_m2=(ec_area_override or None),
            tube_od_mm=ec_tube_od_mm, tube_length_m=ec_tube_len, tube_count=int(ec_tubes), rows_depth=int(ec_rows),
            face_width_m=ec_face_w, face_height_m=ec_face_h,
            air_flow_m3s=(ec_air_flow if ec_air_mode=="Air flow" and ec_air_flow>0 else None), face_velocity_ms=ec_face_v,
            spray_rate_m3h_m2=ec_spray, k_merkel_kg_s_m2=(ec_K if ec_K > 0 else None), overall_u_w_m2k_dry_basis=ec_U,
            fan_static_pa=ec_static, cycles_of_concentration=ec_cycles
        )
        c1,c2,c3,c4 = st.columns(4)
        c1.metric("Required heat rejection", f"{evap_cond_res.get('heat_rejection_required_kw',0):.1f} kW")
        c2.metric("Possible heat rejection", f"{evap_cond_res.get('heat_rejection_possible_kw',0):.1f} kW")
        c3.metric("Condensing-WB approach", f"{evap_cond_res.get('condensing_to_wb_approach_k',0):.1f} K")
        c4.metric("Status", str(evap_cond_res.get('status','')))
        d1,d2,d3,d4 = st.columns(4)
        d1.metric("Air flow", f"{evap_cond_res.get('air_flow_m3s',0):.2f} m³/s")
        d2.metric("Spray water", f"{evap_cond_res.get('spray_water_flow_m3h',0):.2f} m³/h")
        d3.metric("Make-up water", f"{evap_cond_res.get('makeup_water_m3h',0):.2f} m³/h")
        d4.metric("Fan + pump", f"{evap_cond_res.get('fan_power_kw',0)+evap_cond_res.get('spray_pump_power_kw',0):.2f} kW")
        st.dataframe(pd.DataFrame([[k,v] for k,v in evap_cond_res.items()], columns=["Parameter","Value"]), hide_index=True, use_container_width=True)
        st.info(str(evap_cond_res.get('guidance','')))
        st.divider()
        st.caption("Shell-and-tube water-cooled condenser inputs are below. Change the condenser type selector above if you only want that mode.")

    st.subheader("Shell-and-tube water-cooled condenser")
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
        baffle_spacing_override = st.number_input("Condenser baffle spacing override (mm, 0 = auto)", 0.0, 1000.0, 0.0, step=5.0)
        baffle_cut_pct = st.number_input("Condenser baffle cut (%)", 15.0, 45.0, 25.0, step=1.0)

    baffle_spacing_for_calc = baffle_spacing_override if baffle_spacing_override > 0 else None
    # v19: feed the actual discharge temperature (from the Compressor tab result if
    # available) into the condenser three-zone model instead of the +25 K default.
    _disc_c = None
    try:
        if 'comp_res' in globals() and isinstance(comp_res, dict) and not comp_res.get("error"):
            _disc_c = float(comp_res.get("t_discharge_c"))
    except Exception:
        _disc_c = None
    st.caption("Baffle spacing affects shell-side refrigerant velocity/pressure drop and shell-side HTC. Auto estimate is shown in results; override it here when you want to study spacing manually.")

    tubes = filter_tubes(water_type, od_filter)
    if not tubes:
        st.error("No tubes found for selected water type and OD filter.")
        cond_res = {}
    elif mode == "Manual tube selection":
        tube_names = [t["name"] for t in tubes]
        tname = st.selectbox("Tube from library", tube_names)
        tube = next(t for t in tubes if t["name"] == tname)
        cond_res = evaluate_condenser(heat_rejection_kw, water_type, cw_in, cw_out, n_tubes, tube_passes, tube_length_m, tube, mult, pitch_ratio, shell_thk, condensing_temp_c=cond_c, refrigerant=ref, baffle_spacing_mm=baffle_spacing_for_calc, baffle_cut_pct=baffle_cut_pct, discharge_temp_c=_disc_c, subcool_k=subcool_k)
        st.session_state.selected_tube = tube
        st.dataframe(pd.DataFrame([[k,v] for k,v in cond_res.items() if k != "tube"], columns=["Parameter","Value"]), hide_index=True, use_container_width=True)
    else:
        df_auto = auto_select_tubes(heat_rejection_kw, water_type, cw_in, cw_out, n_tubes, tube_passes, tube_length_m, od_filter=od_filter, condensing_htc_multiplier=mult, pitch_ratio=pitch_ratio, shell_thk_mm=shell_thk, condensing_temp_c=cond_c, refrigerant=ref, baffle_spacing_mm=baffle_spacing_for_calc, baffle_cut_pct=baffle_cut_pct, discharge_temp_c=_disc_c, subcool_k=subcool_k)
        st.dataframe(df_auto, hide_index=True, use_container_width=True)
        if not df_auto.empty:
            best_name = df_auto.iloc[0]["tube"]
            tube = next(t for t in tubes if t["name"] == best_name)
            cond_res = evaluate_condenser(heat_rejection_kw, water_type, cw_in, cw_out, n_tubes, tube_passes, tube_length_m, tube, mult, pitch_ratio, shell_thk, condensing_temp_c=cond_c, refrigerant=ref, baffle_spacing_mm=baffle_spacing_for_calc, baffle_cut_pct=baffle_cut_pct, discharge_temp_c=_disc_c, subcool_k=subcool_k)
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
        d1,d2,d3,d4 = st.columns(4)
        d1.metric("Baffle spacing", f"{cond_res.get('baffle_spacing_mm',0):.0f} mm")
        d2.metric("Baffle cut", f"{cond_res.get('baffle_cut_pct',0):.0f}%")
        d3.metric("Freon shell ΔP", f"{cond_res.get('shell_ref_dp_kpa',0):.1f} kPa")
        d4.metric("Freon shell ΔP status", str(cond_res.get('shell_ref_dp_status','CHECK')))
        st.caption(cond_res.get('shell_ref_dp_note', ''))
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
    evap_mode = st.radio("Evaporator type", ["Shell-and-tube DX water/glycol", "Flooded shell-and-tube", "Air-cooled DX coil"], horizontal=True)
    if evap_mode.startswith("Flooded"):
        f1,f2,f3,f4 = st.columns(4)
        with f1:
            fl_chw_in = st.number_input("Flooded CHW/glycol entering (°C)", -20.0, 30.0, 12.0, step=0.5)
            fl_chw_out = st.number_input("Flooded CHW/glycol leaving (°C)", -25.0, 25.0, 7.0, step=0.5)
        with f2:
            fl_glycol = st.number_input("Flooded glycol %", 0.0, 60.0, 0.0, step=1.0)
            fl_water_flow = st.number_input("Flooded water/glycol flow (m³/h, 0 = calculate)", 0.0, 5000.0, 0.0, step=0.1)
        with f3:
            fl_tube_count = st.number_input("Flooded tube count", 4, 3000, 100, step=4)
            fl_tube_len = st.number_input("Flooded tube length (m)", 0.2, 12.0, 1.5, step=0.1)
        with f4:
            fl_passes = st.number_input("Flooded water-side passes", 1, 12, 2, step=1)
            fl_level = st.number_input("Refrigerant liquid level (% shell dia)", 25.0, 85.0, 55.0, step=5.0)
        with st.expander("Flooded evaporator geometry, boiling and oil-return inputs", expanded=True):
            fg1,fg2,fg3,fg4 = st.columns(4)
            with fg1:
                fl_tube_od = st.selectbox("Flooded tube OD", ["5/8 in", "3/4 in", "1 in"], index=0)
                fl_tube_od_mm = {"5/8 in":15.88, "3/4 in":19.05, "1 in":25.4}[fl_tube_od]
                fl_wall = st.number_input("Flooded tube wall (mm)", 0.25, 3.0, 0.8, step=0.05)
            with fg2:
                fl_pitch_ratio = st.number_input("Flooded tube pitch ratio", 1.10, 2.00, 1.25, step=0.05)
                fl_shell_id = st.number_input("Flooded shell ID override (mm, 0 = estimate)", 0.0, 3000.0, 0.0, step=10.0)
            with fg3:
                fl_enh = st.number_input("Flooded enhanced boiling multiplier", 1.0, 6.0, 1.8, step=0.1)
                fl_shell_allow = st.number_input("Shell length allowance beyond tubes (m)", 0.05, 2.0, 0.25, step=0.05)
            with fg4:
                fl_max_wdp = st.number_input("Flooded max water ΔP (kPa)", 1.0, 500.0, 80.0, step=5.0)
                fl_oil = st.selectbox("Oil return strategy", ["Oil pot / eductor return", "Jet pump oil return", "Skimmer with oil rectifier", "Not yet defined"], index=0)
        evap_res = flooded_evaporator_design(
            capacity_kw=cooling_kw, refrigerant=ref, evap_temp_c=evap_c,
            chw_in_c=fl_chw_in, chw_out_c=fl_chw_out, fluid="Water/Glycol", glycol_pct=fl_glycol,
            water_flow_m3h_input=(fl_water_flow or None), tube_od_mm=fl_tube_od_mm, tube_wall_mm=fl_wall,
            tube_length_m=fl_tube_len, tube_count=int(fl_tube_count), tube_passes=int(fl_passes),
            pitch_ratio=fl_pitch_ratio, shell_id_mm=(fl_shell_id or None), shell_length_allowance_m=fl_shell_allow,
            liquid_level_pct_shell_dia=fl_level, enhanced_boiling_multiplier=fl_enh,
            max_water_dp_kpa=fl_max_wdp, oil_return_type=fl_oil
        )
        k1,k2,k3,k4 = st.columns(4)
        k1.metric("Flooded CHW flow", f"{evap_res.get('water_flow_m3h',0):.2f} m³/h")
        k2.metric("Water velocity", f"{evap_res.get('water_velocity_ms',0):.2f} m/s", evap_res.get('water_velocity_status',''))
        k3.metric("Water ΔP", f"{evap_res.get('water_dp_kpa',0):.1f} kPa", evap_res.get('water_dp_status',''))
        k4.metric("Refrigerant charge", f"{evap_res.get('estimated_refrigerant_charge_kg',0):.1f} kg")
        h1,h2,h3,h4 = st.columns(4)
        h1.metric("Uo", f"{evap_res.get('Uo_w_m2k',0):.0f} W/m²K")
        h2.metric("Boiling HTC", f"{evap_res.get('shell_side_boiling_htc_w_m2k',0):.0f} W/m²K")
        h3.metric("Q possible", f"{evap_res.get('capacity_possible_kw',0):.1f} kW")
        h4.metric("Status", str(evap_res.get('status','')))
        flooded_warnings = evap_res.get('warnings', 'None')
        if flooded_warnings and flooded_warnings != 'None':
            if isinstance(flooded_warnings, (list, tuple)):
                st.warning('\n'.join(str(w) for w in flooded_warnings))
            else:
                st.warning(str(flooded_warnings))
        else:
            st.success("No major flooded-evaporator warnings from screening.")
        st.info(str(evap_res.get('guidance','')))
    elif evap_mode.startswith("Shell"):
        e1,e2,e3,e4 = st.columns(4)
        with e1:
            chw_in = st.number_input("CHW/glycol entering cooler (°C)", -20.0, 30.0, 12.0, step=0.5)
            chw_out = st.number_input("CHW/glycol leaving cooler (°C)", -25.0, 25.0, 7.0, step=0.5)
        with e2:
            glycol = st.number_input("Glycol %", 0.0, 60.0, 0.0, step=1.0)
            ev_water_flow = st.number_input("CHW/glycol flow (m³/h, 0 = calculate from kW and ΔT)", 0.0, 5000.0, 0.0, step=0.1)
        with e3:
            evap_tube_count = st.number_input("Evaporator tube count", 4, 2000, 80, step=4)
            evap_tube_len = st.number_input("Evaporator tube length (m)", 0.2, 10.0, 1.2, step=0.1)
        with e4:
            evap_passes = st.number_input("Evaporator passes", 1, 12, 2, step=1)
            ref_in_tubes = st.checkbox("DX mode: refrigerant in tubes", value=True, help="Recommended for DX shell-and-tube evaporator. Uncheck only for flooded/shell-side refrigerant screening.")
        with st.expander("Advanced shell-and-tube evaporator geometry and limits", expanded=True):
            g1,g2,g3,g4 = st.columns(4)
            with g1:
                ev_tube_od = st.selectbox("Evaporator tube OD", ["3/8 in", "1/2 in", "5/8 in", "3/4 in"], index=2)
                ev_tube_od_mm = {"3/8 in": 9.52, "1/2 in": 12.70, "5/8 in": 15.88, "3/4 in": 19.05}[ev_tube_od]
                ev_tube_wall = st.number_input("Evaporator tube wall (mm)", 0.25, 3.0, 0.8, step=0.05)
            with g2:
                ev_shell_id = st.number_input("Evaporator shell ID override (mm, 0 = estimate)", 0.0, 2000.0, 0.0, step=5.0)
                ev_baffle_spacing = st.number_input("Evaporator baffle spacing override (mm, 0 = estimate)", 0.0, 1000.0, 0.0, step=5.0)
            with g3:
                ev_baffle_cut = st.number_input("Evaporator baffle cut (%)", 15.0, 45.0, 25.0, step=1.0)
                ev_pitch_ratio = st.number_input("Evaporator tube pitch ratio", 1.10, 2.00, 1.25, step=0.05)
            with g4:
                evap_u = st.number_input("Override evaporator U (W/m²K, 0 = calculate)", 0.0, 5000.0, 0.0, step=50.0)
                ev_ref_mdot = st.number_input("Refrigerant mass flow for evaporator (kg/s, 0 = estimate)", 0.0, 20.0, 0.0, step=0.01, format="%.4f")
            l1,l2,l3 = st.columns(3)
            with l1:
                ev_max_wdp = st.number_input("Max allowable water-side ΔP (kPa)", 1.0, 500.0, 80.0, step=5.0)
            with l2:
                ev_max_rdp = st.number_input("Max allowable refrigerant-side ΔP (kPa)", 1.0, 500.0, 80.0, step=5.0)
            with l3:
                ev_target_sh = st.number_input("Target evaporator outlet superheat (K)", 1.0, 20.0, superheat_k, step=0.5)
        evap_res = shell_tube_evaporator_screening(
            cooling_kw, chw_in, chw_out, "Water/Glycol", glycol, evap_c, ev_tube_od_mm, evap_tube_len,
            evap_tube_count, evap_passes, evap_u, tube_wall_mm=ev_tube_wall, refrigerant_in_tubes=ref_in_tubes,
            refrigerant=ref, shell_id_mm=(ev_shell_id or None), baffle_spacing_mm=(ev_baffle_spacing or None),
            baffle_cut_pct=ev_baffle_cut, pitch_ratio=ev_pitch_ratio,
            refrigerant_mass_flow_kg_s=(ev_ref_mdot or None), water_flow_m3h_input=(ev_water_flow or None),
            max_water_dp_kpa=ev_max_wdp, max_refrigerant_dp_kpa=ev_max_rdp, target_superheat_k=ev_target_sh
        )
        k1,k2,k3,k4 = st.columns(4)
        k1.metric("CHW/glycol flow", f"{evap_res.get('water_flow_m3h',0):.2f} m³/h")
        k2.metric("Water velocity", f"{evap_res.get('water_velocity_ms',0):.2f} m/s", evap_res.get('water_velocity_status',''))
        k3.metric("Water ΔP", f"{evap_res.get('water_dp_kpa_est',0):.1f} kPa", evap_res.get('water_dp_status',''))
        k4.metric("Freon ΔP", f"{evap_res.get('refrigerant_dp_kpa_est',0):.1f} kPa", evap_res.get('refrigerant_dp_status',''))
        h1,h2,h3,h4 = st.columns(4)
        h1.metric("Cwater", f"{evap_res.get('water_heat_capacity_rate_kw_per_k',0):.2f} kW/K")
        h2.metric("Limiting side", str(evap_res.get('limiting_side','')))
        h3.metric("Qmax by Cmin", f"{evap_res.get('max_heat_transfer_possible_kw_by_cmin',0):.1f} kW")
        h4.metric("Effectiveness", f"{evap_res.get('effectiveness_based_on_cmin',0):.2f}")
    else:
        a1,a2,a3,a4 = st.columns(4)
        with a1:
            air_input_mode = st.radio("Air input", ["Air flow", "Face velocity"], horizontal=True)
            face_velocity_in = st.number_input("Face velocity (m/s)", 0.5, 6.0, 2.0, step=0.1) if air_input_mode == "Face velocity" else 0.0
            air_flow = st.number_input("Air flow (m³/s)", 0.1, 200.0, 4.0, step=0.1)
        with a2:
            psych_mode = st.radio("Entering air method", ["DB+WB", "DB+RH"], horizontal=True)
            db = st.number_input("Entering DB (°C)", 0.0, 60.0, 27.0, step=0.5)
            wb = st.number_input("Entering WB (°C)", 0.0, 40.0, 19.0, step=0.5, disabled=(psych_mode=="DB+RH"))
            rh = st.number_input("Entering RH (%)", 1.0, 100.0, 50.0, step=1.0, disabled=(psych_mode=="DB+WB"))
        with a3:
            coil_width = st.number_input("Coil finned length / face width (m)", 0.1, 10.0, 1.2, step=0.05)
            coil_height = st.number_input("Coil face height (m)", 0.1, 10.0, 1.0, step=0.05)
        with a4:
            rows = st.number_input("Coil rows", 1, 12, 4, step=1)
            fpi = st.number_input("FPI", 4.0, 24.0, 12.0, step=1.0)
        with st.expander("Advanced air-cooled DX coil geometry and limits", expanded=True):
            ac1,ac2,ac3,ac4 = st.columns(4)
            with ac1:
                air_tube_od_choice = st.selectbox("Tube OD", ["7 mm", "3/8 in", "1/2 in", "5/8 in"], index=1)
                air_tube_od_mm = {"7 mm":7.0, "3/8 in":9.52, "1/2 in":12.70, "5/8 in":15.88}[air_tube_od_choice]
                air_tube_wall = st.number_input("Tube wall (mm)", 0.25, 2.0, 0.35, step=0.05)
            with ac2:
                tube_type = st.selectbox("Fin/tube type", ["Smooth", "Microfin", "Microchannel/flat"], index=0)
                circuits = st.number_input("Refrigerant circuits", 1, 100, 4, step=1)
            with ac3:
                st_pitch = st.number_input("Transverse tube pitch (mm)", 10.0, 80.0, 25.4, step=0.5)
                sl_pitch = st.number_input("Longitudinal tube pitch (mm)", 10.0, 80.0, 22.0, step=0.5)
            with ac4:
                ac_ref_mdot = st.number_input("Refrigerant mass flow for air coil (kg/s, 0 = estimate)", 0.0, 20.0, 0.0, step=0.01, format="%.4f")
                max_air_dp = st.number_input("Max air-side ΔP (Pa)", 10.0, 1000.0, 180.0, step=10.0)
                max_ref_dp = st.number_input("Max refrigerant ΔP (kPa)", 1.0, 500.0, 80.0, step=5.0)
        face_area = coil_width * coil_height
        evap_res = air_cooled_dx_coil_screening(
            cooling_kw, air_flow, db, wb, evap_c, rows, face_area, fpi, circuit_count=int(circuits), tube_type=tube_type,
            input_method=psych_mode, rh_pct=rh, face_width_m=coil_width, face_height_m=coil_height,
            face_velocity_input_ms=(face_velocity_in or None), tube_od_mm=air_tube_od_mm, tube_wall_mm=air_tube_wall,
            tube_pitch_longitudinal_mm=sl_pitch, tube_pitch_transverse_mm=st_pitch, refrigerant=ref,
            refrigerant_mass_flow_kg_s=(ac_ref_mdot or None), condensing_temp_c=cond_c, target_superheat_k=superheat_k,
            max_air_dp_pa=max_air_dp, max_refrigerant_dp_kpa=max_ref_dp
        )
        k1,k2,k3,k4 = st.columns(4)
        k1.metric("Air flow", f"{evap_res.get('air_flow_m3s',0):.2f} m³/s")
        k2.metric("Face velocity", f"{evap_res.get('face_velocity_ms',0):.2f} m/s", evap_res.get('face_velocity_status',''))
        k3.metric("Air ΔP", f"{evap_res.get('air_dp_pa_est',0):.0f} Pa", evap_res.get('air_dp_status',''))
        k4.metric("Freon ΔP", f"{evap_res.get('refrigerant_dp_kpa_est',0):.1f} kPa", evap_res.get('refrigerant_dp_status',''))
        st.caption(str(evap_res.get('expected_issue_due_to_dp','')))
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
    st.caption("SVG schematics are generated directly by the app. They are stable in Streamlit and avoid Mermaid parser errors. Production CAD/DXF drawings must still be prepared from the final approved schedules.")

    st.subheader("Refrigerant circuit P&ID schematic")
    refrigerant_svg = refrigerant_circuit_svg(include_hgb=False, include_receiver=True, evaporator_type="Selected evaporator")
    components.html(svg_html(refrigerant_svg), height=430, scrolling=True)
    st.download_button("Download refrigerant circuit SVG", refrigerant_svg.encode("utf-8"), "refrigerant_circuit.svg", "image/svg+xml")

    st.subheader("Control sequence schematic")
    control_svg = control_flow_svg()
    components.html(svg_html(control_svg), height=500, scrolling=True)
    st.download_button("Download control sequence SVG", control_svg.encode("utf-8"), "control_sequence.svg", "image/svg+xml")

    st.subheader("Shell-and-tube section schematic")
    hx_svg = shell_tube_section_svg("Shell-and-tube condenser / evaporator section", flooded=False)
    components.html(svg_html(hx_svg), height=410, scrolling=True)
    st.download_button("Download shell-and-tube section SVG", hx_svg.encode("utf-8"), "shell_tube_section.svg", "image/svg+xml")

    st.subheader("Flooded evaporator section schematic")
    flooded_svg = shell_tube_section_svg("Flooded shell-and-tube evaporator section", flooded=True)
    components.html(svg_html(flooded_svg), height=410, scrolling=True)
    st.download_button("Download flooded evaporator SVG", flooded_svg.encode("utf-8"), "flooded_evaporator_section.svg", "image/svg+xml")

with tabs[9]:
    st.header("Reports")
    tables = {
        "Compressor": compressor_summary_table(comp_res, pressure_unit),
        "Pressure Settings": ps_df if 'ps_df' in globals() else pd.DataFrame(),
        "Condenser": pd.DataFrame([[k,v] for k,v in (cond_res if 'cond_res' in globals() else {}).items()], columns=["Parameter","Value"]),
        "Evaporator": evaporator_table(evap_res) if 'evap_res' in globals() else pd.DataFrame(),
        "Evaporative Condenser": pd.DataFrame([[k,v] for k,v in (evap_cond_res if 'evap_cond_res' in globals() else {}).items()], columns=["Parameter","Value"]),
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
    # v15: line densities/viscosities auto-computed from the actual refrigerant
    # states (suction with superheat, discharge gas, subcooled liquid); enter 0 to
    # use the calculated value or type a manual override.
    _sc = line_conditions(ref, "suction", evap_c, cond_c)
    _dc = line_conditions(ref, "discharge", evap_c, cond_c)
    _lc = line_conditions(ref, "liquid", evap_c, cond_c)
    c1,c2,c3=st.columns(3)
    with c1:
        suction_density = st.number_input(f"Suction density kg/m³ (calc {_sc['rho']:.1f}, 0=auto)", 0.0, 200.0, 0.0, step=0.5)
        suction_len = st.number_input("Suction actual length m", 1.0, 200.0, 12.0, step=1.0)
    with c2:
        discharge_density = st.number_input(f"Discharge density kg/m³ (calc {_dc['rho']:.1f}, 0=auto)", 0.0, 300.0, 0.0, step=0.5)
        discharge_len = st.number_input("Discharge actual length m", 1.0, 200.0, 8.0, step=1.0)
    with c3:
        liquid_density = st.number_input(f"Liquid density kg/m³ (calc {_lc['rho']:.0f}, 0=auto)", 0.0, 1400.0, 0.0, step=10.0)
        liquid_len = st.number_input("Liquid actual length m", 1.0, 200.0, 10.0, step=1.0)
    suction_density = suction_density if suction_density > 0 else _sc['rho']
    discharge_density = discharge_density if discharge_density > 0 else _dc['rho']
    liquid_density = liquid_density if liquid_density > 0 else _lc['rho']
    _m = mdot if 'mdot' in globals() else 0.1
    st.write("Suction line candidates (includes equivalent SST loss)")
    st.dataframe(select_line_size(_m, suction_density, 6, 14, 25, equivalent_length(suction_len), mu=_sc['mu'], ref=ref, line="suction", evap_c=evap_c, cond_c=cond_c), hide_index=True, use_container_width=True)
    st.write("Discharge line candidates (includes equivalent SCT loss)")
    st.dataframe(select_line_size(_m, discharge_density, 8, 18, 35, equivalent_length(discharge_len), mu=_dc['mu'], ref=ref, line="discharge", evap_c=evap_c, cond_c=cond_c), hide_index=True, use_container_width=True)
    st.write("Liquid line candidates")
    st.dataframe(select_line_size(_m, liquid_density, 0.4, 1.5, 35, equivalent_length(liquid_len), mu=_lc['mu']), hide_index=True, use_container_width=True)
    st.subheader("Oil return guidance")
    oil_res = oil_return_guidance(
        compressor_type,
        suction_v if 'suction_v' in globals() else 8.0,
        3.0,
        refrigerant=ref,
        load_fraction=1.0,
        oil_separator=False,
        flooded_evaporator=False,
    )
    st.dataframe(oil_management_table(oil_res), hide_index=True, use_container_width=True)
    st.dataframe(oil_management_notes_table(oil_res), hide_index=True, use_container_width=True)

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



with tabs[13]:
    st.header("Evaporative condenser / closed-circuit condenser module")
    st.caption("This module uses the cooling-tower/evaporative-fluid-cooler Merkel concept with a coil area and spray-water circuit. Calibrate K and U against vendor data before manufacture.")
    ec1,ec2,ec3,ec4 = st.columns(4)
    with ec1:
        ec_db = st.number_input("Evap condenser entering air DB (°C)", -10.0, 60.0, 35.0, step=0.5)
        ec_wb = st.number_input("Evap condenser entering air WB (°C)", -10.0, 45.0, 28.0, step=0.5)
    with ec2:
        ec_air_mode = st.radio("Evap condenser air input", ["Face velocity", "Air flow"], horizontal=True)
        ec_face_v = st.number_input("Evap condenser face velocity (m/s)", 0.5, 6.0, 2.5, step=0.1)
        ec_air_flow = st.number_input("Evap condenser air flow (m³/s)", 0.0, 500.0, 0.0, step=0.5, disabled=(ec_air_mode=="Face velocity"))
    with ec3:
        ec_face_w = st.number_input("Evap condenser coil face width (m)", 0.2, 20.0, 1.5, step=0.1)
        ec_face_h = st.number_input("Evap condenser coil face height (m)", 0.2, 20.0, 1.5, step=0.1)
    with ec4:
        ec_tubes = st.number_input("Evap condenser tube count", 1, 5000, 120, step=4)
        ec_tube_len = st.number_input("Evap condenser tube length (m)", 0.2, 20.0, 1.5, step=0.1)
    with st.expander("Evaporative condenser coil, spray and fan inputs", expanded=True):
        eca,ecb,ecc,ecd = st.columns(4)
        with eca:
            ec_tube_od = st.selectbox("Evap condenser tube OD", ["5/8 in", "3/4 in", "1 in"], index=1)
            ec_tube_od_mm = {"5/8 in":15.88, "3/4 in":19.05, "1 in":25.4}[ec_tube_od]
            ec_rows = st.number_input("Evap condenser rows in air depth", 1, 20, 6, step=1)
        with ecb:
            ec_area_override = st.number_input("Coil outside area override (m², 0 = from tubes)", 0.0, 10000.0, 0.0, step=1.0)
            ec_K = st.number_input("Merkel K (kg/s·m², 0 = auto from air mass velocity)", 0.0, 0.30, 0.0, step=0.005, format="%.4f")
        with ecc:
            ec_U = st.number_input("Overall U dry/wet basis (W/m²K)", 50.0, 3000.0, 450.0, step=25.0)
            ec_spray = st.number_input("Spray rate (m³/h·m² plan)", 1.0, 20.0, 6.0, step=0.5)
        with ecd:
            ec_static = st.number_input("Fan static pressure (Pa)", 20.0, 1000.0, 180.0, step=10.0)
            ec_cycles = st.number_input("Cycles of concentration", 1.5, 10.0, 3.0, step=0.5)
    evap_cond_res = evaporative_condenser_design(
        heat_rejection_kw=heat_rejection_kw, refrigerant=ref, condensing_temp_c=cond_c,
        ambient_db_c=ec_db, ambient_wb_c=ec_wb, coil_area_m2=(ec_area_override or None),
        tube_od_mm=ec_tube_od_mm, tube_length_m=ec_tube_len, tube_count=int(ec_tubes), rows_depth=int(ec_rows),
        face_width_m=ec_face_w, face_height_m=ec_face_h,
        air_flow_m3s=(ec_air_flow if ec_air_mode=="Air flow" and ec_air_flow>0 else None), face_velocity_ms=ec_face_v,
        spray_rate_m3h_m2=ec_spray, k_merkel_kg_s_m2=(ec_K if ec_K > 0 else None), overall_u_w_m2k_dry_basis=ec_U,
        fan_static_pa=ec_static, cycles_of_concentration=ec_cycles
    )
    c1,c2,c3,c4 = st.columns(4)
    c1.metric("Required heat rejection", f"{evap_cond_res.get('heat_rejection_required_kw',0):.1f} kW")
    c2.metric("Possible heat rejection", f"{evap_cond_res.get('heat_rejection_possible_kw',0):.1f} kW")
    c3.metric("Condensing-WB approach", f"{evap_cond_res.get('condensing_to_wb_approach_k',0):.1f} K")
    c4.metric("Status", str(evap_cond_res.get('status','')))
    d1,d2,d3,d4 = st.columns(4)
    d1.metric("Air flow", f"{evap_cond_res.get('air_flow_m3s',0):.2f} m³/s")
    d2.metric("Spray water", f"{evap_cond_res.get('spray_water_flow_m3h',0):.2f} m³/h")
    d3.metric("Make-up water", f"{evap_cond_res.get('makeup_water_m3h',0):.2f} m³/h")
    d4.metric("Fan + pump", f"{evap_cond_res.get('fan_power_kw',0)+evap_cond_res.get('spray_pump_power_kw',0):.2f} kW")
    st.dataframe(pd.DataFrame([[k,v] for k,v in evap_cond_res.items()], columns=["Parameter","Value"]), hide_index=True, use_container_width=True)
    st.info(str(evap_cond_res.get('guidance','')))



with tabs[15]:
    st.header("Oil management and oil return screening")
    st.caption("Oil return must be checked at design load and minimum compressor capacity. This module is a screening tool; verify final suction piping with the compressor manufacturer's piping manual.")
    o1, o2, o3, o4 = st.columns(4)
    with o1:
        oil_suction_v = st.number_input("Actual suction velocity (m/s)", 0.1, 40.0, 8.0, step=0.1)
        oil_min_load = st.number_input("Minimum operating load fraction", 0.1, 1.0, 1.0, step=0.05)
    with o2:
        oil_vertical = st.number_input("Vertical suction riser height (m)", 0.0, 100.0, 3.0, step=0.5)
        oil_horizontal = st.number_input("Horizontal suction run (m)", 0.0, 500.0, 12.0, step=1.0)
    with o3:
        oil_separator = st.checkbox("Oil separator fitted", value=False)
        flooded_oil = st.checkbox("Flooded evaporator / shell oil logging risk", value=False)
    with o4:
        st.metric("Refrigerant", ref)
        st.metric("Compressor", compressor_type)
    oil_result = assess_oil_return(
        compressor_type=compressor_type,
        refrigerant=ref,
        actual_suction_velocity_m_s=oil_suction_v,
        vertical_riser_m=oil_vertical,
        horizontal_run_m=oil_horizontal,
        load_fraction=oil_min_load,
        oil_separator=oil_separator,
        flooded_evaporator=flooded_oil,
    )
    if oil_result.get("oil_return_ok"):
        st.success(f"Oil return screening PASS. Velocity margin: {oil_result.get('velocity_margin_m_s')} m/s")
    else:
        st.error(f"Oil return screening CHECK. Velocity margin: {oil_result.get('velocity_margin_m_s')} m/s")
    st.dataframe(oil_management_table(oil_result), hide_index=True, use_container_width=True)
    st.dataframe(oil_management_notes_table(oil_result), hide_index=True, use_container_width=True)
    st.info("For vertical risers, also check double-riser arrangement, oil traps at base of risers, minimum compressor step/unloading, oil separator efficiency, and flooded evaporator oil return method.")

st.caption("Preliminary engineering tool only. Final pressure vessel, electrical, refrigeration and marine compliance design must be checked by qualified engineers and equipment suppliers.")


with tabs[14]:
    st.header("System balance point and mechanical screening")
    st.caption("The component tabs size each exchanger at ASSUMED temperatures. This tab solves where the assembled compressor + condenser + evaporator actually settle — the operating point you will measure at FAT.")

    st.subheader("Balance-point solver")
    b1, b2, b3 = st.columns(3)
    with b1:
        sb_evap_ua = st.number_input("Evaporator UA (kW/K) = Uo x Ao from Evaporator tab", 0.1, 500.0,
                                     float(st.session_state.get("sb_evap_ua_default", 8.0)), step=0.5)
        sb_chw_flow = st.number_input("Chilled water flow (m³/h)", 0.1, 2000.0, max(cooling_kw*0.172, 1.0), step=0.5)
        sb_chw_in = st.number_input("Chilled water inlet (°C)", -5.0, 30.0, 12.0, step=0.5)
    with b2:
        sb_cond_ua = st.number_input("Condenser UA (kW/K) = Uo x Ao from Condenser tab", 0.1, 500.0,
                                     float(cond_res.get("uo_w_m2k", 2000.0)) * float(cond_res.get("area_m2", 3.0)) / 1000.0 if isinstance(cond_res, dict) and cond_res else 6.0,
                                     step=0.5)
        sb_cw_flow = st.number_input("Condenser water flow (m³/h)",
                                     0.1, 2000.0, float(cond_res.get("water_flow_m3h", 10.0)) if isinstance(cond_res, dict) and cond_res else 10.0, step=0.5)
        sb_cw_in = st.number_input("Condenser water inlet (°C)", 0.0, 45.0, float(cw_in), step=0.5)
    with b3:
        sb_sh = st.number_input("Suction superheat (K)", 0.0, 25.0, float(superheat_k), step=0.5)
        sb_sc = st.number_input("Liquid subcooling (K)", 0.0, 15.0, float(subcool_k), step=0.5)
        st.caption(f"Compressor calibrated to design point: {cooling_kw:.1f} kW at {evap_c:.1f}/{cond_c:.1f} °C, {compressor_type}.")

    sb = solve_balance_point(ref, compressor_type, cooling_kw, evap_c, cond_c,
                             sb_evap_ua, sb_cond_ua, sb_chw_in, sb_chw_flow, sb_cw_in, sb_cw_flow,
                             superheat_k=sb_sh, subcool_k=sb_sc)
    if sb.get("status") == "ERROR":
        st.error(sb.get("error", "Balance solver failed."))
    else:
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Actual capacity", f"{sb['actual_cooling_capacity_kw']:.1f} kW", f"{sb['capacity_vs_design_pct']-100:+.1f}% vs design")
        m2.metric("Balanced Tevap / Tcond", f"{sb['balanced_evaporating_temp_c']:.1f} / {sb['balanced_condensing_temp_c']:.1f} °C")
        m3.metric("COP", f"{sb['cop']:.2f}")
        m4.metric("Discharge temp", f"{sb['discharge_temp_c']:.1f} °C")
        st.dataframe(balance_table(sb), hide_index=True, use_container_width=True)
        if hasattr(sb, "get") and "fallback" in str(sb.get("notes","")).lower():
            st.info("Compressor fallback model in use (no CoolProp in this runtime).")

    st.subheader("Condenser tube vibration screening (TEMA-style)")
    if isinstance(cond_res, dict) and cond_res and 'selected_tube' in st.session_state:
        _t = st.session_state.selected_tube
        vib = tube_vibration_screening(
            tube_od_mm=float(_t.get("od_mm", 15.88)), tube_id_mm=float(_t.get("id_mm", 12.3)),
            material=_t.get("material", "CuNi 90/10 C70600"),
            baffle_spacing_mm=float(cond_res.get("baffle_spacing_mm", 200.0)),
            shell_crossflow_velocity_ms=float(cond_res.get("shell_ref_velocity_m_s", 1.0)),
            shell_fluid_density_kg_m3=200.0,  # mean condensing two-phase density; refine with detailed design
            tube_side_fluid_density_kg_m3=1025.0 if "sea" in str(water_type).lower() else 1000.0,
            pitch_ratio=float(pitch_ratio) if 'pitch_ratio' in globals() else 1.25,
            service="condensing")
        st.dataframe(vibration_table(vib), hide_index=True, use_container_width=True)
        if vib["overall_status"] != "OK":
            st.warning(vib["guidance"])
        st.subheader("Condenser preliminary tubesheet thickness screening")
        ts = preliminary_tubesheet_screen(
            shell_id_mm=float(cond_res.get("shell_id_mm", cond_res.get("shell_id_mm_est", 250.0))),
            tube_od_mm=float(_t.get("od_mm", 15.88)),
            design_pressure_bar_g=float(st.number_input("Condenser design pressure for tubesheet screen (bar g)", 1.0, 45.0, 24.0, step=0.5, key="cond_ts_dp")),
            corrosion_allowance_mm=float(st.number_input("Condenser tubesheet corrosion allowance (mm)", 0.0, 6.0, 1.5, step=0.5, key="cond_ts_ca")),
        )
        st.dataframe(mechanical_screen_table(ts, vib), hide_index=True, use_container_width=True)
    else:
        st.info("Run the Condenser tab first to enable vibration and tubesheet screening.")

    st.subheader("Evaporator vibration and tubesheet screening")
    if isinstance(evap_res, dict) and evap_res:
        try:
            evap_shell_id = float(evap_res.get("shell_id_mm", evap_res.get("shell_id_mm_est", 250.0)))
            evap_tube_od = float(evap_res.get("tube_od_mm", 15.88))
            evap_tube_id = float(evap_res.get("tube_id_mm", 12.3))
            evap_baffle = float(evap_res.get("baffle_spacing_mm", 200.0))
            evap_vshell = float(evap_res.get("shell_velocity_ms", evap_res.get("water_velocity_ms", 0.8)))
            evap_vib = tube_vibration_screening(evap_tube_od, evap_tube_id, "CuNi 90/10 C70600", evap_baffle, evap_vshell, 1000.0, 25.0, service="liquid")
            evap_ts = preliminary_tubesheet_screen(evap_shell_id, evap_tube_od, float(st.number_input("Evaporator design pressure for tubesheet screen (bar g)", 1.0, 35.0, 14.0, step=0.5, key="evap_ts_dp")))
            st.dataframe(mechanical_screen_table(evap_ts, evap_vib), hide_index=True, use_container_width=True)
            if evap_vib.get("overall_status") != "OK":
                st.warning(evap_vib.get("guidance"))
        except Exception as exc:
            st.warning(f"Evaporator mechanical screening needs complete shell/tube geometry: {exc}")
    else:
        st.info("Run the Evaporator tab first to enable evaporator vibration and tubesheet screening.")

    st.subheader("Condenser nozzle sizing (TEMA rho·v² limits)")
    if isinstance(cond_res, dict) and cond_res:
        _disc_for_nozzle = None
        try:
            if isinstance(comp_res, dict) and not comp_res.get("error"):
                _disc_for_nozzle = float(comp_res.get("t_discharge_c"))
        except Exception:
            pass
        nset = condenser_nozzle_set(heat_rejection_kw, ref, cond_c,
                                    float(cond_res.get("water_flow_m3h", 10.0)),
                                    discharge_temp_c=_disc_for_nozzle)
        st.dataframe(nozzle_summary_table(nset), hide_index=True, use_container_width=True)
        st.caption("Impingement, reinforcement pads and nozzle loads remain an ASME/TEMA mechanical design task; sizes above satisfy the momentum limits only.")
    else:
        st.info("Run the Condenser tab first to enable nozzle sizing.")

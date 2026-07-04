from modules.evaporator import shell_tube_evaporator_screening, air_cooled_dx_coil_screening


def test_shell_tube_evaporator_v11_outputs():
    r = shell_tube_evaporator_screening(
        42.2, 12, 7, glycol_pct=0, evap_temp_c=5,
        water_flow_m3h_input=10.0, refrigerant="R407C", refrigerant_mass_flow_kg_s=0.22,
        max_water_dp_kpa=80, max_refrigerant_dp_kpa=80, target_superheat_k=6
    )
    for k in ["water_flow_m3h", "water_velocity_ms", "water_dp_kpa_est", "refrigerant_dp_kpa_est",
              "water_heat_capacity_rate_kw_per_k", "limiting_side", "max_heat_transfer_possible_kw_by_cmin",
              "effectiveness_based_on_cmin", "effective_evaporating_temp_after_ref_dp_c"]:
        assert k in r


def test_air_coil_v11_outputs():
    r = air_cooled_dx_coil_screening(
        42.2, 4.0, 27, 19, 5, 4, 1.2, 12,
        input_method="DB+RH", rh_pct=50, face_width_m=1.2, face_height_m=1.0,
        face_velocity_input_ms=2.0, tube_od_mm=9.52, tube_wall_mm=0.35,
        refrigerant="R407C", refrigerant_mass_flow_kg_s=0.22, condensing_temp_c=45
    )
    for k in ["air_flow_m3s", "face_width_m", "face_height_m", "tube_od_mm", "refrigerant_dp_kpa_est",
              "effective_evaporating_temp_after_ref_dp_c", "expected_issue_due_to_dp"]:
        assert k in r

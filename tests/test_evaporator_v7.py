from modules.evaporator import shell_tube_evaporator_screening, air_cooled_dx_coil_screening

def test_shell_tube_evaporator_runs():
    r = shell_tube_evaporator_screening(42.2, 12, 7, glycol_pct=0, evap_temp_c=2, tube_count=80, tube_length_m=1.2, u_w_m2k=0, refrigerant='R134a')
    assert r['capacity_possible_kw'] > 0
    assert r['calculated_Uo_w_m2k'] > 0
    assert 'refrigerant_boiling_number' in r

def test_air_coil_runs():
    r = air_cooled_dx_coil_screening(42.2, 4.0, 27, 19, 5, 4, 2.0, 12)
    assert r['capacity_possible_kw'] > 0
    assert r['air_dp_pa_est'] >= 0

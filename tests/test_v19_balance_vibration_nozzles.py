from modules.system_balance import solve_balance_point
from modules.vibration import tube_vibration_screening
from modules.nozzles import size_nozzle, condenser_nozzle_set


BASE = dict(refrigerant='R407C', compressor_type='Scroll',
            rated_cooling_kw=50, rated_evap_c=5, rated_cond_c=45,
            chw_in_c=12, chw_flow_m3h=8.6, cw_in_c=37, cw_flow_m3h=9.5)


def test_balance_point_solves_and_is_physical():
    r = solve_balance_point(evap_ua_kw_k=10.0, cond_ua_kw_k=8.0, **BASE)
    assert r['status'] in ('BALANCED', 'LIMIT')
    assert BASE['cw_in_c'] < r['balanced_condensing_temp_c'] < 70
    assert r['balanced_evaporating_temp_c'] < BASE['chw_in_c']
    # energy bookkeeping
    assert abs(r['heat_rejection_kw'] - r['actual_cooling_capacity_kw'] - r['compressor_power_kw']) < 0.5


def test_undersized_condenser_raises_tcond_and_cuts_capacity():
    ok = solve_balance_point(evap_ua_kw_k=10.0, cond_ua_kw_k=8.0, **BASE)
    small = solve_balance_point(evap_ua_kw_k=10.0, cond_ua_kw_k=3.0, **BASE)
    assert small['balanced_condensing_temp_c'] > ok['balanced_condensing_temp_c'] + 3
    assert small['actual_cooling_capacity_kw'] < ok['actual_cooling_capacity_kw']
    assert 'condenser is the bottleneck' in small['notes']


def test_vibration_screening_trends():
    base = dict(tube_od_mm=15.88, tube_id_mm=12.3, material='CuNi 90/10 C70600',
                shell_fluid_density_kg_m3=200.0, tube_side_fluid_density_kg_m3=1000.0,
                pitch_ratio=1.25, service='condensing')
    short = tube_vibration_screening(baffle_spacing_mm=150,
                                     shell_crossflow_velocity_ms=1.0, **base)
    long = tube_vibration_screening(baffle_spacing_mm=600,
                                    shell_crossflow_velocity_ms=1.0, **base)
    assert short['tube_natural_freq_hz'] > long['tube_natural_freq_hz']  # shorter span = stiffer
    fast = tube_vibration_screening(baffle_spacing_mm=600,
                                    shell_crossflow_velocity_ms=8.0, **base)
    assert fast['fei_velocity_margin'] < long['fei_velocity_margin']


def test_nozzle_vapor_impingement_limit():
    n = size_nozzle(0.32, 55.0, 'shell_vapor_in')
    assert n['rho_v2_kg_m_s2'] <= 744.0
    assert n['selected_DN'] in (15, 20, 25, 32, 40, 50, 65, 80, 100, 125, 150, 200, 250, 300)


def test_condenser_nozzle_set():
    nset = condenser_nozzle_set(63.0, 'R407C', 45.0, 9.5, discharge_temp_c=84.0)
    assert nset['refrigerant_mass_flow_kg_s'] > 0
    gas = nset['hot_gas_inlet']; liq = nset['liquid_outlet']; wat = nset['water_nozzles']
    assert gas['selected_DN'] >= liq['selected_DN']      # vapor line larger than liquid
    assert liq['velocity_ms'] <= 1.0 + 1e-6
    assert 1.0 <= wat['velocity_ms'] <= 3.0 + 1e-6

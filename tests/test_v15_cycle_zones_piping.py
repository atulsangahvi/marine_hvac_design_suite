from modules.compressor import cycle_operating_point, estimate_operating_point
from modules.condenser import evaluate_condenser, _lmtd
from modules.refrigerant_piping import line_conditions, select_line_size, copper_id_mm
from data.tube_library import filter_tubes


def test_cycle_model_derates_with_lift():
    cal = cycle_operating_point('R407C', 5, 45, compressor_type='Scroll',
                                rated_cooling_kw=50, rated_evap_c=5, rated_cond_c=45)
    assert abs(cal['cooling_kw'] - 50.0) < 0.5           # reproduces the rated point
    hot = cycle_operating_point('R407C', 5, 55, compressor_type='Scroll',
                                swept_flow_m3_s=cal['swept_flow_m3_s'])
    assert hot['cooling_kw'] < cal['cooling_kw']         # capacity falls with lift
    assert hot['power_kw'] > cal['power_kw']             # power rises with lift
    assert hot['cop'] < cal['cop']
    assert hot['discharge_temp_c'] > cal['discharge_temp_c']


def test_operating_point_balances():
    op = estimate_operating_point('R407C', 5, 45, 37, 12.0, 50, 3.2, 'Scroll')
    assert op['status'] in ('OK', 'NOT BALANCED')
    assert 'Compressor power kW' in op['operating_point']


def test_lmtd_is_order_independent():
    assert abs(_lmtd(10, 3) - _lmtd(3, 10)) < 1e-9
    assert _lmtd(10, 3) > 0


def test_condenser_three_zone_runs_and_is_conservative():
    tube = next(t for t in filter_tubes('seawater', '5/8"', 'condenser')
                if 'GEWA-CLF 5/8 x 0.80 L10' in t['name'])
    r = evaluate_condenser(53, 'seawater', 37, 42, 64, 2, 1.041, tube, 1.4,
                           condensing_temp_c=47, refrigerant='R407C',
                           discharge_temp_c=75, subcool_k=3)
    assert r['zone_model'].startswith('three-zone')
    assert r['zone_q_desuperheat_kw'] > 0
    assert abs(r['zone_q_desuperheat_kw'] + r['zone_q_condense_kw'] + r['zone_q_subcool_kw'] - 53) < 0.2
    assert r['q_possible_kw'] <= r['q_possible_single_zone_kw'] + 1e-6


def test_line_conditions_liquid_viscosity_realistic():
    lc = line_conditions('R134a', 'liquid', 5, 45)
    sc = line_conditions('R134a', 'suction', 5, 45)
    assert lc['mu'] > 5 * sc['mu']      # liquid viscosity is an order above vapor
    assert lc['rho'] > 500
    df = select_line_size(0.25, lc['rho'], 0.4, 1.5, 35, 15, mu=lc['mu'])
    assert not df.empty
    dfs = select_line_size(0.25, sc['rho'], 6, 14, 25, 15, mu=sc['mu'],
                           ref='R134a', line='suction', evap_c=5, cond_c=45)
    assert 'sat temp loss K' in dfs.columns


def test_copper_wall_table():
    assert abs(copper_id_mm(22) - (22 - 2 * 1.1)) < 1e-9
    assert abs(copper_id_mm(54) - (54 - 2 * 2.0)) < 1e-9

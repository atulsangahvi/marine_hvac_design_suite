from modules.condenser import evaluate_condenser
from data.tube_library import filter_tubes
from modules.validation_benchmarks import run_benchmarks
from modules.design_optimizer import condenser_geometry_optimizer


def test_tube_library_filters_seawater():
    tubes = filter_tubes('seawater', '5/8"', 'condenser')
    assert tubes
    assert all('seawater' in t['water_service'] for t in tubes)


def test_condenser_engine_outputs_geometry():
    tube = filter_tubes('seawater', '5/8"', 'condenser')[0]
    r = evaluate_condenser(53, 'seawater', 37, 42, 64, 2, 1.2, tube, condensing_temp_c=47, refrigerant='R407C')
    assert r['shell_id_mm'] > 0
    assert r['q_possible_kw'] > 0
    assert r['hi_w_m2k'] > 0
    assert r['ho_w_m2k'] > 0


def test_optimizer_returns_rows():
    df = condenser_geometry_optimizer(20, 'seawater', 35, 40, 45, max_shell_od_mm=500, max_length_m=1.2, max_dp_kpa=100, od_filter='5/8"')
    assert not df.empty


def test_benchmark_runs():
    df = run_benchmarks()
    assert not df.empty

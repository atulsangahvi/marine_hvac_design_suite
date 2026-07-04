"""Small offline smoke tests for the Marine Chiller Suite.
Run from project root: python tests/smoke_test.py
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from data.tube_library import filter_tubes
from modules.condenser import evaluate_condenser, auto_select_tubes
from modules.pressure_switch import calculate_pressure_switches
from modules.evaporator import shell_tube_evaporator_screening, air_cooled_dx_coil_screening, correlation_audit_table


def main():
    sea_58 = filter_tubes('seawater', '5/8"')
    assert sea_58, 'Expected seawater 5/8 tubes in Wieland library'
    r = evaluate_condenser(53, 'seawater', 37, 42, 64, 2, 1.2, sea_58[0], 2.8, 1.25, 6, condensing_temp_c=47)
    assert r['q_possible_kw'] > 0, 'Condenser capacity must be positive'
    assert r['shell_id_mm'] > r['bundle_od_mm'] > 0, 'Shell/bundle geometry must be positive and consistent'
    assert r['shell_od_mm'] > r['shell_id_mm'], 'Shell OD must exceed shell ID'
    df = auto_select_tubes(53, 'seawater', 37, 42, 64, 2, 1.2, 'All', 2.8, 1.25, 6, 47)
    assert not df.empty, 'Auto tube selection should return candidates'
    ev = shell_tube_evaporator_screening(40, 12, 7, glycol_pct=0, evap_temp_c=2, tube_count=80)
    assert ev['capacity_possible_kw'] > 0 and ev['water_flow_m3h'] > 0, 'Evaporator screening failed'
    coil = air_cooled_dx_coil_screening(20, 2.0, 27, 19, 5, 4, 1.2, 12)
    assert coil['face_velocity_ms'] > 0 and coil['air_dp_pa_est'] > 0, 'Air coil screening failed'
    assert not correlation_audit_table().empty, 'Correlation audit table must not be empty'
    ps, warns, vals = calculate_pressure_switches('R407C', 5, 47, 5, 30, 10, -2, 4, 42, 36, 48, 42)
    if ps.empty:
        assert any('CoolProp' in w for w in warns), 'Pressure switch calculation failed for an unexpected reason'
        print('Smoke tests passed without CoolProp pressure calculation.')
    else:
        assert vals['hps_cutout'] > vals['normal_condensing'], 'Pressure switch calculation failed'
        print('Smoke tests passed.')


if __name__ == '__main__':
    main()

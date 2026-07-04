from __future__ import annotations
import pandas as pd

def tema_datasheet(project_name: str, service: str, duty_kw: float, shell_id_mm: float, shell_od_mm: float, tube_count: int, tube_od_mm: float, tube_length_m: float, tube_passes: int, material: str, design_pressure_barg: float, design_temp_c: float) -> pd.DataFrame:
    rows = {
        'Project': project_name,
        'Service': service,
        'Duty kW': duty_kw,
        'TEMA type': 'BEM / AEM preliminary - verify',
        'Shell ID mm': shell_id_mm,
        'Shell OD mm': shell_od_mm,
        'Tube count': tube_count,
        'Tube OD mm': tube_od_mm,
        'Tube effective length m': tube_length_m,
        'Tube passes': tube_passes,
        'Tube material': material,
        'Design pressure bar(g)': design_pressure_barg,
        'Design temperature C': design_temp_c,
        'Corrosion allowance': 'As project/class requirement',
        'Fouling factor': 'As selected in thermal module',
        'Inspection': 'Hydrotest, leak test, material certificates, dimensional check',
    }
    return pd.DataFrame([{'Field':k,'Value':v} for k,v in rows.items()])

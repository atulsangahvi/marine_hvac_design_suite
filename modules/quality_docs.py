from __future__ import annotations
import pandas as pd

def manufacturing_document_register() -> pd.DataFrame:
    rows=[
        ('GA drawing','Required','Shell/tube exchanger and package base frame'),
        ('P&ID','Required','Refrigerant, seawater, chilled water and safety reliefs'),
        ('Electrical schematic','Required','Power, control, terminal schedule and wire numbers'),
        ('TEMA datasheet','Required','Mechanical/thermal datasheet for exchanger fabrication'),
        ('Material certificates','Required','EN 10204 3.1 for tubes, shell, tubesheets'),
        ('WPS/PQR/Welder qualification','Required','For pressure retaining welds'),
        ('NDE records','Required','As per code and class requirement'),
        ('Hydrotest/pneumatic test','Required','Pressure vessel testing and leak test'),
        ('Performance test report','Recommended','Water flow, ΔT, pressure drop, amps, pressures'),
        ('O&M manual','Required','Startup, shutdown, maintenance and troubleshooting'),
    ]
    return pd.DataFrame(rows, columns=['Document','Status','Notes'])

def commissioning_checklist() -> pd.DataFrame:
    rows=[
        ('Pre-start','Verify electrical insulation, phase sequence, oil level, crankcase heater'),
        ('Water flow','Verify chilled water and condenser water flow switches prove correctly'),
        ('Leak test','Nitrogen pressure test, standing pressure and vacuum decay'),
        ('Charge','Charge refrigerant by weight and confirm sight glass/subcooling'),
        ('Controls','Verify HP/LP/CPS/freeze/flow/overload trips'),
        ('EEV/TXV','Set superheat and confirm stable operation at low and high load'),
        ('Performance','Record capacity, COP, water ΔT, pressures and discharge temperature'),
    ]
    return pd.DataFrame(rows, columns=['Stage','Checklist'])

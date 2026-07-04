from __future__ import annotations
import pandas as pd

def marine_compliance_checks(refrigerant: str, location: str, seawater: bool, pressure_vessel: bool, electrical_panel_location: str, atex_required: bool=False) -> pd.DataFrame:
    rows=[]
    def add(item,status,note,ref): rows.append({'Check':item,'Status':status,'Guidance':note,'Reference basis':ref})
    add('Pressure vessel code','REQUIRED' if pressure_vessel else 'N/A','Shell, receiver, oil separator and accumulators require code design, hydrotest and nameplate.','ASME VIII / EN 13445 / class rule')
    add('Marine class approval','CHECK','Confirm ABS/DNV/LR/BV/IRS project requirements before procurement.','Class society rules')
    add('Seawater materials','OK' if seawater else 'N/A','Use titanium, CuNi 90/10, CuNi 70/30 or approved material; avoid plain copper/carbon steel for direct seawater.','Marine condenser practice')
    add('Refrigerant machinery space','CHECK','Provide ventilation, leak detection and relief discharge routing as required.','ASHRAE 15 / EN 378 / class rule')
    add('ATEX/hazardous area','REQUIRED' if atex_required else 'CHECK','If installed in hazardous zone, motors/switches/panel/instruments must match zone classification.','IECEx/ATEX/project HAZAREA')
    add('Electrical enclosure','OK' if electrical_panel_location!='Outdoor exposed' else 'CHECK','Outdoor/marine panels normally need IP55/IP65 plus anti-condensation heater.','IEC 60529 / marine practice')
    return pd.DataFrame(rows)

"""Starter compressor library schema for Milestone 2.

The app can already accept manual/map inputs. This file defines the structure for
future manufacturer compressor records and interpolation maps.
"""
from __future__ import annotations
import pandas as pd

COMPRESSOR_LIBRARY = [
    {"manufacturer":"Bitzer","type":"Screw","model":"Example CSVH/CSH placeholder","refrigerants":["R134a","R407C","R513A"],"capacity_control":["slide_valve","VFD"],"notes":"Replace with verified manufacturer map points before selection."},
    {"manufacturer":"Copeland","type":"Scroll","model":"Example ZR/ZP placeholder","refrigerants":["R407C","R410A","R134a"],"capacity_control":["fixed_speed","digital_scroll"],"notes":"Replace with verified manufacturer map points before selection."},
    {"manufacturer":"Danfoss","type":"Scroll/Screw","model":"Example placeholder","refrigerants":["R134a","R513A","R410A"],"capacity_control":["fixed_speed","VFD"],"notes":"Replace with verified manufacturer map points before selection."},
]

def compressor_library_df() -> pd.DataFrame:
    return pd.DataFrame(COMPRESSOR_LIBRARY)

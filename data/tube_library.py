"""Tube library for Marine Chiller Suite v8.

Milestone 2 database layer. The library stores geometry, material and service
suitability. Heat-transfer performance is calculated by the engineering engine;
manufacturer catalogue data is used for dimensions, mass and application filters.
"""
from __future__ import annotations
from .materials import service_suitable

# Plain/smooth commercial tubes
PLAIN_TUBES = [
    {"manufacturer":"Generic","family":"Plain smooth","name":"Plain smooth 3/8 in Cu","material":"Copper Cu-DHP","od_mm":9.52,"id_mm":7.62,"wall_under_fin_mm":0.95,"plain_wall_mm":0.95,"fin_od_mm":9.52,"root_od_mm":9.52,"kg_m":0.22,"water_service":["plain_water"],"application":["condenser","dx_evaporator"]},
    {"manufacturer":"Generic","family":"Plain smooth","name":"Plain smooth 1/2 in CuNi 90/10","material":"CuNi 90/10 C70600","od_mm":12.70,"id_mm":10.70,"wall_under_fin_mm":1.00,"plain_wall_mm":1.00,"fin_od_mm":12.70,"root_od_mm":12.70,"kg_m":0.30,"water_service":["plain_water","seawater"],"application":["condenser","dx_evaporator"]},
    {"manufacturer":"Generic","family":"Plain smooth","name":"Plain smooth 5/8 in CuNi 90/10","material":"CuNi 90/10 C70600","od_mm":15.88,"id_mm":13.88,"wall_under_fin_mm":1.00,"plain_wall_mm":1.00,"fin_od_mm":15.88,"root_od_mm":15.88,"kg_m":0.42,"water_service":["plain_water","seawater"],"application":["condenser","dx_evaporator"]},
    {"manufacturer":"Generic","family":"Plain smooth","name":"Plain smooth 3/4 in CuNi 90/10","material":"CuNi 90/10 C70600","od_mm":19.05,"id_mm":16.85,"wall_under_fin_mm":1.10,"plain_wall_mm":1.10,"fin_od_mm":19.05,"root_od_mm":19.05,"kg_m":0.55,"water_service":["plain_water","seawater"],"application":["condenser","dx_evaporator"]},
    {"manufacturer":"Generic","family":"Plain smooth","name":"Plain smooth 5/8 in Titanium","material":"Titanium","od_mm":15.88,"id_mm":13.88,"wall_under_fin_mm":1.00,"plain_wall_mm":1.00,"fin_od_mm":15.88,"root_od_mm":15.88,"kg_m":0.21,"water_service":["plain_water","seawater"],"application":["condenser","dx_evaporator"]},
    {"manufacturer":"Generic","family":"Plain smooth","name":"Plain smooth 3/4 in Titanium","material":"Titanium","od_mm":19.05,"id_mm":16.85,"wall_under_fin_mm":1.10,"plain_wall_mm":1.10,"fin_od_mm":19.05,"root_od_mm":19.05,"kg_m":0.28,"water_service":["plain_water","seawater"],"application":["condenser","dx_evaporator"]},
]

# Wieland GEWA-C/CLF condenser tube entries. Dimensions are catalogue-style fields.
# v14: "id_enhancement" is the tube-side HTC ratio vs a plain bore at equal Re for
# the internal helix/rib geometry of GEWA-C/CLF tubes (typical published range
# 1.7-2.2x). 1.9 is an engineering estimate and MUST be confirmed against the
# supplier datasheet for the exact tube before manufacture. "fpi"/"fin_thickness_mm"
# feed the Beatty-Katz outside condensation model; values are typical for the family.
WIELAND_GEWA_C = [
    {"manufacturer":"Wieland","family":"GEWA-C6H","name":"GEWA-C6H 3/4 x 0.63 K21","material_code":"K21","material":"Copper Cu-DHP","od_mm":19.00,"plain_wall_mm":1.12,"fin_od_mm":18.85,"root_od_mm":16.95,"wall_under_fin_mm":0.63,"id_mm":15.69,"kg_m":0.470,"water_service":["plain_water"],"application":["condenser"],"enhanced_surface":"GEWA-C","fpi":26,"fin_thickness_mm":0.30,"id_enhancement":1.9},
    {"manufacturer":"Wieland","family":"GEWA-C5H","name":"GEWA-C5H 3/4 x 0.63 K21","material_code":"K21","material":"Copper Cu-DHP","od_mm":19.00,"plain_wall_mm":1.10,"fin_od_mm":18.85,"root_od_mm":16.95,"wall_under_fin_mm":0.63,"id_mm":15.69,"kg_m":0.487,"water_service":["plain_water"],"application":["condenser"],"enhanced_surface":"GEWA-C","fpi":26,"fin_thickness_mm":0.30,"id_enhancement":1.9},
    {"manufacturer":"Wieland","family":"GEWA-C5H","name":"GEWA-C5H 3/4 x 0.71 K21","material_code":"K21","material":"Copper Cu-DHP","od_mm":19.00,"plain_wall_mm":1.20,"fin_od_mm":18.85,"root_od_mm":16.95,"wall_under_fin_mm":0.71,"id_mm":15.53,"kg_m":0.516,"water_service":["plain_water"],"application":["condenser"],"enhanced_surface":"GEWA-C","fpi":26,"fin_thickness_mm":0.30,"id_enhancement":1.9},
    {"manufacturer":"Wieland","family":"GEWA-C5H","name":"GEWA-C5H 1 x 0.63 K21","material_code":"K21","material":"Copper Cu-DHP","od_mm":25.45,"plain_wall_mm":1.16,"fin_od_mm":25.25,"root_od_mm":23.35,"wall_under_fin_mm":0.63,"id_mm":22.09,"kg_m":0.687,"water_service":["plain_water"],"application":["condenser"],"enhanced_surface":"GEWA-C","fpi":26,"fin_thickness_mm":0.30,"id_enhancement":1.9},
    {"manufacturer":"Wieland","family":"GEWA-CLF","name":"GEWA-CLF 5/8 x 0.63 K21","material_code":"K21","material":"Copper Cu-DHP","od_mm":15.88,"plain_wall_mm":1.17,"fin_od_mm":15.80,"root_od_mm":13.90,"wall_under_fin_mm":0.63,"id_mm":12.64,"kg_m":0.435,"water_service":["plain_water"],"application":["condenser"],"enhanced_surface":"GEWA-CLF","fpi":26,"fin_thickness_mm":0.30,"id_enhancement":1.9},
    {"manufacturer":"Wieland","family":"GEWA-CLF","name":"GEWA-CLF 5/8 x 0.63 L10","material_code":"L10","material":"CuNi 90/10 C70600","od_mm":15.88,"plain_wall_mm":1.17,"fin_od_mm":15.80,"root_od_mm":13.90,"wall_under_fin_mm":0.63,"id_mm":12.64,"kg_m":0.435,"water_service":["plain_water","seawater"],"application":["condenser"],"enhanced_surface":"GEWA-CLF","fpi":26,"fin_thickness_mm":0.30,"id_enhancement":1.9},
    {"manufacturer":"Wieland","family":"GEWA-CLF","name":"GEWA-CLF 5/8 x 0.80 K21","material_code":"K21","material":"Copper Cu-DHP","od_mm":15.88,"plain_wall_mm":1.40,"fin_od_mm":15.80,"root_od_mm":13.90,"wall_under_fin_mm":0.80,"id_mm":12.30,"kg_m":0.505,"water_service":["plain_water"],"application":["condenser"],"enhanced_surface":"GEWA-CLF","fpi":26,"fin_thickness_mm":0.30,"id_enhancement":1.9},
    {"manufacturer":"Wieland","family":"GEWA-CLF","name":"GEWA-CLF 5/8 x 0.80 L10","material_code":"L10","material":"CuNi 90/10 C70600","od_mm":15.88,"plain_wall_mm":1.40,"fin_od_mm":15.80,"root_od_mm":13.90,"wall_under_fin_mm":0.80,"id_mm":12.30,"kg_m":0.505,"water_service":["plain_water","seawater"],"application":["condenser"],"enhanced_surface":"GEWA-CLF","fpi":26,"fin_thickness_mm":0.30,"id_enhancement":1.9},
    {"manufacturer":"Wieland","family":"GEWA-CLF","name":"GEWA-CLF 3/4 x 0.71 K21","material_code":"K21","material":"Copper Cu-DHP","od_mm":19.00,"plain_wall_mm":1.30,"fin_od_mm":18.85,"root_od_mm":16.95,"wall_under_fin_mm":0.71,"id_mm":15.53,"kg_m":0.591,"water_service":["plain_water"],"application":["condenser"],"enhanced_surface":"GEWA-CLF","fpi":26,"fin_thickness_mm":0.30,"id_enhancement":1.9},
    {"manufacturer":"Wieland","family":"GEWA-CLF","name":"GEWA-CLF 3/4 x 0.71 L10","material_code":"L10","material":"CuNi 90/10 C70600","od_mm":19.00,"plain_wall_mm":1.35,"fin_od_mm":18.85,"root_od_mm":16.95,"wall_under_fin_mm":0.71,"id_mm":15.53,"kg_m":0.591,"water_service":["plain_water","seawater"],"application":["condenser"],"enhanced_surface":"GEWA-CLF","fpi":26,"fin_thickness_mm":0.30,"id_enhancement":1.9},
    {"manufacturer":"Wieland","family":"GEWA-CLF","name":"GEWA-CLF 3/4 x 0.71 L30","material_code":"L30","material":"CuNi 70/30 C71500","od_mm":19.00,"plain_wall_mm":1.35,"fin_od_mm":18.85,"root_od_mm":16.95,"wall_under_fin_mm":0.71,"id_mm":15.53,"kg_m":0.591,"water_service":["plain_water","seawater"],"application":["condenser"],"enhanced_surface":"GEWA-CLF","fpi":26,"fin_thickness_mm":0.30,"id_enhancement":1.9},
    {"manufacturer":"Wieland","family":"GEWA-CLF","name":"GEWA-CLF 3/4 x 0.90 L10","material_code":"L10","material":"CuNi 90/10 C70600","od_mm":19.00,"plain_wall_mm":1.55,"fin_od_mm":18.85,"root_od_mm":16.95,"wall_under_fin_mm":0.90,"id_mm":15.15,"kg_m":0.660,"water_service":["plain_water","seawater"],"application":["condenser"],"enhanced_surface":"GEWA-CLF","fpi":26,"fin_thickness_mm":0.30,"id_enhancement":1.9},
    {"manufacturer":"Wieland","family":"GEWA-CLF","name":"GEWA-CLF 3/4 x 0.90 S76","material_code":"S76","material":"Aluminum Brass S76","od_mm":19.00,"plain_wall_mm":1.55,"fin_od_mm":18.85,"root_od_mm":16.95,"wall_under_fin_mm":0.90,"id_mm":15.15,"kg_m":0.620,"water_service":["plain_water","seawater"],"application":["condenser"],"enhanced_surface":"GEWA-CLF","fpi":26,"fin_thickness_mm":0.30,"id_enhancement":1.9},
    {"manufacturer":"Wieland","family":"GEWA-CLF","name":"GEWA-CLF 1 x 0.89 L10","material_code":"L10","material":"CuNi 90/10 C70600","od_mm":25.45,"plain_wall_mm":1.65,"fin_od_mm":25.25,"root_od_mm":23.35,"wall_under_fin_mm":0.89,"id_mm":21.57,"kg_m":0.930,"water_service":["plain_water","seawater"],"application":["condenser"],"enhanced_surface":"GEWA-CLF","fpi":26,"fin_thickness_mm":0.30,"id_enhancement":1.9},
    {"manufacturer":"Wieland","family":"GEWA-CPL","name":"GEWA-CPL 3/4 x 0.90 K21","material_code":"K21","material":"Copper Cu-DHP","od_mm":19.00,"plain_wall_mm":1.55,"fin_od_mm":18.85,"root_od_mm":16.95,"wall_under_fin_mm":0.90,"id_mm":15.15,"kg_m":0.660,"water_service":["plain_water"],"application":["condenser"],"enhanced_surface":"GEWA-CPL","fpi":26,"fin_thickness_mm":0.30,"id_enhancement":1.0},
    {"manufacturer":"Wieland","family":"GEWA-CPL","name":"GEWA-CPL 3/4 x 0.90 L10","material_code":"L10","material":"CuNi 90/10 C70600","od_mm":19.00,"plain_wall_mm":1.55,"fin_od_mm":18.85,"root_od_mm":16.95,"wall_under_fin_mm":0.90,"id_mm":15.15,"kg_m":0.660,"water_service":["plain_water","seawater"],"application":["condenser"],"enhanced_surface":"GEWA-CPL","fpi":26,"fin_thickness_mm":0.30,"id_enhancement":1.0},
]

DATANG_LOW_FIN = [
    {"manufacturer":"Datang","family":"Integral low-fin","name":"Datang low-fin 5/8 in CuNi 90/10 26 FPI","material":"CuNi 90/10 C70600","od_mm":15.88,"fin_od_mm":15.88,"root_od_mm":13.80,"id_mm":12.20,"plain_wall_mm":1.40,"wall_under_fin_mm":0.80,"kg_m":0.50,"fpi":26,"fin_thickness_mm":0.25,"water_service":["plain_water","seawater"],"application":["condenser"],"enhanced_surface":"low-fin"},
    {"manufacturer":"Datang","family":"Integral low-fin","name":"Datang low-fin 3/4 in CuNi 90/10 26 FPI","material":"CuNi 90/10 C70600","od_mm":19.05,"fin_od_mm":19.05,"root_od_mm":16.90,"id_mm":15.20,"plain_wall_mm":1.50,"wall_under_fin_mm":0.85,"kg_m":0.66,"fpi":26,"fin_thickness_mm":0.25,"water_service":["plain_water","seawater"],"application":["condenser"],"enhanced_surface":"low-fin"},
    {"manufacturer":"Datang","family":"Integral low-fin","name":"Datang low-fin 3/4 in Titanium 26 FPI","material":"Titanium","od_mm":19.05,"fin_od_mm":19.05,"root_od_mm":16.90,"id_mm":15.20,"plain_wall_mm":1.50,"wall_under_fin_mm":0.85,"kg_m":0.34,"fpi":26,"fin_thickness_mm":0.25,"water_service":["plain_water","seawater"],"application":["condenser"],"enhanced_surface":"low-fin"},
]

EVAPORATOR_TUBES = [
    {"manufacturer":"Generic","family":"Enhanced evaporator","name":"Generic Turbo-B/GEWA-B style 5/8 in Cu","material":"Copper Cu-DHP","od_mm":15.88,"id_mm":12.70,"fin_od_mm":15.88,"root_od_mm":13.5,"plain_wall_mm":1.00,"wall_under_fin_mm":0.80,"kg_m":0.48,"water_service":["plain_water"],"application":["flooded_evaporator"],"boiling_enhancement":2.0},
    {"manufacturer":"Generic","family":"DX microfin","name":"Generic internal microfin 1/2 in Cu","material":"Copper Cu-DHP","od_mm":12.70,"id_mm":10.70,"fin_od_mm":12.70,"root_od_mm":12.70,"plain_wall_mm":1.00,"wall_under_fin_mm":1.00,"kg_m":0.30,"water_service":["plain_water"],"application":["dx_evaporator"],"internal_enhancement":1.35},
]

ALL_TUBES = PLAIN_TUBES + WIELAND_GEWA_C + DATANG_LOW_FIN + EVAPORATOR_TUBES


def od_label(od_mm: float) -> str:
    if abs(od_mm-9.52) < 0.4: return '3/8"'
    if abs(od_mm-12.70) < 0.4: return '1/2"'
    if abs(od_mm-15.88) < 0.4: return '5/8"'
    if abs(od_mm-19.05) < 0.6 or abs(od_mm-19.00) < 0.6: return '3/4"'
    if abs(od_mm-25.4) < 0.8: return '1"'
    return f"{od_mm:.1f} mm"


def filter_tubes(water_type: str = "seawater", od_filter: str = "All", application: str = "condenser", manufacturer: str = "All") -> list[dict]:
    water_key = "seawater" if "sea" in (water_type or "").lower() else "plain_water"
    out = []
    for t in ALL_TUBES:
        if application and application not in t.get("application", []):
            continue
        if water_key not in t.get("water_service", []):
            continue
        if not service_suitable(t.get("material",""), water_key):
            continue
        if manufacturer != "All" and t.get("manufacturer") != manufacturer:
            continue
        if od_filter != "All" and od_label(float(t["od_mm"])) != od_filter:
            continue
        out.append(dict(t))
    return out


def tube_dataframe(water_type: str = "seawater", application: str = "condenser"):
    import pandas as pd
    return pd.DataFrame(filter_tubes(water_type, "All", application))

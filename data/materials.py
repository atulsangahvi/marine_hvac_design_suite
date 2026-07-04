"""Material and fluid service database for Marine Chiller Suite v8.

Values are preliminary engineering defaults. They are intended to guide selection,
not replace project-specific material review, corrosion study, class approval or
supplier confirmation.
"""
from __future__ import annotations

MATERIALS = {
    "Copper Cu-DHP": {
        "code": "K21", "k_w_mk": 385.0, "density_kg_m3": 8940.0,
        "service": ["plain_water", "closed_loop_water"],
        "seawater_ok": False, "velocity_plain_ms": (0.6, 1.8), "velocity_sea_ms": None,
        "note": "Good for clean fresh/closed water; avoid direct seawater service."
    },
    "CuNi 90/10 C70600": {
        "code": "L10", "k_w_mk": 50.0, "density_kg_m3": 8900.0,
        "service": ["plain_water", "closed_loop_water", "seawater"],
        "seawater_ok": True, "velocity_plain_ms": (0.8, 2.5), "velocity_sea_ms": (1.0, 2.5),
        "note": "Common economical seawater tube material; check pollution, sulphides and erosion."
    },
    "CuNi 70/30 C71500": {
        "code": "L30", "k_w_mk": 29.0, "density_kg_m3": 8950.0,
        "service": ["plain_water", "closed_loop_water", "seawater"],
        "seawater_ok": True, "velocity_plain_ms": (0.8, 3.0), "velocity_sea_ms": (1.0, 3.0),
        "note": "Better erosion/corrosion margin than 90/10 CuNi for severe seawater."
    },
    "Aluminum Brass S76": {
        "code": "S76", "k_w_mk": 110.0, "density_kg_m3": 8300.0,
        "service": ["plain_water", "seawater"],
        "seawater_ok": True, "velocity_plain_ms": (0.8, 2.2), "velocity_sea_ms": (1.0, 2.2),
        "note": "Historically used in seawater but sensitive to polluted/ammoniacal water; verify."
    },
    "Titanium": {
        "code": "Ti", "k_w_mk": 17.0, "density_kg_m3": 4500.0,
        "service": ["plain_water", "closed_loop_water", "seawater", "brine"],
        "seawater_ok": True, "velocity_plain_ms": (0.8, 3.5), "velocity_sea_ms": (1.0, 3.5),
        "note": "Premium seawater choice; excellent chloride resistance; verify tube-to-tubesheet details."
    },
    "Carbon Steel": {
        "code": "CS", "k_w_mk": 45.0, "density_kg_m3": 7850.0,
        "service": ["plain_water", "closed_loop_water"],
        "seawater_ok": False, "velocity_plain_ms": (0.6, 1.5), "velocity_sea_ms": None,
        "note": "Not recommended for direct seawater tubes."
    },
    "Stainless Steel 316L": {
        "code": "316L", "k_w_mk": 15.0, "density_kg_m3": 8000.0,
        "service": ["plain_water", "closed_loop_water", "brine"],
        "seawater_ok": False, "velocity_plain_ms": (0.8, 2.5), "velocity_sea_ms": None,
        "note": "Avoid stagnant chloride seawater unless corrosion review approves."
    },
}


def material_k(material: str) -> float:
    return MATERIALS.get(material, {}).get("k_w_mk", 45.0)


def material_density(material: str) -> float:
    return MATERIALS.get(material, {}).get("density_kg_m3", 7850.0)


def velocity_limits(material: str, water_type: str) -> tuple[float, float]:
    m = MATERIALS.get(material, {})
    key = "velocity_sea_ms" if "sea" in (water_type or "").lower() else "velocity_plain_ms"
    return m.get(key) or m.get("velocity_plain_ms") or (0.8, 2.5)


def service_suitable(material: str, water_type: str) -> bool:
    water_key = "seawater" if "sea" in (water_type or "").lower() else "plain_water"
    return water_key in MATERIALS.get(material, {}).get("service", [])

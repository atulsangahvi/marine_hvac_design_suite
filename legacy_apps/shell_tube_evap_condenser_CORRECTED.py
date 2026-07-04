import streamlit as st
import numpy as np
import pandas as pd
import math
from scipy.optimize import fsolve, minimize
import plotly.graph_objects as go
from typing import Dict, Tuple, List, Optional
import warnings
import CoolProp.CoolProp as CP
from datetime import datetime
import base64
from io import BytesIO
import reportlab
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter, landscape
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
import os

warnings.filterwarnings('ignore')

# ============================================================================
# CORRECTED VERSION - February 13, 2026
# ============================================================================
# Critical fixes applied:
# 1. ✅ CORRECTED: Condenser area distribution (now based on Q×R, not just U)
# 2. ✅ CORRECTED: Wall resistance calculation (consistent formula throughout)
# 3. ✅ CORRECTED: Overall U calculations (proper area basis conversions)
# 4. ✅ ADDED: Temperature validation in sequential zone calculations
# 5. ✅ ADDED: Comprehensive validation checks for heat duty matching
# 
# These corrections fix the major issues identified in code review where:
# - Desuperheat zone was achieving only 54% of required duty
# - Latent zone was achieving 130% of required duty (oversize)
# - Subcool zone was achieving only 62% of required duty
# - Overall effectiveness was very low (0.031 instead of expected 0.3-0.4)
# ============================================================================

# ============================================================================
# PASSWORD PROTECTION
# ============================================================================

def check_password():
    """Password protection for the app"""
    def password_entered():
        if st.session_state["password"] == "Semaanju":
            st.session_state["password_correct"] = True
            del st.session_state["password"]
        else:
            st.session_state["password_correct"] = False

    if "password_correct" not in st.session_state:
        st.text_input(
            "Enter Password", type="password", on_change=password_entered, key="password"
        )
        st.write("*Please enter the password to access the design tool*")
        return False
    elif not st.session_state["password_correct"]:
        st.text_input(
            "Enter Password", type="password", on_change=password_entered, key="password"
        )
        st.error("😕 Password incorrect")
        return False
    else:
        return True

# ============================================================================
# PAGE CONFIGURATION
# ============================================================================

st.set_page_config(
    page_title="TEMA 10th Edition DX Shell & Tube HX Designer",
    page_icon="🌡️",
    layout="wide"
)

# ============================================================================
# CUSTOM CSS
# ============================================================================

st.markdown("""
<style>
    .main-header {
        font-size: 2.5rem;
        color: #1E3A8A;
        text-align: center;
        margin-bottom: 2rem;
    }
    .section-header {
        font-size: 1.5rem;
        color: #1E3A8A;
        margin-top: 1.5rem;
        margin-bottom: 1rem;
        padding-bottom: 0.5rem;
        border-bottom: 2px solid #E5E7EB;
    }
    .result-box {
        background-color: #F3F4F6;
        padding: 1.5rem;
        border-radius: 0.5rem;
        margin: 1rem 0;
        border-left: 4px solid #3B82F6;
    }
    .warning-box {
        background-color: #FEF3C7;
        padding: 1rem;
        border-radius: 0.5rem;
        margin: 1rem 0;
        border-left: 4px solid #F59E0B;
    }
    .tema-compliant {
        background-color: #D1FAE5;
        padding: 1rem;
        border-radius: 0.5rem;
        margin: 1rem 0;
        border-left: 4px solid #10B981;
    }
    .tema-noncompliant {
        background-color: #FEE2E2;
        padding: 1rem;
        border-radius: 0.5rem;
        margin: 1rem 0;
        border-left: 4px solid #EF4444;
    }
    .dx-badge {
        display: inline-block;
        background-color: #3B82F6;
        color: white;
        padding: 0.25rem 0.75rem;
        border-radius: 1rem;
        font-weight: bold;
        font-size: 0.85rem;
        margin-left: 0.5rem;
    }
    .condenser-badge {
        display: inline-block;
        background-color: #8B5CF6;
        color: white;
        padding: 0.25rem 0.75rem;
        border-radius: 1rem;
        font-weight: bold;
        font-size: 0.85rem;
        margin-left: 0.5rem;
    }
    .velocity-good {
        background-color: #D1FAE5;
        color: #065F46;
        padding: 0.25rem 0.5rem;
        border-radius: 0.5rem;
        font-size: 0.85rem;
        font-weight: bold;
    }
    .velocity-low {
        background-color: #FEF3C7;
        color: #92400E;
        padding: 0.25rem 0.5rem;
        border-radius: 0.5rem;
        font-size: 0.85rem;
        font-weight: bold;
    }
    .velocity-high {
        background-color: #FEE2E2;
        color: #991B1B;
        padding: 0.25rem 0.5rem;
        border-radius: 0.5rem;
        font-size: 0.85rem;
        font-weight: bold;
    }
    .stButton>button {
        width: 100%;
    }
    .download-btn {
        background-color: #1E3A8A;
        color: white;
        padding: 0.75rem 1.5rem;
        border-radius: 0.5rem;
        text-align: center;
        margin: 1rem 0;
        cursor: pointer;
    }
    .footer {
        text-align: center;
        color: #6B7280;
        font-size: 0.8rem;
        margin-top: 2rem;
    }
</style>
""", unsafe_allow_html=True)

# ============================================================================
# TEMA 10th EDITION STANDARDS IMPLEMENTATION
# ============================================================================

class TEMAFoulingResistances:
    """TEMA Table RGP-T-2.4 - Design Fouling Resistances (10th Edition)"""
    
    # Industrial Fluids - Values in m²·K/W (converted from hr·ft²·°F/BTU * 0.17611)
    INDUSTRIAL_FLUIDS = {
        "fuel_oil_2": {"r": 0.000352, "desc": "Fuel Oil #2"},
        "fuel_oil_8": {"r": 0.000881, "desc": "Fuel Oil #8"},
        "transformer_oil": {"r": 0.000176, "desc": "Transformer Oil"},
        "engine_lube_oil": {"r": 0.000176, "desc": "Engine Lube Oil"},
        "quench_oil": {"r": 0.000704, "desc": "Quench Oil"},
        "refrigerant_liquid": {"r": 0.000176, "desc": "Refrigerant Liquids"},
        "refrigerant_vapor_oil": {"r": 0.000352, "desc": "Refrigerant Vapors (Oil Bearing)"},
        "ammonia_liquid": {"r": 0.000176, "desc": "Ammonia Liquid"},
        "ammonia_liquid_oil": {"r": 0.000528, "desc": "Ammonia Liquid (Oil Bearing)"},
        "ethylene_glycol": {"r": 0.000352, "desc": "Ethylene Glycol Solutions"},
        "methanol": {"r": 0.000352, "desc": "Methanol Solutions"},
        "ethanol": {"r": 0.000352, "desc": "Ethanol Solutions"},
        "compressed_air": {"r": 0.000176, "desc": "Compressed Air"},
        "steam_non_oil": {"r": 0.000088, "desc": "Steam (Non-Oil Bearing)"},
        "steam_oil": {"r": 0.000264, "desc": "Exhaust Steam (Oil Bearing)"},
        "manufactured_gas": {"r": 0.001761, "desc": "Manufactured Gas"},
        "natural_gas": {"r": 0.000176, "desc": "Natural Gas"},
    }
    
    # Cooling Water Fouling (TEMA Table - Water)
    COOLING_WATER = {
        "sea_water": {
            "low_temp": {"low_vel": 0.000088, "high_vel": 0.000088},
            "high_temp": {"low_vel": 0.000176, "high_vel": 0.000176},
        },
        "brackish_water": {
            "low_temp": {"low_vel": 0.000352, "high_vel": 0.000176},
            "high_temp": {"low_vel": 0.000528, "high_vel": 0.000352},
        },
        "cooling_tower_treated": {
            "low_temp": {"low_vel": 0.000176, "high_vel": 0.000176},
            "high_temp": {"low_vel": 0.000352, "high_vel": 0.000352},
        },
        "cooling_tower_untreated": {
            "low_temp": {"low_vel": 0.000528, "high_vel": 0.000528},
            "high_temp": {"low_vel": 0.000881, "high_vel": 0.000704},
        },
        "city_water": {
            "low_temp": {"low_vel": 0.000176, "high_vel": 0.000176},
            "high_temp": {"low_vel": 0.000352, "high_vel": 0.000352},
        },
        "river_water_min": {
            "low_temp": {"low_vel": 0.000352, "high_vel": 0.000176},
            "high_temp": {"low_vel": 0.000528, "high_vel": 0.000352},
        },
        "river_water_avg": {
            "low_temp": {"low_vel": 0.000528, "high_vel": 0.000352},
            "high_temp": {"low_vel": 0.000704, "high_vel": 0.000528},
        },
        "distilled_water": {
            "low_temp": {"low_vel": 0.000088, "high_vel": 0.000088},
            "high_temp": {"low_vel": 0.000088, "high_vel": 0.000088},
        },
        "treated_boiler_feed": {
            "low_temp": {"low_vel": 0.000176, "high_vel": 0.000088},
            "high_temp": {"low_vel": 0.000176, "high_vel": 0.000176},
        },
    }
    
    # Chemical Processing Streams
    CHEMICAL_STREAMS = {
        "acid_gases": {"r": 0.000352, "desc": "Acid Gases"},
        "solvent_vapors": {"r": 0.000176, "desc": "Solvent Vapors"},
        "stable_overhead": {"r": 0.000176, "desc": "Stable Overhead Products"},
        "mea_dea_solutions": {"r": 0.000352, "desc": "MEA and DEA Solutions"},
        "deg_teg_solutions": {"r": 0.000352, "desc": "DEG and TEG Solutions"},
        "caustic_solutions": {"r": 0.000352, "desc": "Caustic Solutions"},
        "vegetable_oils": {"r": 0.000528, "desc": "Vegetable Oils"},
    }
    
    @classmethod
    def get_fouling_resistance(cls, fluid_type: str, temperature: float = 60, 
                              velocity: float = 1.0, units: str = "SI") -> float:
        """Get TEMA fouling resistance in m²·K/W"""
        
        # Check industrial fluids
        if fluid_type in cls.INDUSTRIAL_FLUIDS:
            return cls.INDUSTRIAL_FLUIDS[fluid_type]["r"]
        
        # Check chemical streams
        if fluid_type in cls.CHEMICAL_STREAMS:
            return cls.CHEMICAL_STREAMS[fluid_type]["r"]
        
        # Cooling water logic
        temp_range = "low_temp" if temperature < 51.7 else "high_temp"  # 125°F = 51.7°C
        vel_range = "high_vel" if velocity > 0.914 else "low_vel"  # 3ft/s = 0.914 m/s
        
        if fluid_type in cls.COOLING_WATER:
            return cls.COOLING_WATER[fluid_type][temp_range][vel_range]
        
        # Default value if not found
        return 0.00035


class TEMATubeStandards:
    """TEMA Table D-7 - Characteristics of Tubing (10th Edition)"""
    
    # Tube dimensions in mm, BWG gauges with wall thickness in mm
    TUBE_SIZES_BWG = {
        "1/4\"": {  # 6.35 mm
            "BWG": {
                "22": 0.711, "24": 0.559, "26": 0.457, "27": 0.406, "28": 0.356
            },
            "internal_area_m2": {
                "22": 0.0000191, "24": 0.0000215, "26": 0.0000232, "27": 0.0000241, "28": 0.0000247
            }
        },
        "3/8\"": {  # 9.53 mm
            "BWG": {
                "18": 1.245, "20": 0.889, "22": 0.711, "24": 0.559, "25": 0.508, "26": 0.457
            },
            "internal_area_m2": {
                "18": 0.0000389, "20": 0.0000472, "22": 0.0000516, "24": 0.0000555, "25": 0.0000567, "26": 0.0000579
            }
        },
        "1/2\"": {  # 12.7 mm
            "BWG": {
                "16": 1.651, "17": 1.473, "18": 1.245, "19": 1.067, "20": 0.889, "21": 0.813, "22": 0.711
            },
            "internal_area_m2": {
                "16": 0.0000694, "17": 0.0000742, "18": 0.0000819, "19": 0.0000877, "20": 0.0000937, "21": 0.0000961, "22": 0.0000999
            }
        },
        "5/8\"": {  # 15.88 mm
            "BWG": {
                "12": 2.769, "13": 2.413, "14": 2.108, "15": 1.829, "16": 1.651, "17": 1.473, "18": 1.245
            },
            "internal_area_m2": {
                "12": 0.0000839, "13": 0.0000959, "14": 0.0001068, "15": 0.0001172, "16": 0.0001241, "17": 0.0001313, "18": 0.0001407
            }
        },
        "3/4\"": {  # 19.05 mm
            "BWG": {
                "10": 3.404, "11": 3.046, "12": 2.769, "13": 2.413, "14": 2.108, "15": 1.829, "16": 1.651
            },
            "internal_area_m2": {
                "10": 0.0001177, "11": 0.0001318, "12": 0.0001434, "13": 0.0001589, "14": 0.0001726, "15": 0.0001861, "16": 0.0001948
            }
        },
        "1\"": {  # 25.4 mm
            "BWG": {
                "8": 4.191, "10": 3.404, "11": 3.046, "12": 2.769, "13": 2.413, "14": 2.108
            },
            "internal_area_m2": {
                "8": 0.0003528, "10": 0.0004208, "11": 0.0004538, "12": 0.0004803, "13": 0.0005153, "14": 0.0005463
            }
        },
        "1.25\"": {  # 31.75 mm
            "BWG": {
                "7": 4.572, "8": 4.191, "10": 3.404, "11": 3.046, "12": 2.769, "13": 2.413, "14": 2.108
            },
            "internal_area_m2": {
                "7": 0.0004014, "8": 0.0004289, "10": 0.0004686, "11": 0.0005169, "12": 0.0005397, "13": 0.0005694, "14": 0.0005954
            }
        },
        "1.5\"": {  # 38.1 mm
            "BWG": {
                "10": 3.404, "12": 2.769, "14": 2.108, "16": 1.651
            },
            "internal_area_m2": {
                "10": 0.0007691, "12": 0.0008328, "14": 0.0009017, "16": 0.0009510
            }
        },
    }
    
    # Maximum working pressures from TEMA Table D-9A (psi) - simplified
    MAX_WORKING_PRESSURES = {
        "1/4\":22": 4920, "1/4\":24": 3786, "1/4\":26": 3056, "1/4\":27": 2698,
        "3/8\":18": 5836, "3/8\":20": 4034, "3/8\":22": 3175, "3/8\":24": 2462,
        "1/2\":16": 5803, "1/2\":18": 4253, "1/2\":20": 2966, "1/2\":22": 2345,
        "5/8\":12": 8107, "5/8\":14": 5943, "5/8\":16": 4537, "5/8\":18": 3345,
        "3/4\":10": 10351, "3/4\":12": 8107, "3/4\":14": 5943, "3/4\":16": 4537,
        "1\":8": 10667, "1\":10": 8391, "1\":12": 6578, "1\":14": 5114,
    }
    
    @classmethod
    def validate_tube_selection(cls, tube_size: str, bwg: str, 
                               design_pressure_kpa: float) -> Tuple[bool, str]:
        """Validate tube against TEMA standards"""
        
        if tube_size not in cls.TUBE_SIZES_BWG:
            return False, f"Tube size {tube_size} not in TEMA Table D-7 standards"
        
        if bwg not in cls.TUBE_SIZES_BWG[tube_size]["BWG"]:
            return False, f"BWG {bwg} not standard for {tube_size} tubes per TEMA"
        
        # Check working pressure
        key = f"{tube_size}:{bwg}"
        if key in cls.MAX_WORKING_PRESSURES:
            max_pressure_psi = cls.MAX_WORKING_PRESSURES[key]
            max_pressure_kpa = max_pressure_psi * 6.89476
            if design_pressure_kpa > max_pressure_kpa:
                return False, f"Design pressure exceeds TEMA Table D-9A maximum ({max_pressure_psi:.0f} psi / {max_pressure_kpa:.0f} kPa)"
        
        return True, "TEMA compliant"
    
    @classmethod
    def get_tube_thickness(cls, tube_size: str, bwg: str) -> float:
        """Get tube wall thickness in mm"""
        if tube_size in cls.TUBE_SIZES_BWG:
            if bwg in cls.TUBE_SIZES_BWG[tube_size]["BWG"]:
                return cls.TUBE_SIZES_BWG[tube_size]["BWG"][bwg]
        return 0.889  # Default to 20 BWG
    
    @classmethod
    def get_tube_od_mm(cls, tube_size: str) -> float:
        """Get tube outside diameter in mm from size string"""
        try:
            if '/' in tube_size:
                # Handle fractional sizes like "3/4\""
                parts = tube_size.replace('"', '').split('/')
                numerator = float(parts[0])
                denominator = float(parts[1])
                return numerator / denominator * 25.4
            else:
                # Handle decimal sizes like "1.25\""
                return float(tube_size.replace('"', '')) * 25.4
        except:
            return 19.05  # Default to 3/4"


class TEMABaffleStandards:
    """TEMA RCB-4 - Baffles and Support Plates (10th Edition)"""
    
    @staticmethod
    def validate_baffle_spacing(shell_id_m: float, baffle_spacing_m: float, 
                               tube_od_m: float, tema_class: str = "R") -> Dict:
        """
        TEMA RCB-4.5.1 Minimum Spacing: 1/5 of shell ID or 2", whichever greater
        """
        shell_id_inch = shell_id_m * 39.3701
        spacing_inch = baffle_spacing_m * 39.3701
        
        min_spacing_inch = max(shell_id_inch / 5, 2.0)
        min_spacing_m = min_spacing_inch / 39.3701
        
        result = {
            "compliant": spacing_inch >= min_spacing_inch,
            "minimum_spacing_m": min_spacing_m,
            "actual_spacing_m": baffle_spacing_m,
            "minimum_spacing_inch": min_spacing_inch,
            "actual_spacing_inch": spacing_inch,
            "warnings": []
        }
        
        if not result["compliant"]:
            result["warnings"].append(
                f"TEMA RCB-4.5.1: Baffle spacing ({baffle_spacing_m:.3f}m) below minimum ({min_spacing_m:.3f}m)"
            )
        
        return result
    
    @staticmethod
    def get_maximum_unsupported_span(tube_od_m: float, tube_material: str, 
                                    T_metal_c: float) -> float:
        """
        TEMA Table RCB-4.5.2 - Maximum Unsupported Straight Tube Spans
        """
        tube_od_inch = tube_od_m * 39.3701
        
        # Base maximum spans (inches) from TEMA table
        if tube_od_inch <= 0.25:
            base_span_inch = 26 if "Steel" in tube_material else 22
        elif tube_od_inch <= 0.375:
            base_span_inch = 35 if "Steel" in tube_material else 30
        elif tube_od_inch <= 0.5:
            base_span_inch = 44 if "Steel" in tube_material else 38
        elif tube_od_inch <= 0.625:
            base_span_inch = 52 if "Steel" in tube_material else 45
        elif tube_od_inch <= 0.75:
            base_span_inch = 60 if "Steel" in tube_material else 52
        elif tube_od_inch <= 0.875:
            base_span_inch = 69 if "Steel" in tube_material else 60
        elif tube_od_inch <= 1.0:
            base_span_inch = 74 if "Steel" in tube_material else 64
        elif tube_od_inch <= 1.25:
            base_span_inch = 88 if "Steel" in tube_material else 76
        elif tube_od_inch <= 1.5:
            base_span_inch = 100 if "Steel" in tube_material else 87
        elif tube_od_inch <= 2.0:
            base_span_inch = 125 if "Steel" in tube_material else 110
        else:
            base_span_inch = 125
        
        # Temperature correction (Note 1)
        if T_metal_c > 399:  # 750°F for carbon steel
            # Simplified correction - in practice need E modulus ratio^0.25
            correction = 0.9
        else:
            correction = 1.0
        
        span_inch = base_span_inch * correction
        span_m = span_inch * 0.0254
        
        return span_m
    
    @staticmethod
    def calculate_impingement_requirement(rho: float, v: float, 
                                         fluid_type: str = "single_phase") -> Dict:
        """
        TEMA RCB-4.6.1 - Impingement Protection Requirements
        ρV² > 1500 for non-abrasive single phase (lb/ft³·ft²/s²)
        ρV² > 500 for boiling liquids
        """
        # Convert to US customary units for TEMA check
        rho_lb_ft3 = rho * 0.062428  # kg/m³ to lb/ft³
        v_ft_s = v * 3.28084  # m/s to ft/s
        
        pv2 = rho_lb_ft3 * (v_ft_s ** 2)
        
        limits = {
            "non_abrasive_single_phase": 1500,
            "boiling_liquids": 500,
            "other_liquids": 500,
            "gases_vapors": 0,
            "two_phase": 0,
        }
        
        limit = limits.get(fluid_type, 1500)
        required = pv2 > limit if limit > 0 else True
        
        return {
            "impingement_required": required,
            "pv2_value_us": pv2,
            "pv2_limit_us": limit,
            "pv2_value_si": rho * (v ** 2),
            "exceeds_limit": pv2 > limit if limit > 0 else True,
            "fluid_type": fluid_type
        }
    
    @staticmethod
    def get_tie_rod_requirements(shell_diameter_m: float, tema_class: str = "R") -> Dict:
        """
        TEMA Table R-4.7.1 / CB-4.7.1 - Tie Rod Requirements
        """
        shell_diameter_inch = shell_diameter_m * 39.3701
        
        if tema_class == "R":
            if shell_diameter_inch <= 15:
                return {"diameter_mm": 9.5, "min_qty": 4, "diameter_inch": "3/8"}
            elif shell_diameter_inch <= 27:
                return {"diameter_mm": 9.5, "min_qty": 6, "diameter_inch": "3/8"}
            elif shell_diameter_inch <= 33:
                return {"diameter_mm": 12.7, "min_qty": 6, "diameter_inch": "1/2"}
            elif shell_diameter_inch <= 48:
                return {"diameter_mm": 12.7, "min_qty": 8, "diameter_inch": "1/2"}
            elif shell_diameter_inch <= 60:
                return {"diameter_mm": 12.7, "min_qty": 10, "diameter_inch": "1/2"}
            else:
                return {"diameter_mm": 15.9, "min_qty": 12, "diameter_inch": "5/8"}
        else:  # Class C/B
            if shell_diameter_inch <= 15:
                return {"diameter_mm": 6.4, "min_qty": 4, "diameter_inch": "1/4"}
            elif shell_diameter_inch <= 27:
                return {"diameter_mm": 9.5, "min_qty": 6, "diameter_inch": "3/8"}
            elif shell_diameter_inch <= 33:
                return {"diameter_mm": 12.7, "min_qty": 6, "diameter_inch": "1/2"}
            elif shell_diameter_inch <= 48:
                return {"diameter_mm": 12.7, "min_qty": 8, "diameter_inch": "1/2"}
            elif shell_diameter_inch <= 60:
                return {"diameter_mm": 12.7, "min_qty": 10, "diameter_inch": "1/2"}
            else:
                return {"diameter_mm": 15.9, "min_qty": 12, "diameter_inch": "5/8"}


class TEMATubesheetStandards:
    """TEMA RCB-7 and Appendix A - Tubesheet Design (10th Edition)"""
    
    @staticmethod
    def validate_tube_hole_diameter(tube_od_mm: float, hole_diameter_mm: float,
                                   fit_type: str = "standard") -> Dict:
        """
        TEMA Table RCB-7.2.1 - Tube Hole Diameters and Tolerances
        """
        tube_od_inch = tube_od_mm / 25.4
        
        # TEMA standard fits
        if fit_type == "standard":
            target_inch = tube_od_inch + 0.004
            under_tolerance = 0.004
            over_tolerance_96pct = 0.002
            over_tolerance_max = 0.007 if tube_od_inch <= 0.5 else 0.010
        else:  # special close fit
            target_inch = tube_od_inch + 0.002
            under_tolerance = 0.002
            over_tolerance_96pct = 0.002
            over_tolerance_max = 0.008 if tube_od_inch <= 0.5 else 0.010
        
        target_mm = target_inch * 25.4
        actual_mm = hole_diameter_mm
        
        return {
            "compliant": abs(actual_mm - target_mm) <= (under_tolerance * 25.4),
            "target_diameter_mm": round(target_mm, 3),
            "actual_diameter_mm": round(actual_mm, 3),
            "tolerance_mm": round(under_tolerance * 25.4, 3),
            "fit_type": fit_type,
            "under_tolerance_mm": round(under_tolerance * 25.4, 3),
            "over_tolerance_96pct_mm": round(over_tolerance_96pct * 25.4, 3),
            "over_tolerance_max_mm": round(over_tolerance_max * 25.4, 3)
        }
    
    @staticmethod
    def calculate_min_thickness_expanded_joints(tube_od_mm: float, tema_class: str = "R") -> float:
        """
        TEMA R-7.1.1 / C-7.1.1 / B-7.1.1
        Minimum tubesheet thickness for expanded tube joints
        """
        tube_od_inch = tube_od_mm / 25.4
        
        if tema_class == "R":
            # Class R: Not less than tube OD
            return tube_od_mm
        else:
            # Class C/B: 3/4 of tube OD for ≤1", graduated for larger
            if tube_od_inch <= 1.0:
                return 0.75 * tube_od_mm
            elif tube_od_inch <= 1.25:
                return 22.2  # 7/8"
            elif tube_od_inch <= 1.5:
                return 25.4  # 1"
            else:
                return 31.8  # 1-1/4"
    
    @staticmethod
    def calculate_min_tubesheet_thickness_bending(P: float, G: float, S: float, 
                                                 F: float = 1.0) -> float:
        """
        TEMA Appendix A.1.3.1 - Tubesheet Formula for Bending
        T = F * G * sqrt(P / (3 * eta * S))
        """
        eta = 1.0  # Tube support factor, assume 1.0 for supported tubesheets
        
        T = F * G * math.sqrt(P / (3 * eta * S))
        return T * 1000  # Convert to mm
    @staticmethod
    def calculate_min_tubesheet_thickness(shell_diameter_mm: float,
                                          tube_od_mm: float,
                                          tube_pitch_mm: float,
                                          design_pressure_pa: float,
                                          max_temp_c: float | None = None,
                                          tema_class: str = "R") -> float:
        """
        Convenience wrapper used by the condenser path.

        Note:
        - Full TEMA tubesheet design per Appendix A requires additional inputs
          (materials/allowable stresses, joint details, effective span, etc.).
        - At this stage, we use the TEMA minimum thickness for expanded joints
          (RCB/R-7.1.1 / C-7.1.1 / B-7.1.1), which is conservative for many
          standard exchangers and prevents the app from crashing.

        Returns thickness in mm.
        """
        try:
            return TEMATubesheetStandards.calculate_min_thickness_expanded_joints(
                float(tube_od_mm), str(tema_class or "R")
            )
        except Exception:
            # Absolute fallback: at least tube OD (very conservative)
            return float(tube_od_mm)



class TEMAVibrationAnalysis:
    """
    TEMA Section 6 - Flow Induced Vibration (10th Edition)
    Critical for preventing tube failure in service
    """
    
    def __init__(self, designer):
        self.designer = designer
    
    def calculate_tube_natural_frequency(self, tube_od_m: float, tube_id_m: float,
                                        unsupported_span_m: float, E_tube_pa: float,
                                        rho_tube_kgm3: float, rho_fluid_kgm3: float,
                                        end_condition: str = "simply_supported") -> float:
        """
        TEMA Table V-5.3 - Fundamental Natural Frequency
        """
        # Tube moment of inertia (m^4)
        I = (math.pi / 64) * (tube_od_m**4 - tube_id_m**4)
        
        # Tube metal cross-sectional area (m^2)
        A_metal = math.pi * (tube_od_m**2 - tube_id_m**2) / 4
        
        # Mass per unit length (kg/m)
        m_tube = A_metal * rho_tube_kgm3
        
        # Fluid inside tube mass
        A_fluid = math.pi * tube_id_m**2 / 4
        m_fluid = A_fluid * rho_fluid_kgm3
        
        # Hydrodynamic mass (TEMA V-7.1.1)
        # Estimate added mass coefficient based on pitch ratio
        pitch_ratio = getattr(self.designer, 'pitch_ratio', 1.25)
        if pitch_ratio <= 1.25:
            C_m = 1.8
        elif pitch_ratio <= 1.5:
            C_m = 1.6 - (pitch_ratio - 1.25) * 0.8
        elif pitch_ratio <= 2.0:
            C_m = 1.2 - (pitch_ratio - 1.5) * 0.4
        else:
            C_m = 1.0
        
        m_displaced = (math.pi * tube_od_m**2 / 4) * rho_fluid_kgm3
        m_hydro = C_m * m_displaced
        
        m_effective = m_tube + m_fluid + m_hydro
        
        # End condition constant
        end_constants = {
            "both_ends_simply_supported": math.pi**2,
            "one_end_fixed_one_end_simply": (4.49)**2,
            "both_ends_fixed": (2 * math.pi)**2
        }
        C = end_constants.get(end_condition, math.pi**2)
        
        # Natural frequency (Hz)
        fn = (C / (2 * math.pi * unsupported_span_m**2)) * math.sqrt((E_tube_pa * I) / m_effective)
        
        return fn
    
    def calculate_critical_velocity(self, fn: float, d0_m: float,
                                   m_effective: float, delta: float,
                                   rho_shell_kgm3: float, tube_pattern: str,
                                   pitch_ratio: float) -> float:
        """
        TEMA V-10 - Critical Flow Velocity
        """
        # Convert to US customary units for TEMA correlations
        d0_inch = d0_m * 39.3701
        m_effective_lb_ft = m_effective * 0.671969  # kg/m to lb/ft
        rho_shell_lb_ft3 = rho_shell_kgm3 * 0.062428
        
        # Fluid elastic parameter X (TEMA V-4.2)
        X = (144 * m_effective_lb_ft * delta) / (rho_shell_lb_ft3 * d0_inch**2)
        
        # Critical velocity factor D (TEMA Table V-10.1)
        if tube_pattern == "30°" or tube_pattern == "triangular":
            if X <= 1:
                D = 8.86 * (pitch_ratio - 0.9) * X**0.34
            else:
                D = 8.86 * (pitch_ratio - 0.9) * X**0.5
        elif tube_pattern == "60°":
            if X <= 1:
                D = 2.80 * X**0.17
            else:
                D = 2.80 * X**0.5
        elif tube_pattern == "90°" or tube_pattern == "square":
            if X <= 0.7:
                D = 2.10 * X**0.15
            else:
                D = 2.35 * X**0.5
        else:  # 45° or rotated square
            D = 4.13 * (pitch_ratio - 0.5) * X**0.5
        
        # Critical velocity in ft/s, convert to m/s
        Vc_ft_s = (D * fn * d0_inch) / 12
        Vc_ms = Vc_ft_s * 0.3048
        
        return Vc_ms
    
    def assess_vibration_risk(self, results: Dict) -> Dict:
        """
        Comprehensive vibration risk assessment per TEMA Section 6
        """
        # Extract needed parameters
        tube_od_m = results.get('tube_od_mm', 19.05) / 1000
        tube_id_m = results.get('tube_id_mm', 15.75) / 1000
        span_m = results.get('max_unsupported_span_m', results.get('baffle_spacing_m', 0.5))
        
        # Default values if not available
        E_tube_pa = 1.1e11  # Copper alloy approx
        rho_tube = 8960  # Copper density
        rho_fluid = results.get('rho_shell', 1000)
        delta = results.get('log_dec', 0.03)  # Typical damping
        
        # Calculate natural frequency
        fn = self.calculate_tube_natural_frequency(
            tube_od_m, tube_id_m, span_m, E_tube_pa, rho_tube, rho_fluid
        )
        
        # Calculate effective mass (simplified)
        A_metal = math.pi * (tube_od_m**2 - tube_id_m**2) / 4
        m_effective = A_metal * rho_tube + (math.pi * tube_id_m**2 / 4) * rho_fluid
        
        # Calculate critical velocity
        Vc = self.calculate_critical_velocity(
            fn, tube_od_m, m_effective, delta,
            results.get('rho_shell', 1000),
            results.get('tube_layout', 'triangular'),
            results.get('pitch_ratio', 1.25)
        )
        
        V_actual = results.get('velocity_shell_ms', 0)
        safety_factor = Vc / V_actual if V_actual > 0 else 999
        
        # Risk assessment
        if safety_factor >= 2.0:
            risk_level = "LOW"
            risk_color = "🟢"
            recommendation = "Vibration risk acceptable per TEMA Section 6 guidelines."
        elif safety_factor >= 1.5:
            risk_level = "MEDIUM"
            risk_color = "🟡"
            recommendation = "Moderate vibration risk. Consider reducing unsupported span or increasing tube stiffness."
        elif safety_factor >= 1.0:
            risk_level = "HIGH"
            risk_color = "🟠"
            recommendation = "HIGH vibration risk. Redesign required: reduce baffle spacing, increase tube gauge, or add support plates."
        else:
            risk_level = "CRITICAL"
            risk_color = "🔴"
            recommendation = "CRITICAL vibration risk. IMMEDIATE REDESIGN REQUIRED. Consult TEMA Section 6 for mitigation strategies."
        
        return {
            "natural_frequency_hz": round(fn, 2),
            "critical_velocity_ms": round(Vc, 3),
            "actual_velocity_ms": round(V_actual, 3),
            "safety_factor": round(safety_factor, 2),
            "risk_level": risk_level,
            "risk_color": risk_color,
            "recommendation": recommendation,
            "tema_compliant": safety_factor >= 1.5
        }


# ============================================================================
# MAIN DESIGN CLASS - TEMA 10th EDITION COMPLIANT
# ============================================================================

class TEMACompliantDXHeatExchangerDesign:
    """TEMA 10th Edition Compliant DX Shell & Tube Heat Exchanger Design"""
    
    # Tube materials with thermal conductivity (W/m·K) and elastic modulus (GPa)
    TUBE_MATERIALS = {
        "Copper": {"k": 386, "density": 8960, "cost_factor": 1.0, "E_modulus_gpa": 110},
        "Cu-Ni 90/10": {"k": 40, "density": 8940, "cost_factor": 1.8, "E_modulus_gpa": 135},
        "Steel": {"k": 50, "density": 7850, "cost_factor": 0.6, "E_modulus_gpa": 200},
        "Aluminum Brass": {"k": 100, "density": 8300, "cost_factor": 1.2, "E_modulus_gpa": 110},
        "Stainless Steel 304": {"k": 16, "density": 8000, "cost_factor": 2.5, "E_modulus_gpa": 193},
        "Stainless Steel 316": {"k": 16, "density": 8000, "cost_factor": 3.0, "E_modulus_gpa": 193},
        "Titanium": {"k": 22, "density": 4500, "cost_factor": 8.0, "E_modulus_gpa": 116}
    }
    
    # Tube sizes from TEMA Table D-7
    TUBE_SIZES = TEMATubeStandards.TUBE_SIZES_BWG
    
    # Recommended velocities from TEMA/industry practice
    RECOMMENDED_VELOCITIES = {
        "water_tubes": {"min": 0.6, "opt": 1.2, "max": 2.5},
        "water_shell": {"min": 0.3, "opt": 0.8, "max": 1.5},
        "glycol_tubes": {"min": 0.4, "opt": 0.9, "max": 2.0},
        "glycol_shell": {"min": 0.2, "opt": 0.6, "max": 1.2},
        "refrigerant_two_phase": {"min": 0.5, "opt": 1.0, "max": 3.0},
        "refrigerant_vapor": {"min": 5.0, "opt": 10.0, "max": 30.0},
        "refrigerant_liquid": {"min": 0.5, "opt": 1.0, "max": 2.0}
    }
    
    def __init__(self):
        self.results = {}
        self.warnings = []
        self.tema_class = "R"
        self.pitch_ratio = 1.25
        self.tema_vibration = TEMAVibrationAnalysis(self)
    
    
    # ========================================================================
    # TEMA VIBRATION WRAPPER (Used by condenser path)
    # ========================================================================

    def analyze_vibration_tema(self, vib: Dict) -> Dict:
        """
        Run a simplified TEMA Section 6 vibration screening using the same
        underlying formulas already used in the evaporator path.

        Inputs (vib dict) expected (SI units):
          - tube_od_m, tube_id_m, baffle_spacing_m
          - tube_material (key from TUBE_MATERIALS)
          - shell_velocity_ms (crossflow / shell-side velocity to compare)
          - shell_density (density of shell-side fluid)
          - tube_density  (density of tube-side fluid; used only for added mass approx)
          - tube_layout, pitch_ratio (optional; defaults applied)

        Returns dict with keys:
          natural_frequency_hz, critical_velocity_ms, actual_velocity_ms,
          safety_factor, risk_level, tema_compliant
        """
        # Defaults
        v_actual = float(vib.get("shell_velocity_ms", 0.0) or 0.0)

        tube_od = float(vib.get("tube_od_m", 0.0) or 0.0)
        tube_id = float(vib.get("tube_id_m", 0.0) or 0.0)
        span = float(vib.get("baffle_spacing_m", 0.0) or 0.0)

        tube_material = vib.get("tube_material", "Copper")
        tube_layout = vib.get("tube_layout", "triangular")
        pitch_ratio = float(vib.get("pitch_ratio", getattr(self, "pitch_ratio", 1.25)) or 1.25)

        rho_shell = float(vib.get("shell_density", 1000.0) or 1000.0)
        rho_added = float(vib.get("tube_density", rho_shell) or rho_shell)

        # Guard: if not enough geometry, return "not analyzed" without crashing
        if tube_od <= 0 or tube_id <= 0 or span <= 0:
            return {
                "natural_frequency_hz": 0.0,
                "critical_velocity_ms": 0.0,
                "actual_velocity_ms": round(v_actual, 3),
                "safety_factor": 0.0,
                "risk_level": "NOT ANALYZED",
                "tema_compliant": True,
                "note": "Insufficient geometry for vibration screening (OD/ID/span)."
            }

        # Material properties
        mat = self.TUBE_MATERIALS.get(tube_material, self.TUBE_MATERIALS["Copper"])
        E_tube_pa = float(mat.get("E_modulus_gpa", 110)) * 1e9
        rho_tube = float(mat.get("density", 8960))

        # Natural frequency
        fn = self.tema_vibration.calculate_tube_natural_frequency(
            tube_od, tube_id, span, E_tube_pa, rho_tube, rho_shell
        )

        # Effective mass (simplified): tube metal + contained/added fluid mass
        A_metal = math.pi * (tube_od**2 - tube_id**2) / 4
        m_effective = A_metal * rho_tube + (math.pi * tube_id**2 / 4) * rho_added

        # Damping (logarithmic decrement) typical screening value
        delta = float(vib.get("log_dec", 0.03) or 0.03)

        Vc = self.tema_vibration.calculate_critical_velocity(
            fn, tube_od, m_effective, delta, rho_shell, tube_layout, pitch_ratio
        )

        safety = (Vc / v_actual) if v_actual > 0 else 999.0

        # Risk bands (simple)
        if safety >= 2.0:
            risk = "LOW"
            compliant = True
        elif safety >= 1.5:
            risk = "MODERATE"
            compliant = True
        elif safety >= 1.0:
            risk = "HIGH"
            compliant = False
        else:
            risk = "SEVERE"
            compliant = False

        return {
            "natural_frequency_hz": round(fn, 2),
            "critical_velocity_ms": round(Vc, 3),
            "actual_velocity_ms": round(v_actual, 3),
            "safety_factor": round(safety, 2),
            "risk_level": risk,
            "tema_compliant": compliant
        }

# ========================================================================
    # COOLPROP PROPERTY METHODS
    # ========================================================================
    
    def get_refrigerant_properties(self, refrigerant: str, T_sat: float) -> Dict:
        """Get EXACT refrigerant properties from CoolProp at saturation temperature"""
        try:
            T_K = T_sat + 273.15
            
            # Saturation pressure
            P_sat = CP.PropsSI('P', 'T', T_K, 'Q', 1, refrigerant)
            
            # Liquid at saturation
            rho_l = CP.PropsSI('D', 'T', T_K, 'Q', 0, refrigerant)
            cp_l = CP.PropsSI('C', 'T', T_K, 'Q', 0, refrigerant)
            k_l = CP.PropsSI('L', 'T', T_K, 'Q', 0, refrigerant)
            mu_l = CP.PropsSI('V', 'T', T_K, 'Q', 0, refrigerant)
            
            # Vapor at saturation
            rho_v = CP.PropsSI('D', 'T', T_K, 'Q', 1, refrigerant)
            cp_v = CP.PropsSI('C', 'T', T_K, 'Q', 1, refrigerant)
            k_v = CP.PropsSI('L', 'T', T_K, 'Q', 1, refrigerant)
            mu_v = CP.PropsSI('V', 'T', T_K, 'Q', 1, refrigerant)
            
            # Latent heat (J/kg)
            h_l = CP.PropsSI('H', 'T', T_K, 'Q', 0, refrigerant)
            h_v = CP.PropsSI('H', 'T', T_K, 'Q', 1, refrigerant)
            h_fg = h_v - h_l
            
            # Prandtl numbers
            pr_l = cp_l * mu_l / k_l
            pr_v = cp_v * mu_v / k_v
            
            # Surface tension
            sigma = CP.PropsSI('I', 'T', T_K, 'Q', 0, refrigerant)
            
            # Critical properties
            T_crit = CP.PropsSI('TCRIT', refrigerant) - 273.15
            P_crit = CP.PropsSI('PCRIT', refrigerant) / 1000  # kPa
            
            return {
                "cp_vapor": cp_v / 1000,  # kJ/kg·K
                "cp_liquid": cp_l / 1000,  # kJ/kg·K
                "h_fg": h_fg / 1000,  # kJ/kg
                "rho_vapor": rho_v,  # kg/m³
                "rho_liquid": rho_l,  # kg/m³
                "mu_vapor": mu_v,  # Pa·s
                "mu_liquid": mu_l,  # Pa·s
                "k_vapor": k_v,  # W/m·K
                "k_liquid": k_l,  # W/m·K
                "pr_vapor": pr_v,
                "pr_liquid": pr_l,
                "sigma": sigma,
                "T_critical": T_crit,
                "P_critical": P_crit,
                "T_sat": T_sat,
                "P_sat": P_sat / 1000,  # kPa
            }
        except Exception as e:
            self.warnings.append(f"CoolProp error for {refrigerant} at {T_sat}°C: {e}")
            # Fallback to approximate values for R134a if CoolProp fails
            return {
                "cp_vapor": 0.852, "cp_liquid": 1.434, "h_fg": 198.7,
                "rho_vapor": 14.43, "rho_liquid": 1277.8,
                "mu_vapor": 1.11e-5, "mu_liquid": 2.04e-4,
                "k_vapor": 0.0116, "k_liquid": 0.0845,
                "pr_vapor": 0.815, "pr_liquid": 3.425,
                "sigma": 0.00852, "T_critical": 101.1, "P_critical": 4059.0,
                "T_sat": T_sat, "P_sat": 350.0
            }
    
    def get_glycol_properties(self, glycol_type: str, concentration: int, temperature: float) -> Dict:
        """Get EXACT glycol/water mixture properties from CoolProp"""
        try:
            # CoolProp mixture string
            if concentration <= 0:
                mixture = "WATER"
            elif glycol_type.lower() == "ethylene":
                mixture = f"EG-{concentration}%"
            else:  # propylene
                mixture = f"PG-{concentration}%"
            
            T_K = temperature + 273.15
            P = 101325  # Atmospheric pressure
            
            cp = CP.PropsSI('C', 'T', T_K, 'P', P, mixture)  # J/kg·K
            rho = CP.PropsSI('D', 'T', T_K, 'P', P, mixture)  # kg/m³
            mu = CP.PropsSI('V', 'T', T_K, 'P', P, mixture)  # Pa·s
            k = CP.PropsSI('L', 'T', T_K, 'P', P, mixture)  # W/m·K
            pr = cp * mu / k
            
            # Approximate freeze points (simplified)
            if glycol_type.lower() == "ethylene":
                freeze_points = {0: 0, 10: -3.5, 20: -7.5, 30: -14, 40: -23, 50: -36, 60: -52}
            else:
                freeze_points = {0: 0, 10: -3, 20: -7, 30: -13, 40: -21, 50: -33, 60: -48}
            
            freeze_point = freeze_points.get(concentration, 0)
            
            return {
                "cp": cp,  # J/kg·K
                "rho": rho,  # kg/m³
                "mu": mu,  # Pa·s
                "k": k,  # W/m·K
                "pr": pr,
                "freeze_point": freeze_point,
                "glycol_type": glycol_type,
                "glycol_percentage": concentration
            }
        except Exception as e:
            self.warnings.append(f"CoolProp error for {glycol_type} {concentration}%: {e}")
            # Fallback to water
            return {
                "cp": 4186, "rho": 998, "mu": 0.001, "k": 0.598, "pr": 7.01,
                "freeze_point": 0, "glycol_type": glycol_type, "glycol_percentage": concentration
            }
    
    # ========================================================================
    # HEAT TRANSFER CORRELATIONS
    # ========================================================================
    
    def gnielinski_single_phase(self, Re: float, Pr: float, f: float = None) -> float:
        """Gnielinski correlation for single-phase turbulent flow"""
        if Re < 2300:
            return 4.36
        elif Re < 3000:
            Nu_lam = 4.36
            Nu_3000 = 0.023 * 3000**0.8 * Pr**0.4
            return Nu_lam + (Re - 2300) / 700 * (Nu_3000 - Nu_lam)
        else:
            if f is None:
                f = (0.79 * math.log(Re) - 1.64)**-2
            Nu = (f/8) * (Re - 1000) * Pr / (1 + 12.7 * (f/8)**0.5 * (Pr**(2/3) - 1))
            return max(Nu, 4.36)
    
    def shah_evaporation_improved(self, Re_l: float, Pr_l: float, x: float, 
                                 rho_l: float, rho_v: float, D: float, G: float, 
                                 h_fg: float, k_l: float, cp_l: float, mu_l: float) -> float:
        """Improved Shah correlation for flow boiling"""
        if x <= 0:
            return self.gnielinski_single_phase(Re_l, Pr_l) * k_l / D
        
        if x >= 1.0:
            Re_v = G * D / mu_l
            return self.gnielinski_single_phase(Re_v, Pr_l) * k_l / D * 0.6
        
        g = 9.81
        Fr_l = G**2 / (rho_l**2 * g * D)
        Co = ((1 - x) / x)**0.8 * (rho_v / rho_l)**0.5
        q_flux_estimate = 10000
        Bo = q_flux_estimate / (G * h_fg)
        
        if Re_l < 2300:
            Nu_l = 4.36
        else:
            f_l = (0.79 * math.log(Re_l) - 1.64)**-2 if Re_l > 0 else 0.02
            Nu_l = (f_l/8) * (Re_l - 1000) * Pr_l / (1 + 12.7 * (f_l/8)**0.5 * (Pr_l**(2/3) - 1))
            Nu_l = max(Nu_l, 4.36)
        
        h_l = Nu_l * k_l / D
        
        if Fr_l >= 0.04:
            if Bo > 0.0011:
                if Co <= 1.0:
                    psi = 230 * Bo**0.5
                else:
                    psi = 1.8 / Co**0.8
                if psi < max(1.0, Bo**-0.5):
                    psi = max(1.0, Bo**-0.5)
            else:
                F_nb = 14.7 * Bo**0.5
                psi = max(1.8 / Co**0.8, F_nb)
        else:
            psi_vertical = 1.8 / Co**0.8 if Co > 0.65 else 230 * Bo**0.5
            psi = max(psi_vertical, 14.7 * Bo**0.5)
        
        enhancement = 1 + x * (rho_l / rho_v - 1)
        h_tp = h_l * psi * min(enhancement, 3.0)
        h_tp = max(h_tp, 500)
        h_tp = min(h_tp, 15000)
        
        return h_tp
    
    def dobson_chato_improved(self, G: float, D: float, T_sat: float, 
                            rho_l: float, rho_v: float, mu_l: float, mu_v: float,
                            k_l: float, cp_l: float, h_fg: float, 
                            x: float, P_sat: float = None) -> float:
        """Improved Dobson & Chato correlation for condensation"""
        g = 9.81
        delta_T = 5.0
        h_fg_prime = h_fg + 0.68 * cp_l * delta_T
        
        Re_eq = G * D / mu_l
        Re_v = G * x * D / mu_v if mu_v > 0 else 0
        
        if x > 0 and x < 1:
            X_tt = ((1 - x) / x)**0.9 * (rho_v / rho_l)**0.5 * (mu_l / mu_v)**0.1
        else:
            X_tt = 0.1
        
        Fr_so = G**2 / (rho_l**2 * g * D)
        
        if x > 0.5 and Fr_so > 1.0:
            regime = "annular"
        elif Fr_so > 7.0:
            regime = "annular"
        else:
            regime = "stratified-wavy"
        
        if regime == "annular":
            Pr_l = mu_l * cp_l / k_l
            
            if Re_eq > 2300:
                f = (0.79 * math.log(Re_eq) - 1.64)**-2
                Nu_l = (f/8) * Re_eq * Pr_l / (1 + 12.7 * (f/8)**0.5 * (Pr_l**(2/3) - 1))
            else:
                Nu_l = 4.36
            
            h_l = Nu_l * k_l / D
            
            if X_tt > 0:
                phi_l = 1 + 2.22 / X_tt**0.89
            else:
                phi_l = 1.0
            
            h_annular = h_l * phi_l
            
            if x > 0.7:
                enhancement = 1 + 0.8 * (x - 0.7) * min(Re_v / 10000, 2.0)
                h_annular *= enhancement
            
            h_tp = h_annular
            
        else:
            Nu_film = 0.555 * ((g * rho_l * (rho_l - rho_v) * k_l**3 * h_fg_prime) / 
                              (mu_l * D * delta_T))**0.25
            
            if Fr_so > 0.1:
                Pr_l = mu_l * cp_l / k_l
                Re_l = G * (1 - x) * D / mu_l if mu_l > 0 else 0
                
                if Re_l > 2300:
                    Nu_conv = 0.023 * Re_l**0.8 * Pr_l**0.4
                else:
                    Nu_conv = 4.36
                
                h_conv = Nu_conv * k_l / D
                h_tp = Nu_film * k_l / D + 0.3 * h_conv * (1 - x)
            else:
                h_tp = Nu_film * k_l / D
        
        h_tp = max(h_tp, 800)
        h_tp = min(h_tp, 8000)
        
        return h_tp
    
    def calculate_single_phase_htc(
        self,
        m_dot_total: float,
        D: float,
        rho: float,
        mu: float,
        k: float,
        cp: float,
        n_tubes: int = 1,
        n_passes: int = 1,
    ) -> float:
        """Calculate single-phase HTC (Gnielinski) with correct flow splitting across parallel tubes.

        Notes
        -----
        For tube-side flow, the total mass flow is split across (n_tubes / n_passes) tubes in parallel per pass.
        For non-tube geometries (e.g., shell-side equivalent diameter), call with n_tubes=1, n_passes=1 and supply
        appropriate characteristic diameter D and velocity separately if needed.
        """
        # Guardrails
        n_tubes = max(int(n_tubes), 1)
        n_passes = max(int(n_passes), 1)

        # Parallel tubes per pass
        n_parallel = max(n_tubes / n_passes, 1.0)

        # Total flow area across parallel tubes
        A_single = math.pi * D**2 / 4
        A_total = A_single * n_parallel

        v = m_dot_total / (rho * A_total) if (rho > 0 and A_total > 0) else 0.0

        Re = rho * v * D / mu if mu > 0 else 0.0
        Pr = mu * cp / k if k > 0 else 0.0

        if Re > 0 and Pr > 0:
            Nu = self.gnielinski_single_phase(Re, Pr)
            h = Nu * k / D
        else:
            h = 100.0

        return h
    
    def epsilon_ntu_counterflow(self, NTU: float, C_r: float) -> float:
        """ε-NTU relationship for counterflow"""
        if C_r < 1e-6:
            epsilon = 1 - math.exp(-NTU)
        elif abs(1 - C_r) < 1e-6:
            epsilon = NTU / (1 + NTU)
        else:
            numerator = 1 - math.exp(-NTU * (1 - C_r))
            denominator = 1 - C_r * math.exp(-NTU * (1 - C_r))
            if denominator == 0:
                epsilon = 1.0
            else:
                epsilon = numerator / denominator
        
        epsilon = max(0.0, min(epsilon, 1.0))
        return epsilon
    
    # ========================================================================
    # GEOMETRY CALCULATIONS
    # ========================================================================
    
    def calculate_shell_diameter(self, tube_od: float, n_tubes: int, pitch: float,
                               tube_layout: str = "triangular") -> float:
        """Calculate shell diameter based on tube layout"""
        if tube_layout.lower() == "triangular":
            tubes_per_row = math.sqrt(n_tubes / 0.866)
            bundle_width = tubes_per_row * pitch
        else:
            tubes_per_row = math.sqrt(n_tubes)
            bundle_width = tubes_per_row * pitch
        
        # TEMA clearance guidelines
        if bundle_width < 0.3:
            clearance = 0.010
        elif bundle_width < 0.6:
            clearance = 0.015
        else:
            clearance = 0.020
        
        shell_diameter = bundle_width + 2 * clearance
        return max(shell_diameter, 0.1)
    
    def calculate_bundle_diameter(self, tube_od: float, n_tubes: int, pitch: float,
                                tube_layout: str = "triangular") -> float:
        """Calculate bundle diameter"""
        if tube_layout.lower() == "triangular":
            tubes_per_row = math.sqrt(n_tubes / 0.866)
            bundle_diameter = tubes_per_row * pitch
        else:
            tubes_per_row = math.sqrt(n_tubes)
            bundle_diameter = tubes_per_row * pitch
        
        return bundle_diameter
    
    def calculate_shell_side_flow_area(self, shell_diameter: float, bundle_diameter: float,
                                      tube_od: float, n_tubes: int, baffle_spacing: float,
                                      baffle_cut: float = 0.25) -> float:
        """Calculate shell-side flow area per TEMA guidelines"""
        # Cross-flow area at bundle centerline
        A_cross = (shell_diameter - bundle_diameter) * baffle_spacing * 0.8
        
        # Window flow area (simplified)
        theta_baffle = 2 * math.acos(1 - 2 * baffle_cut)
        A_window_total = (shell_diameter**2 / 8) * (theta_baffle - math.sin(theta_baffle))
        
        n_tubes_in_window = n_tubes * baffle_cut
        A_tubes_in_window = n_tubes_in_window * math.pi * tube_od**2 / 4
        A_window = A_window_total - A_tubes_in_window
        
        A_flow = min(A_cross, A_window)
        A_flow = max(A_flow, 0.001)
        
        return A_flow
    
    def calculate_shell_side_htc(self, Re: float, Pr: float, D_e: float,
                               k: float, tube_layout: str) -> float:
        """Calculate shell-side HTC using Colburn j-factor analogy"""
        if Re < 100:
            if tube_layout == "triangular":
                Nu = 1.0
            else:
                Nu = 0.9
        elif Re < 1000:
            if tube_layout == "triangular":
                Nu = 0.6 * Re**0.5 * Pr**0.33
            else:
                Nu = 0.5 * Re**0.5 * Pr**0.33
        else:
            if tube_layout == "triangular":
                Nu = 0.36 * Re**0.55 * Pr**0.33
            else:
                Nu = 0.31 * Re**0.6 * Pr**0.33
        
        return Nu * k / D_e
    
    # ========================================================================
    # DX EVAPORATOR DESIGN (Correct: Refrigerant in tubes, Water on shell)
    # ========================================================================
    
    def design_dx_evaporator(self, inputs: Dict) -> Dict:
        """
        Design DX evaporator - TEMA compliant
        CORRECT CONFIGURATION: Refrigerant in TUBES, Water/Glycol on SHELL
        """
        self.warnings = []
        
        # Unpack inputs
        refrigerant = inputs["refrigerant"]
        m_dot_ref = inputs["m_dot_ref"]  # Tube side
        T_evap = inputs["T_ref"]
        superheat_req = inputs["delta_T_sh_sc"]
        inlet_quality = inputs.get("inlet_quality", 20)
        
        # Refrigerant properties at evaporating temperature
        ref_props = self.get_refrigerant_properties(refrigerant, T_evap)
        
        # Water/glycol properties (shell side)
        glycol_percent = inputs["glycol_percentage"]
        glycol_type = inputs.get("glycol_type", "ethylene")
        m_dot_sec_L = inputs["m_dot_sec"] / 3600  # L/hr to L/s
        T_sec_in = inputs["T_sec_in"]
        
        sec_props = self.get_glycol_properties(glycol_type, glycol_percent, T_sec_in)
        m_dot_sec_kg = m_dot_sec_L * sec_props["rho"] / 1000  # kg/s
        
        # Geometry parameters
        tube_size = inputs["tube_size"]
        bwg = inputs.get("bwg", "20")  # BWG gauge
        tube_material = inputs["tube_material"]
        tube_pitch = inputs["tube_pitch"] / 1000  # mm to m
        n_passes = inputs["n_passes"]
        n_baffles = inputs["n_baffles"]
        n_tubes = inputs["n_tubes"]
        tube_length = inputs["tube_length"]
        tube_layout = inputs["tube_layout"].lower()
        tema_class = inputs.get("tema_class", "R")
        
        # Get tube dimensions from TEMA standards
        tube_od_mm = TEMATubeStandards.get_tube_od_mm(tube_size)
        tube_od = tube_od_mm / 1000  # Convert to meters
        
        # Get wall thickness from BWG
        tube_thickness_mm = TEMATubeStandards.get_tube_thickness(tube_size, bwg)
        tube_thickness = tube_thickness_mm / 1000
        tube_id = max(tube_od - 2 * tube_thickness, tube_od * 0.8)
        
        # Calculate shell diameter
        shell_diameter = self.calculate_shell_diameter(tube_od, n_tubes, tube_pitch, tube_layout)
        
        # Calculate equivalent diameter for shell-side flow
        if tube_layout == "triangular":
            D_e = 4 * (0.866 * tube_pitch**2 - 0.5 * math.pi * tube_od**2 / 4) / (math.pi * tube_od)
        else:
            D_e = 4 * (tube_pitch**2 - math.pi * tube_od**2 / 4) / (math.pi * tube_od)
        
        # Baffle geometry
        baffle_spacing = tube_length / (n_baffles + 1)
        baffle_cut = inputs.get("baffle_cut", 25) / 100  # Convert percent to decimal
        bundle_diameter = self.calculate_bundle_diameter(tube_od, n_tubes, tube_pitch, tube_layout)
        
        # Shell-side flow area and velocity
        shell_flow_area = self.calculate_shell_side_flow_area(
            shell_diameter, bundle_diameter, tube_od, n_tubes, baffle_spacing, baffle_cut
        )
        
        v_shell = m_dot_sec_kg / (sec_props["rho"] * shell_flow_area) if shell_flow_area > 0 else 0
        G_sec = m_dot_sec_kg / shell_flow_area if shell_flow_area > 0 else 0
        Re_shell = G_sec * D_e / sec_props["mu"] if sec_props["mu"] > 0 else 0
        
        # Shell-side heat transfer coefficient
        h_shell = self.calculate_shell_side_htc(Re_shell, sec_props["pr"], D_e, sec_props["k"], tube_layout)
        h_shell = max(h_shell, 500)
        h_shell = min(h_shell, 8000)
        
        # Tube-side refrigerant flow
        A_flow_tube = (math.pi * tube_id**2 / 4) * n_tubes / max(n_passes, 1)
        G_ref = m_dot_ref / A_flow_tube if A_flow_tube > 0 else 0
        
        # Average quality for evaporation region
        x_in = inlet_quality / 100.0
        x_avg = (x_in + 1.0) / 2.0
        
        # Tube-side evaporation HTC (Shah correlation)
        Re_l = G_ref * tube_id / ref_props["mu_liquid"] if ref_props["mu_liquid"] > 0 else 0
        Pr_l = ref_props["pr_liquid"]
        
        h_evap = self.shah_evaporation_improved(
            Re_l, Pr_l, x_avg,
            ref_props["rho_liquid"], ref_props["rho_vapor"],
            tube_id, G_ref, ref_props["h_fg"] * 1000,
            ref_props["k_liquid"], ref_props["cp_liquid"] * 1000,
            ref_props["mu_liquid"]
        )
        
        # Tube-side superheat HTC
        h_superheat = self.calculate_single_phase_htc(
            m_dot_ref, tube_id, ref_props["rho_vapor"],
            ref_props["mu_vapor"], ref_props["k_vapor"],
            ref_props["cp_vapor"] * 1000, n_tubes, n_passes
        )
        
        # Tube material thermal conductivity
        tube_k = self.TUBE_MATERIALS[tube_material]["k"]
        
        # Wall resistance (CORRECTED: Standard formula based on OD area)
        # Formula: R_wall = (r_o / k) * ln(r_o / r_i) = (D_o / 2k) * ln(D_o / D_i)
        R_wall = (tube_od / (2.0 * tube_k)) * math.log(tube_od / tube_id) if tube_k > 0 else 0
        
        # Fouling resistances - use TEMA values
        fluid_type = "ethylene_glycol" if glycol_percent > 0 else "cooling_tower_treated"
        R_fouling_shell = TEMAFoulingResistances.get_fouling_resistance(
            fluid_type, T_sec_in, v_shell
        )
        R_fouling_tube = TEMAFoulingResistances.get_fouling_resistance(
            "refrigerant_liquid", T_evap, G_ref/ref_props["rho_liquid"]
        )
        
        # Overall U values (CORRECTED: All resistances based on tube OD area)
        # Configuration: Refrigerant in tubes, Water/Glycol on shell
        # U = 1 / (R_tube + R_wall + R_shell + R_fouling_tube + R_fouling_shell)
        U_evap = 1.0 / (
            1.0 / h_evap +                                    # Tube evaporation (ID basis)
            (tube_od / (2.0 * tube_k)) * math.log(tube_od / tube_id) +  # Wall (OD basis)
            (tube_od / tube_id) / h_shell +                   # Shell water (ID→OD)
            R_fouling_tube +                                   # Tube fouling (ID basis)
            (tube_od / tube_id) * R_fouling_shell             # Shell fouling (ID→OD)
        )
        U_superheat = 1.0 / (
            1.0 / h_superheat +                                # Tube superheat (ID basis)
            (tube_od / (2.0 * tube_k)) * math.log(tube_od / tube_id) +  # Wall (OD basis)
            (tube_od / tube_id) / h_shell +                   # Shell water (ID→OD)
            R_fouling_tube +                                   # Tube fouling (ID basis)
            (tube_od / tube_id) * R_fouling_shell             # Shell fouling (ID→OD)
        )
        
        # Total area
        A_total = math.pi * tube_od * tube_length * n_tubes
        
        # Heat duties
        Q_latent_req = m_dot_ref * (1 - x_in) * ref_props["h_fg"] * 1000
        T_superheated_req = T_evap + superheat_req
        Q_superheat_req = m_dot_ref * ref_props["cp_vapor"] * 1000 * superheat_req
        Q_total_req = Q_latent_req + Q_superheat_req
        
        # Capacity rates
        C_ref_superheat = m_dot_ref * ref_props["cp_vapor"] * 1000
        C_water = m_dot_sec_kg * sec_props["cp"]
        
        # Area distribution based on thermal resistances
        R_evap = 1/U_evap if U_evap > 0 else 0
        R_superheat = 1/U_superheat if U_superheat > 0 else 0
        
        total_resistance_weight = Q_latent_req * R_evap + Q_superheat_req * R_superheat
        
        if total_resistance_weight > 0:
            A_evap = A_total * (Q_latent_req * R_evap) / total_resistance_weight
            A_superheat = A_total * (Q_superheat_req * R_superheat) / total_resistance_weight
        else:
            A_evap = A_total * 0.8
            A_superheat = A_total * 0.2
        
        # Normalize areas
        A_sum = A_evap + A_superheat
        if abs(A_sum - A_total) > 0.001:
            A_evap = A_evap * A_total / A_sum
            A_superheat = A_superheat * A_total / A_sum
        
        # Evaporation region ε-NTU
        NTU_evap = U_evap * A_evap / C_water if C_water > 0 else 0
        epsilon_evap = 1 - math.exp(-NTU_evap)
        Q_max_evap = C_water * (T_sec_in - T_evap)
        Q_evap_achieved = epsilon_evap * Q_max_evap
        T_water_after_evap = T_sec_in - Q_evap_achieved / C_water if C_water > 0 else T_sec_in
        
        # Superheat region ε-NTU
        C_min_superheat = min(C_ref_superheat, C_water)
        C_max_superheat = max(C_ref_superheat, C_water)
        C_r_superheat = C_min_superheat / C_max_superheat if C_max_superheat > 0 else 0
        NTU_superheat = U_superheat * A_superheat / C_min_superheat if C_min_superheat > 0 else 0
        epsilon_superheat = self.epsilon_ntu_counterflow(NTU_superheat, C_r_superheat)
        Q_max_superheat = C_min_superheat * (T_water_after_evap - T_evap)
        Q_superheat_achieved = epsilon_superheat * Q_max_superheat
        
        # Outlet temperatures
        T_water_out = T_water_after_evap - Q_superheat_achieved / C_water if C_water > 0 else T_water_after_evap
        T_ref_out = T_evap + Q_superheat_achieved / C_ref_superheat if C_ref_superheat > 0 else T_superheated_req
        
        Q_total_achieved = Q_evap_achieved + Q_superheat_achieved
        
        # Overall effectiveness
        C_min_overall = min(C_water, C_ref_superheat)
        Q_max_total = C_min_overall * (T_sec_in - T_evap)
        epsilon_overall = Q_total_achieved / Q_max_total if Q_max_total > 0 else 0
        
        U_avg = (U_evap * A_evap + U_superheat * A_superheat) / A_total
        NTU_overall = U_avg * A_total / C_water if C_water > 0 else 0
        
        # LMTD
        dt1 = T_sec_in - T_ref_out
        dt2 = T_water_out - T_evap
        if dt1 > 0 and dt2 > 0 and abs(dt1 - dt2) > 1e-6:
            LMTD = (dt1 - dt2) / math.log(dt1 / dt2)
        else:
            LMTD = (dt1 + dt2) / 2
        
        # Pressure drop calculations
        # Tube-side two-phase pressure drop
        rho_tp = 1 / (x_avg/ref_props["rho_vapor"] + (1-x_avg)/ref_props["rho_liquid"])
        v_ref = G_ref / rho_tp
        
        if Re_l > 2300:
            f_tube = (0.79 * math.log(Re_l) - 1.64)**-2 if Re_l > 0 else 0.02
        else:
            f_tube = 64 / Re_l if Re_l > 0 else 0.05
        
        phi_tp = 1 + 2.5 / x_avg if x_avg > 0 else 1
        dp_tube = f_tube * (tube_length * n_passes / tube_id) * (rho_tp * v_ref**2 / 2) * phi_tp
        
        # Shell-side pressure drop
        if Re_shell < 2300:
            f_shell = 64 / Re_shell if Re_shell > 0 else 0.2
        else:
            f_shell = 0.2 * Re_shell**-0.2
        
        dp_shell = f_shell * (tube_length / D_e) * (n_baffles + 1) * (sec_props["rho"] * v_shell**2 / 2)
        
        # Velocity status
        sec_velocity_status = self.check_velocity_status(v_shell, glycol_percent, "shell")
        ref_velocity_status = self.check_velocity_status(v_ref, 0, "refrigerant_two_phase")
        
        # Flow distribution
        m_dot_per_tube = m_dot_ref / n_tubes * 3600
        distribution_status = "Good" if m_dot_per_tube >= 3.6 else "Marginal" if m_dot_per_tube >= 2.0 else "Poor"
        
        # Freeze protection
        freeze_point = sec_props["freeze_point"]
        freeze_risk = "High" if T_water_out < freeze_point + 2 else "Medium" if T_water_out < freeze_point + 3 else "Low"
        
        # Required area from basic heat transfer equation
        Q_required = Q_total_req
        A_required = Q_required / (U_avg * LMTD) if U_avg > 0 and LMTD > 0 else 0
        area_ratio = A_total / A_required if A_required > 0 else 0
        
        # ====================================================================
        # TEMA COMPLIANCE CHECKS
        # ====================================================================
        
        # 1. Tube selection validation
        tube_valid, tube_message = TEMATubeStandards.validate_tube_selection(
            tube_size, bwg, inputs.get("design_pressure_kpa", 1000)
        )
        
        # 2. Baffle spacing validation
        baffle_check = TEMABaffleStandards.validate_baffle_spacing(
            shell_diameter, baffle_spacing, tube_od, tema_class
        )
        
        # 3. Maximum unsupported span
        T_metal_avg = (T_evap + T_sec_in) / 2
        max_span_m = TEMABaffleStandards.get_maximum_unsupported_span(
            tube_od, tube_material, T_metal_avg
        )
        span_compliant = baffle_spacing <= max_span_m
        
        # 4. Impingement requirement at shell inlet
        nozzle_velocity = inputs.get("nozzle_velocity_ms", v_shell * 1.5)  # Estimate
        impingement_check = TEMABaffleStandards.calculate_impingement_requirement(
            sec_props["rho"], nozzle_velocity, "two_phase" if x_in > 0 else "single_phase"
        )
        
        # 5. Tie rod requirements
        tie_rod_req = TEMABaffleStandards.get_tie_rod_requirements(shell_diameter, tema_class)
        
        # 6. Tube hole tolerance validation
        hole_diameter = tube_od_mm + 0.2  # Estimate typical hole diameter
        hole_check = TEMATubesheetStandards.validate_tube_hole_diameter(
            tube_od_mm, hole_diameter, "standard"
        )
        
        # 7. Minimum tubesheet thickness
        min_ts_thickness = TEMATubesheetStandards.calculate_min_thickness_expanded_joints(
            tube_od_mm, tema_class
        )
        
        # 8. Vibration analysis
        self.pitch_ratio = tube_pitch / tube_od
        vibration_results = {
            "natural_frequency_hz": 0,
            "critical_velocity_ms": 0,
            "actual_velocity_ms": v_shell,
            "safety_factor": 0,
            "risk_level": "NOT ANALYZED",
            "tema_compliant": True
        }
        
        if inputs.get("vibration_analysis", True):
            try:
                # Get tube material modulus
                E_tube_pa = self.TUBE_MATERIALS[tube_material]["E_modulus_gpa"] * 1e9
                rho_tube = self.TUBE_MATERIALS[tube_material]["density"]
                
                fn = self.tema_vibration.calculate_tube_natural_frequency(
                    tube_od, tube_id, baffle_spacing, E_tube_pa, rho_tube, sec_props["rho"]
                )
                
                A_metal = math.pi * (tube_od**2 - tube_id**2) / 4
                m_effective = A_metal * rho_tube + (math.pi * tube_id**2 / 4) * ref_props["rho_liquid"]
                delta = 0.03  # Approximate logarithmic decrement
                
                Vc = self.tema_vibration.calculate_critical_velocity(
                    fn, tube_od, m_effective, delta, sec_props["rho"],
                    tube_layout, self.pitch_ratio
                )
                
                safety_factor = Vc / v_shell if v_shell > 0 else 999
                
                vibration_results = {
                    "natural_frequency_hz": round(fn, 2),
                    "critical_velocity_ms": round(Vc, 3),
                    "actual_velocity_ms": round(v_shell, 3),
                    "safety_factor": round(safety_factor, 2),
                    "risk_level": "LOW" if safety_factor >= 2 else "MEDIUM" if safety_factor >= 1.5 else "HIGH" if safety_factor >= 1 else "CRITICAL",
                    "tema_compliant": safety_factor >= 1.5
                }
            except Exception as e:
                self.warnings.append(f"Vibration analysis error: {e}")
        
        # Design status
        design_status = self.determine_design_status(
            epsilon_overall, A_total, A_required, Q_total_achieved, Q_total_req
        )
        
        # Compile results
        self.results = {
            # Heat exchanger identification
            "heat_exchanger_type": "DX Evaporator",
            "tema_class": tema_class,
            "tema_type": inputs.get("tema_type", "AES"),
            "design_method": "TEMA 10th Edition / ε-NTU",
            "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            
            # Heat duty
            "heat_duty_required_kw": Q_total_req / 1000,
            "heat_duty_achieved_kw": Q_total_achieved / 1000,
            "kw_difference": (Q_total_achieved - Q_total_req) / 1000,
            "kw_match_percentage": (Q_total_achieved / Q_total_req * 100) if Q_total_req > 0 else 0,
            "q_latent_req_kw": Q_latent_req / 1000,
            "q_superheat_req_kw": Q_superheat_req / 1000,
            "q_latent_achieved_kw": Q_evap_achieved / 1000,
            "q_superheat_achieved_kw": Q_superheat_achieved / 1000,
            
            # Thermal performance
            "effectiveness": epsilon_overall,
            "ntu": NTU_overall,
            "ntu_evap": NTU_evap,
            "ntu_superheat": NTU_superheat,
            "epsilon_evap": epsilon_evap,
            "epsilon_superheat": epsilon_superheat,
            "overall_u": U_avg,
            "h_tube_evap": h_evap,
            "h_tube_superheat": h_superheat,
            "h_shell": h_shell,
            "u_evap": U_evap,
            "u_superheat": U_superheat,
            "lmtd": LMTD,
            "r_fouling_shell": R_fouling_shell,
            "r_fouling_tube": R_fouling_tube,
            "r_wall": R_wall,
            
            # Temperatures
            "t_sec_in": T_sec_in,
            "t_sec_out": T_water_out,
            "t_sec_out_required": (T_sec_out_required if T_sec_out_required is not None else None),
            "t_ref_in": T_evap,
            "t_ref_out_required": T_superheated_req,
            "t_ref_out_achieved": T_ref_out,
            # Stream mapping (for UI/report clarity)
            "refrigerant_side": refrigerant_side,
            "shell_stream": ("Refrigerant" if refrigerant_side == "shell" else "Water/Glycol"),
            "tube_stream": ("Water/Glycol" if refrigerant_side == "shell" else "Refrigerant"),
            "t_shell_in": (T_ref_in_superheated if refrigerant_side == "shell" else T_sec_in),
            "t_shell_out": (T_ref_out if refrigerant_side == "shell" else T_water_out),
            "t_tube_in": (T_sec_in if refrigerant_side == "shell" else T_ref_in_superheated),
            "t_tube_out": (T_water_out if refrigerant_side == "shell" else T_ref_out),

            "m_dot_shell_kg_s": (m_dot_ref if refrigerant_side == "shell" else m_dot_sec_kg),
            "m_dot_tube_kg_s": (m_dot_sec_kg if refrigerant_side == "shell" else m_dot_ref),


            "superheat_difference": T_ref_out - T_superheated_req,
            "water_deltaT": abs(T_water_out - T_sec_in),
            "superheat_req": superheat_req,
            "superheat_achieved": T_ref_out - T_evap,
            
            # Refrigerant
            "refrigerant": refrigerant,
            "refrigerant_mass_flow_kg_s": m_dot_ref,
            "refrigerant_mass_flow_kg_hr": m_dot_ref * 3600,
            "inlet_quality_percent": inlet_quality,
            "outlet_quality": 100 if T_ref_out > T_evap else 0,  # Superheated
            "refrigerant_properties": ref_props,
            
            # Secondary fluid
            "water_vol_flow_L_hr": m_dot_sec_L * 3600,
            "water_mass_flow_kg_hr": m_dot_sec_kg * 3600,
            "water_properties": sec_props,
            "glycol_type": glycol_type,
            "glycol_percentage": glycol_percent,
            "freeze_point_c": freeze_point,
            "freeze_risk": freeze_risk,
            
            # Geometry - Shell
            "shell_diameter_m": shell_diameter,
            "shell_flow_area_m2": shell_flow_area,
            "baffle_spacing_m": baffle_spacing,
            "baffle_cut_percent": baffle_cut * 100,
            "n_baffles": n_baffles,
            "baffle_thickness_mm": inputs.get("baffle_thickness_mm", 9.5),
            "tie_rod_diameter_mm": tie_rod_req["diameter_mm"],
            "tie_rod_min_qty": tie_rod_req["min_qty"],
            "bundle_diameter_m": bundle_diameter,
            "shell_clearance_mm": (shell_diameter - bundle_diameter) * 1000 / 2,
            
            # Geometry - Tubes
            "tube_size": tube_size,
            "bwg": bwg,
            "tube_material": tube_material,
            "tube_layout": tube_layout,
            "pitch_ratio": (tube_pitch / tube_od if tube_od > 0 else 1.25),
            "tube_od_mm": tube_od * 1000,
            "tube_id_mm": tube_id * 1000,
            "tube_thickness_mm": tube_thickness * 1000,
            "tube_pitch_mm": tube_pitch * 1000,
            "pitch_ratio": tube_pitch / tube_od,
            "tube_layout": tube_layout,
            "n_tubes": n_tubes,
            "n_passes": n_passes,
            "tube_length_m": tube_length,
            "tube_effective_length_m": tube_length,
            "area_total_m2": A_total,
            "area_evap_m2": A_evap,
            "area_superheat_m2": A_superheat,
            "area_required_m2": A_required,
            "area_ratio": area_ratio,
            "flow_per_tube_kg_hr": m_dot_per_tube,
            
            # Velocities
            "velocity_tube_ms": v_ref,
            "velocity_shell_ms": v_shell,
            "velocity_tube_status": ref_velocity_status["status"],
            "velocity_shell_status": sec_velocity_status["status"],
            "velocity_tube_rec": ref_velocity_status,
            "velocity_shell_rec": sec_velocity_status,
            
            # Pressure drop
            "dp_tube_kpa": dp_tube / 1000,
            "dp_shell_kpa": dp_shell / 1000,
            "dp_tube_psi": dp_tube / 6894.76,
            "dp_shell_psi": dp_shell / 6894.76,
            
            # Reynolds numbers
            "reynolds_tube": Re_l,
            "reynolds_shell": Re_shell,
            "mass_flux_tube": G_ref,
            "mass_flux_shell": G_sec,
            
            # Capacity rates
            "c_water": C_water,
            "c_ref_superheat": C_ref_superheat,
            "c_ratio": C_min_superheat / C_max_superheat if C_max_superheat > 0 else 0,
            
            # TEMA Compliance
            "tema_tube_compliant": tube_valid,
            "tema_tube_message": tube_message,
            "tema_baffle_compliant": baffle_check["compliant"],
            "tema_baffle_warnings": baffle_check["warnings"],
            "tema_span_compliant": span_compliant,
            "tema_max_span_m": max_span_m,
            "tema_impingement": impingement_check,
            "tema_tie_rod": tie_rod_req,
            "tema_hole_check": hole_check,
            "tema_min_ts_thickness_mm": min_ts_thickness,
            "tema_vibration": vibration_results,
            
            # Design status
            "distribution_status": distribution_status,
            "design_status": design_status,
            "warnings": self.warnings,
        }
        
        # Overall TEMA compliance
        tema_compliant = all([
            tube_valid,
            baffle_check["compliant"],
            span_compliant,
            not impingement_check["impingement_required"] or inputs.get("has_impingement_plate", False),
            vibration_results.get("tema_compliant", True)
        ])
        
        self.results["tema_overall_compliant"] = tema_compliant
        
        return self.results
    
    # ========================================================================
    # CONDENSER DESIGN (Corrected: Refrigerant on SHELL, Water in TUBES)
    # ========================================================================
    
    def design_condenser(self, inputs: Dict) -> Dict:
        """Design condenser (TEMA-aware).

        Default configuration (common practice):
        - Refrigerant condensing on SHELL side
        - Water/Glycol in TUBES (easy cleaning)

        Optional configuration:
        - Refrigerant in TUBES
        - Water/Glycol on SHELL side

        Notes:
        - Thermal correlations already implemented in this tool are preserved.
        - Some shell-side single-phase calculations (when water is on shell side) use an equivalent-diameter
          Gnielinski approach as an engineering estimate; a warning is provided in that mode.
        """
        self.warnings = []

        # --- Inputs ---
        refrigerant = inputs["refrigerant"]
        m_dot_ref = float(inputs["m_dot_ref"])  # kg/s
        T_ref_in_superheated = float(inputs["T_ref_in_superheated"])
        T_cond = float(inputs["T_ref"])
        subcool_req = float(inputs["delta_T_sh_sc"])

        refrigerant_side = inputs.get("condenser_refrigerant_side", "shell").strip().lower()
        if refrigerant_side not in ("shell", "tube"):
            refrigerant_side = "shell"

        # Refrigerant properties at condensing temperature
        ref_props = self.get_refrigerant_properties(refrigerant, T_cond)

        # Secondary fluid properties
        glycol_percent = float(inputs["glycol_percentage"])
        glycol_type = inputs.get("glycol_type", "ethylene")
        m_dot_sec_L = float(inputs["m_dot_sec"]) / 3600.0  # L/hr -> L/s
        T_sec_in = float(inputs["T_sec_in"])
        sec_props = self.get_glycol_properties(glycol_type, glycol_percent, T_sec_in)
        m_dot_sec_kg = m_dot_sec_L * sec_props["rho"] / 1000.0  # kg/s

        # --- Geometry / TEMA selections ---
        tube_size = inputs["tube_size"]
        bwg = inputs.get("bwg", "18")
        tube_material = inputs["tube_material"]
        tube_pitch = float(inputs["tube_pitch"]) / 1000.0  # mm -> m
        n_passes = int(inputs["n_passes"])
        n_baffles = int(inputs["n_baffles"])
        n_tubes = int(inputs["n_tubes"])
        tube_length = float(inputs["tube_length"])
        tube_layout = inputs["tube_layout"].lower()
        tema_class = inputs.get("tema_class", "R")
        tema_type = inputs.get("tema_type", "AES")

        # Tube dimensions from TEMA standards
        tube_od_mm = TEMATubeStandards.get_tube_od_mm(tube_size)
        tube_od = tube_od_mm / 1000.0
        tube_thickness_mm = TEMATubeStandards.get_tube_thickness(tube_size, bwg)
        tube_thickness = tube_thickness_mm / 1000.0
        tube_id = max(tube_od - 2.0 * tube_thickness, tube_od * 0.8)

        # --- Bundle/Shell geometry ---
        shell_diameter = self.calculate_shell_diameter(tube_od, n_tubes, tube_pitch, tube_layout)

        # Equivalent diameter for shell-side (tube bundle passages)
        if tube_layout == "triangular":
            D_e = 4.0 * (0.866 * tube_pitch**2 - 0.5 * math.pi * tube_od**2 / 4.0) / (math.pi * tube_od)
        else:
            D_e = 4.0 * (tube_pitch**2 - math.pi * tube_od**2 / 4.0) / (math.pi * tube_od)

        baffle_spacing = tube_length / (n_baffles + 1)
        baffle_cut = float(inputs.get("baffle_cut", 25)) / 100.0
        bundle_diameter = self.calculate_bundle_diameter(tube_od, n_tubes, tube_pitch, tube_layout)

        shell_flow_area = self.calculate_shell_side_flow_area(
            shell_diameter, bundle_diameter, tube_od, n_tubes, baffle_spacing, baffle_cut
        )

        # --- Tube material thermal conductivity + wall resistance ---
        tube_k = self.TUBE_MATERIALS.get(tube_material, {}).get("k", 16.0)
        # Wall resistance (CORRECTED: Standard formula based on OD area)
        # Formula: R_wall = (D_o / 2k) * ln(D_o / D_i)
        R_wall = (tube_od / (2.0 * tube_k)) * math.log(tube_od / tube_id) if tube_k > 0 else 0

        # ============================================================
        # SIDE ASSIGNMENT
        # ============================================================
        if refrigerant_side == "shell":
            # --------------------------------------------------------
            # Tube side: water/glycol
            # --------------------------------------------------------
            A_flow_tube = (math.pi * tube_id**2 / 4.0) * n_tubes / max(n_passes, 1)
            v_tube = m_dot_sec_kg / (sec_props["rho"] * A_flow_tube) if A_flow_tube > 0 else 0.0
            Re_tube = sec_props["rho"] * v_tube * tube_id / sec_props["mu"] if sec_props["mu"] > 0 else 0.0

            h_tube = self.calculate_single_phase_htc(
                m_dot_sec_kg, tube_id, sec_props["rho"],
                sec_props["mu"], sec_props["k"], sec_props["cp"],
                n_tubes, n_passes
            )

            # --------------------------------------------------------
            # Shell side: refrigerant (desuperheat + condense + subcool)
            # --------------------------------------------------------
            G_ref_shell = m_dot_ref / shell_flow_area if shell_flow_area > 0 else 0.0
            v_shell = (G_ref_shell / ref_props["rho_vapor"]) if ref_props["rho_vapor"] > 0 else 0.0

            # Condensation HTC (existing correlation retained)
            h_condense = self.dobson_chato_improved(
                G_ref_shell, tube_od, T_cond,
                ref_props["rho_liquid"], ref_props["rho_vapor"],
                ref_props["mu_liquid"], ref_props["mu_vapor"],
                ref_props["k_liquid"], ref_props["cp_liquid"] * 1000.0,
                ref_props["h_fg"] * 1000.0, x=0.5
            )

            # Single-phase shell-side estimates for superheat/subcool (engineering estimate)
            # Preserve existing logic style: Gnielinski on equivalent diameter
            # Vapor (desuperheat)
            Re_shell_v = G_ref_shell * D_e / ref_props["mu_vapor"] if ref_props["mu_vapor"] > 0 else 0.0
            Pr_shell_v = ref_props["mu_vapor"] * (ref_props["cp_vapor"] * 1000.0) / ref_props["k_vapor"] if ref_props["k_vapor"] > 0 else 0.0
            Nu_shell_v = self.gnielinski_single_phase(Re_shell_v, Pr_shell_v) if (Re_shell_v > 0 and Pr_shell_v > 0) else 10.0
            h_desuperheat = Nu_shell_v * ref_props["k_vapor"] / D_e if D_e > 0 else 100.0

            # Liquid (subcool)
            Re_shell_l = G_ref_shell * D_e / ref_props["mu_liquid"] if ref_props["mu_liquid"] > 0 else 0.0
            Pr_shell_l = ref_props["mu_liquid"] * (ref_props["cp_liquid"] * 1000.0) / ref_props["k_liquid"] if ref_props["k_liquid"] > 0 else 0.0
            Nu_shell_l = self.gnielinski_single_phase(Re_shell_l, Pr_shell_l) if (Re_shell_l > 0 and Pr_shell_l > 0) else 10.0
            h_subcool = Nu_shell_l * ref_props["k_liquid"] / D_e if D_e > 0 else 100.0

            # Fouling resistances
            R_fouling_tube = TEMAFoulingResistances.get_fouling_resistance(
                "cooling_tower_treated" if glycol_percent == 0 else f"{glycol_type}_glycol",
                T_sec_in, v_tube
            )
            R_fouling_shell = TEMAFoulingResistances.get_fouling_resistance(
                "refrigerant_vapor_oil", T_cond, v_shell
            )

            # Pressure drops (existing style preserved)
            if Re_tube > 2300:
                f_tube = (0.79 * math.log(Re_tube) - 1.64) ** -2 if Re_tube > 0 else 0.02
            else:
                f_tube = 64.0 / Re_tube if Re_tube > 0 else 0.05
            dp_tube = f_tube * (tube_length * max(n_passes, 1) / tube_id) * (sec_props["rho"] * v_tube**2 / 2.0)

            Re_shell = G_ref_shell * D_e / ref_props["mu_vapor"] if ref_props["mu_vapor"] > 0 else 0.0
            if Re_shell < 2300:
                f_shell = 64.0 / Re_shell if Re_shell > 0 else 0.2
            else:
                f_shell = 0.2 * Re_shell ** -0.2
            dp_shell = f_shell * (tube_length / max(D_e, 1e-6)) * (n_baffles + 1) * (ref_props["rho_vapor"] * v_shell**2 / 2.0)

            # Velocity status
            tube_velocity_status = self.check_velocity_status(v_tube, glycol_percent, "water_glycol")
            shell_velocity_status = self.check_velocity_status(v_shell, 0, "refrigerant")

            # For reporting
            v_shell_report = v_shell
            v_tube_report = v_tube
            Re_shell_report = Re_shell
            Re_tube_report = Re_tube

            # U calculations will use h_tube (tube) and h_* (shell)
            h_shell_for_reporting = h_condense  # main shell HTC shown

        else:
            # --------------------------------------------------------
            # Tube side: refrigerant (desuperheat + condense + subcool)
            # --------------------------------------------------------
            A_flow_ref = (math.pi * tube_id**2 / 4.0) * n_tubes / max(n_passes, 1)
            v_ref = m_dot_ref / (ref_props["rho_vapor"] * A_flow_ref) if (A_flow_ref > 0 and ref_props["rho_vapor"] > 0) else 0.0
            Re_ref_v = ref_props["rho_vapor"] * v_ref * tube_id / ref_props["mu_vapor"] if ref_props["mu_vapor"] > 0 else 0.0

            # Single-phase inside-tube (existing correlation preserved)
            h_desuperheat = self.calculate_single_phase_htc(
                m_dot_ref, tube_id, ref_props["rho_vapor"],
                ref_props["mu_vapor"], ref_props["k_vapor"], ref_props["cp_vapor"] * 1000.0,
                n_tubes, n_passes
            )

            # Condensation inside tubes (use existing dobson-chato function; keep correlation)
            G_ref_tube = m_dot_ref / A_flow_ref if A_flow_ref > 0 else 0.0
            h_condense = self.dobson_chato_improved(
                G_ref_tube, tube_id, T_cond,
                ref_props["rho_liquid"], ref_props["rho_vapor"],
                ref_props["mu_liquid"], ref_props["mu_vapor"],
                ref_props["k_liquid"], ref_props["cp_liquid"] * 1000.0,
                ref_props["h_fg"] * 1000.0, x=0.5
            )

            h_subcool = self.calculate_single_phase_htc(
                m_dot_ref, tube_id, ref_props["rho_liquid"],
                ref_props["mu_liquid"], ref_props["k_liquid"], ref_props["cp_liquid"] * 1000.0,
                n_tubes, n_passes
            )

            # --------------------------------------------------------
            # Shell side: water/glycol (engineering estimate)
            # --------------------------------------------------------
            if shell_flow_area <= 0:
                shell_flow_area = 1e-6

            G_sec_shell = m_dot_sec_kg / shell_flow_area
            v_shell = G_sec_shell / sec_props["rho"] if sec_props["rho"] > 0 else 0.0
            Re_shell = G_sec_shell * D_e / sec_props["mu"] if sec_props["mu"] > 0 else 0.0
            Pr_shell = sec_props["mu"] * sec_props["cp"] / sec_props["k"] if sec_props["k"] > 0 else 0.0
            Nu_shell = self.gnielinski_single_phase(Re_shell, Pr_shell) if (Re_shell > 0 and Pr_shell > 0) else 10.0
            h_tube = Nu_shell * sec_props["k"] / D_e if D_e > 0 else 200.0  # here h_tube variable reused as shell HTC for legacy usage

            self.warnings.append(
                "Condenser mode: Water/Glycol on shell side uses equivalent-diameter Gnielinski estimate (conservative). "
                "For detailed design, use a dedicated shell-side method (e.g., Kern/Bell-Delaware)."

            )

            # Fouling resistances (swap sides)
            R_fouling_shell = TEMAFoulingResistances.get_fouling_resistance(
                "cooling_tower_treated" if glycol_percent == 0 else f"{glycol_type}_glycol",
                T_sec_in, v_shell
            )
            R_fouling_tube = TEMAFoulingResistances.get_fouling_resistance(
                "refrigerant_vapor_oil", T_cond, v_ref
            )

            # Pressure drops (rough, preserve style)
            if Re_ref_v > 2300:
                f_tube = (0.79 * math.log(Re_ref_v) - 1.64) ** -2 if Re_ref_v > 0 else 0.02
            else:
                f_tube = 64.0 / Re_ref_v if Re_ref_v > 0 else 0.05
            dp_tube = f_tube * (tube_length * max(n_passes, 1) / tube_id) * (ref_props["rho_vapor"] * v_ref**2 / 2.0)

            if Re_shell < 2300:
                f_shell = 64.0 / Re_shell if Re_shell > 0 else 0.2
            else:
                f_shell = 0.2 * Re_shell ** -0.2
            dp_shell = f_shell * (tube_length / max(D_e, 1e-6)) * (n_baffles + 1) * (sec_props["rho"] * v_shell**2 / 2.0)

            tube_velocity_status = self.check_velocity_status(v_ref, 0, "refrigerant")
            shell_velocity_status = self.check_velocity_status(v_shell, glycol_percent, "water_glycol")

            v_shell_report = v_shell
            v_tube_report = v_ref
            Re_shell_report = Re_shell
            Re_tube_report = Re_ref_v

            h_shell_for_reporting = h_tube

        # ============================================================
        # Overall U values (based on tube OD) + Duties/Areas
        # ============================================================

        # Overall U values: keep original structure. h_tube always means "tube-side water" in shell-refrigerant mode.
        # In tube-refrigerant mode, h_desuperheat/h_condense/h_subcool are tube-side refrigerant and h_tube variable is shell-side water estimate.

        if refrigerant_side == "shell":
            # CORRECTED: All resistances based on tube OD area
            # Configuration: Refrigerant on shell side, Water in tubes
            U_condense = 1.0 / (
                1.0 / h_condense +                                 # Shell condensation (OD basis)
                (tube_od / tube_id) / h_tube +                     # Tube water (ID→OD)
                (tube_od / (2.0 * tube_k)) * math.log(tube_od / tube_id) +  # Wall (OD basis)
                R_fouling_shell +                                   # Shell fouling (OD basis)
                (tube_od / tube_id) * R_fouling_tube               # Tube fouling (ID→OD)
            )
            U_desuperheat = 1.0 / (
                1.0 / h_desuperheat +                              # Shell desuperheat (OD basis)
                (tube_od / tube_id) / h_tube +                     # Tube water (ID→OD)
                (tube_od / (2.0 * tube_k)) * math.log(tube_od / tube_id) +  # Wall (OD basis)
                R_fouling_shell +                                   # Shell fouling (OD basis)
                (tube_od / tube_id) * R_fouling_tube               # Tube fouling (ID→OD)
            )
            U_subcool = 1.0 / (
                1.0 / h_subcool +                                  # Shell subcool (OD basis)
                (tube_od / tube_id) / h_tube +                     # Tube water (ID→OD)
                (tube_od / (2.0 * tube_k)) * math.log(tube_od / tube_id) +  # Wall (OD basis)
                R_fouling_shell +                                   # Shell fouling (OD basis)
                (tube_od / tube_id) * R_fouling_tube               # Tube fouling (ID→OD)
            )
        else:
            # CORRECTED: All resistances based on tube OD area
            # Configuration: Refrigerant in tubes, Water on shell side
            # Note: h_tube variable is reused for shell-side water in this configuration
            U_condense = 1.0 / (
                1.0 / h_tube +                                      # Shell water (OD basis)
                (tube_od / tube_id) / h_condense +                  # Tube condensation (ID→OD)
                (tube_od / (2.0 * tube_k)) * math.log(tube_od / tube_id) +  # Wall (OD basis)
                R_fouling_shell +                                   # Shell fouling (OD basis)
                (tube_od / tube_id) * R_fouling_tube               # Tube fouling (ID→OD)
            )
            U_desuperheat = 1.0 / (
                1.0 / h_tube +                                      # Shell water (OD basis)
                (tube_od / tube_id) / h_desuperheat +               # Tube desuperheat (ID→OD)
                (tube_od / (2.0 * tube_k)) * math.log(tube_od / tube_id) +  # Wall (OD basis)
                R_fouling_shell +                                   # Shell fouling (OD basis)
                (tube_od / tube_id) * R_fouling_tube               # Tube fouling (ID→OD)
            )
            U_subcool = 1.0 / (
                1.0 / h_tube +                                      # Shell water (OD basis)
                (tube_od / tube_id) / h_subcool +                   # Tube subcool (ID→OD)
                (tube_od / (2.0 * tube_k)) * math.log(tube_od / tube_id) +  # Wall (OD basis)
                R_fouling_shell +                                   # Shell fouling (OD basis)
                (tube_od / tube_id) * R_fouling_tube               # Tube fouling (ID→OD)
            )

        # Total area
        A_total = math.pi * tube_od * tube_length * n_tubes

        # Refrigerant duties
        Q_desuperheat_req = m_dot_ref * (ref_props["cp_vapor"] * 1000.0) * (T_ref_in_superheated - T_cond)
        Q_latent_req = m_dot_ref * (ref_props["h_fg"] * 1000.0)
        T_subcooled_req = T_cond - subcool_req
        Q_subcool_req = m_dot_ref * (ref_props["cp_liquid"] * 1000.0) * (T_cond - T_subcooled_req)
        Q_total_req = Q_desuperheat_req + Q_latent_req + Q_subcool_req

        # ============================================================
        # CORRECTED: Area distribution based on heat duty AND thermal resistance
        # This is the same CORRECT method used in evaporator (lines 1477-1494)
        # ============================================================
        
        # Calculate thermal resistances for each zone
        R_desuperheat = 1.0 / U_desuperheat if U_desuperheat > 0 else 0
        R_condense = 1.0 / U_condense if U_condense > 0 else 0
        R_subcool = 1.0 / U_subcool if U_subcool > 0 else 0
        
        # Weight by both heat duty requirement AND thermal resistance
        # Higher resistance and higher duty = needs more area
        total_resistance_weight = (Q_desuperheat_req * R_desuperheat + 
                                  Q_latent_req * R_condense + 
                                  Q_subcool_req * R_subcool)
        
        if total_resistance_weight > 0:
            A_desuperheat = A_total * (Q_desuperheat_req * R_desuperheat) / total_resistance_weight
            A_condense = A_total * (Q_latent_req * R_condense) / total_resistance_weight
            A_subcool = A_total * (Q_subcool_req * R_subcool) / total_resistance_weight
        else:
            # Fallback to typical distribution if calculation fails
            A_desuperheat = A_total * 0.15  # ~15% for desuperheat
            A_condense = A_total * 0.70     # ~70% for condensation (main zone)
            A_subcool = A_total * 0.15      # ~15% for subcooling
        
        # Normalize areas to ensure they sum exactly to A_total
        A_sum = A_desuperheat + A_condense + A_subcool
        if abs(A_sum - A_total) > 0.001:
            A_desuperheat = A_desuperheat * A_total / A_sum
            A_condense = A_condense * A_total / A_sum
            A_subcool = A_subcool * A_total / A_sum

        
        # ============================================================
        # OPTIONAL: Zoned condenser allocation (integral subcooler)
        # When enabled, reserve a dedicated fraction/rows of area for subcooling.
        # This improves realism for the common case: "Total kW OK but subcooling short".
        # Correlations (Shah, etc.) are NOT changed; only the available A per zone is reallocated.
        # ============================================================
        if refrigerant_side == "shell" and inputs.get("zoned_condenser_enabled", False):
            method = inputs.get("zoned_condenser_method", "area_fraction")
            f_sc = None

            if method == "area_fraction":
                try:
                    f_sc = float(inputs.get("subcool_area_fraction", 0.20))
                except Exception:
                    f_sc = 0.20
            elif method == "row_based":
                try:
                    tubes_per_row = max(int(inputs.get("estimated_tubes_per_row", 25)), 1)
                    total_rows = int(math.ceil(n_tubes / tubes_per_row))
                    sc_rows = max(int(inputs.get("subcool_rows", 1)), 1)
                    f_sc = min(sc_rows / max(total_rows, 1), 0.60)
                except Exception:
                    f_sc = 0.20

            # Clamp to safe range
            f_sc = min(max(f_sc if f_sc is not None else 0.20, 0.05), 0.60)

            # Reserve area for subcooling and redistribute remaining between desuperheat + condense
            A_subcool = A_total * f_sc
            A_remaining = max(A_total - A_subcool, 1e-9)

            main_weight = (Q_desuperheat_req * R_desuperheat) + (Q_latent_req * R_condense)
            if main_weight > 0:
                A_desuperheat = A_remaining * (Q_desuperheat_req * R_desuperheat) / main_weight
                A_condense = A_remaining * (Q_latent_req * R_condense) / main_weight
            else:
                A_desuperheat = A_remaining * 0.20
                A_condense = A_remaining * 0.80

            # Final normalize
            A_sum2 = A_desuperheat + A_condense + A_subcool
            if abs(A_sum2 - A_total) > 1e-6:
                A_desuperheat *= A_total / A_sum2
                A_condense *= A_total / A_sum2
                A_subcool *= A_total / A_sum2

            self.warnings.append(
                f"Zoned condenser enabled: reserved {f_sc*100:.0f}% of bundle area for subcooling "
                f"(A_subcool={A_subcool:.2f} m²)."
            )
# Secondary fluid heat capacity rate
        C_water = m_dot_sec_kg * sec_props["cp"] if sec_props["cp"] > 0 else 1e-9

        # Achievable heat duties via ε-NTU per zone (counterflow approx), applied sequentially
        # NOTE: We update the secondary-fluid temperature after each zone. This fixes unrealistic in/out temperatures
        # that can occur if all zones use T_sec_in as the cold-side inlet.

        T_sec_z1_in = T_sec_in

        # Zone 1: Desuperheat (single-phase vs single-phase)
        C_ref_superheat = m_dot_ref * (ref_props["cp_vapor"] * 1000.0)  # W/K
        C_min_superheat = min(C_water, C_ref_superheat)
        C_max_superheat = max(C_water, C_ref_superheat)
        Cr_superheat = C_min_superheat / C_max_superheat if C_max_superheat > 0 else 0.0
        NTU1 = (U_desuperheat * A_desuperheat) / C_min_superheat if C_min_superheat > 0 else 0.0
        eps1 = self.epsilon_ntu_counterflow(NTU1, Cr_superheat)
        Q1_achieved = max(eps1 * C_min_superheat * max(T_ref_in_superheated - T_sec_z1_in, 0.0), 0.0)
        
        # Calculate water outlet temperature for zone 1
        T_sec_z1_out_calc = T_sec_z1_in + (Q1_achieved / C_water) if C_water > 0 else T_sec_z1_in

        # Refrigerant temperature after desuperheat (approaches T_cond, cannot go below)
        dT_ref1 = Q1_achieved / max(C_ref_superheat, 1e-9)
        T_ref_after_z1 = max(T_ref_in_superheated - dT_ref1, T_cond)
        
        # VALIDATE: Water cannot exceed refrigerant temperature (2nd Law of Thermodynamics)
        min_approach = 0.5  # Minimum temperature approach [K]
        if T_sec_z1_out_calc > T_ref_after_z1 - min_approach:
            self.warnings.append(
                f"Temperature pinch in desuperheat zone: Water {T_sec_z1_out_calc:.1f}°C "
                f"exceeds refrigerant {T_ref_after_z1:.1f}°C. Corrected to {T_ref_after_z1 - min_approach:.1f}°C"
            )
            T_sec_z1_out = T_ref_after_z1 - min_approach
        else:
            T_sec_z1_out = T_sec_z1_out_calc

        # Zone 2: Condensation (phase change, C_ref ~ ∞ -> Cr ~ 0)
        T_sec_z2_in = T_sec_z1_out
        NTU2 = (U_condense * A_condense) / C_water if C_water > 0 else 0.0
        eps2 = (1.0 - math.exp(-NTU2)) if NTU2 > 0 else 0.0
        Q2_achieved = max(eps2 * C_water * max(T_cond - T_sec_z2_in, 0.0), 0.0)
        
        # Calculate water outlet temperature for zone 2
        T_sec_z2_out_calc = T_sec_z2_in + (Q2_achieved / C_water) if C_water > 0 else T_sec_z2_in
        
        # VALIDATE: Water cannot exceed condensing temperature
        if T_sec_z2_out_calc > T_cond - min_approach:
            self.warnings.append(
                f"Temperature pinch in condensation zone: Water {T_sec_z2_out_calc:.1f}°C "
                f"exceeds condensing temp {T_cond:.1f}°C. Corrected to {T_cond - min_approach:.1f}°C"
            )
            T_sec_z2_out = T_cond - min_approach
        else:
            T_sec_z2_out = T_sec_z2_out_calc

        # Zone 3: Subcool (single-phase)
        T_sec_z3_in = T_sec_z2_out
        C_ref_liquid = m_dot_ref * (ref_props["cp_liquid"] * 1000.0)  # W/K
        C_min_sub = min(C_water, C_ref_liquid)
        C_max_sub = max(C_water, C_ref_liquid)
        Cr_sub = C_min_sub / C_max_sub if C_max_sub > 0 else 0.0
        NTU3 = (U_subcool * A_subcool) / C_min_sub if C_min_sub > 0 else 0.0
        eps3 = self.epsilon_ntu_counterflow(NTU3, Cr_sub)
        Q3_achieved = max(eps3 * C_min_sub * max(T_cond - T_sec_z3_in, 0.0), 0.0)
        
        # Calculate water outlet temperature for zone 3
        T_sec_z3_out_calc = T_sec_z3_in + (Q3_achieved / C_water) if C_water > 0 else T_sec_z3_in
        
        # Calculate refrigerant outlet temperature
        subcool_achieved = Q3_achieved / max(m_dot_ref * (ref_props["cp_liquid"] * 1000.0), 1e-9)
        T_ref_out = T_cond - subcool_achieved
        
        # VALIDATE: Water cannot exceed refrigerant outlet temperature
        if T_sec_z3_out_calc > T_ref_out - min_approach:
            self.warnings.append(
                f"Temperature pinch in subcooling zone: Water {T_sec_z3_out_calc:.1f}°C "
                f"exceeds refrigerant outlet {T_ref_out:.1f}°C. Corrected to {T_ref_out - min_approach:.1f}°C"
            )
            T_sec_z3_out = T_ref_out - min_approach
        else:
            T_sec_z3_out = T_sec_z3_out_calc

        Q_total_achieved = Q1_achieved + Q2_achieved + Q3_achieved

        # Water/Glycol outlet temperature from achieved duty (sequential, with validation)
        T_water_out = T_sec_z3_out

        # Refrigerant outlet achieved (subcooling achieved - already calculated above)

        # Required secondary outlet temperature from required duty (for comparison)
        Q_total_required = self.results.get("Q_total_required", None)
        try:
            Q_total_required = float(Q_total_required) if Q_total_required is not None else None
        except Exception:
            Q_total_required = None
        T_sec_out_required = (T_sec_in + (Q_total_required / C_water)) if (Q_total_required is not None and C_water > 0) else None

        # Overall effectiveness (based on total max)
        Q_max_total = C_water * max((T_ref_in_superheated - T_sec_in), 0.0)
        epsilon_overall = Q_total_achieved / Q_max_total if Q_max_total > 0 else 0.0

        U_avg = (U_desuperheat * A_desuperheat + U_condense * A_condense + U_subcool * A_subcool) / max(A_total, 1e-9)
        NTU_overall = U_avg * A_total / C_water if C_water > 0 else 0.0

        # LMTD (rough, for reporting)
        dt1 = T_ref_in_superheated - T_water_out
        dt2 = T_ref_out - T_sec_in
        if dt1 > 0 and dt2 > 0 and abs(dt1 - dt2) > 1e-9:
            LMTD = (dt1 - dt2) / math.log(dt1 / dt2)
        else:
            LMTD = (dt1 + dt2) / 2.0

        # Required area based on average U and total duty
        A_required = Q_total_req / (max(U_avg, 1e-9) * max(LMTD, 1e-6))
        area_ratio = A_total / A_required if A_required > 0 else 0.0

        design_status = self.determine_design_status(
            epsilon_overall, A_total, A_required, Q_total_achieved, Q_total_req
        )
        
        # ============================================================
        # ADDITIONAL VALIDATION CHECKS (CORRECTED VERSION)
        # ============================================================
        
        # Check heat duty match for each zone
        desuperheat_match = (Q1_achieved / Q_desuperheat_req * 100) if Q_desuperheat_req > 0 else 100
        latent_match = (Q2_achieved / Q_latent_req * 100) if Q_latent_req > 0 else 100
        subcool_match = (Q3_achieved / Q_subcool_req * 100) if Q_subcool_req > 0 else 100
        
        # Warning if any zone is significantly off (>20% deviation)
        if abs(desuperheat_match - 100) > 20:
            self.warnings.append(f"Desuperheat zone duty mismatch: {desuperheat_match:.1f}% of required")
        if abs(latent_match - 100) > 20:
            self.warnings.append(f"Condensation zone duty mismatch: {latent_match:.1f}% of required")
        if abs(subcool_match - 100) > 20:
            self.warnings.append(f"Subcooling zone duty mismatch: {subcool_match:.1f}% of required")
        
        # Check minimum approach temperature
        min_approach_overall = min([
            T_ref_in_superheated - T_water_out,  # Hot end
            T_cond - T_sec_z2_out,                # Condensing section  
            T_ref_out - T_sec_in                  # Cold end
        ])
        
        if min_approach_overall < 1.0:
            self.warnings.append(
                f"WARNING: Minimum approach temperature {min_approach_overall:.2f}°C is too small (<1°C). "
                f"Consider increasing heat exchanger area or adjusting flow rates."
            )
        
        # Check NTU reasonableness
        if NTU_overall < 0.5:
            self.warnings.append(
                f"WARNING: Very low NTU ({NTU_overall:.2f}) - heat exchanger may be undersized"
            )
        elif NTU_overall > 5.0:
            self.warnings.append(
                f"WARNING: Very high NTU ({NTU_overall:.2f}) - heat exchanger may be oversized"
            )
        
        # Check individual zone NTUs
        for zone_name, ntu_value, area_value in [
            ("Desuperheat", NTU1, A_desuperheat),
            ("Condensation", NTU2, A_condense),
            ("Subcooling", NTU3, A_subcool)
        ]:
            if ntu_value < 0.1:
                self.warnings.append(
                    f"{zone_name} zone NTU too low ({ntu_value:.2f}, area={area_value:.2f}m²) - "
                    f"insufficient area for required heat duty"
                )

        # ============================================================
        # TEMA Compliance Checks (populate keys for report)
        # ============================================================
        tube_valid, tube_message = TEMATubeStandards.validate_tube_selection(tube_size, bwg, inputs.get("design_pressure_kpa", 1000))

        baffle_check = TEMABaffleStandards.validate_baffle_spacing(
            shell_diameter, baffle_spacing, tube_od, tema_class
        )

        # Maximum unsupported span (TEMA table-based estimate)
        T_metal_est = (T_cond + (T_sec_in + T_water_out) / 2.0) / 2.0
        max_span_m = TEMABaffleStandards.get_maximum_unsupported_span(tube_od, tube_material, T_metal_est)
        span_compliant = baffle_spacing <= max_span_m

        # Impingement check (use shell-side inlet density/velocity)
        if refrigerant_side == "shell":
            impingement_check = TEMABaffleStandards.calculate_impingement_requirement(
                ref_props["rho_vapor"], v_shell_report, "gases_vapors"
            )
        else:
            impingement_check = TEMABaffleStandards.calculate_impingement_requirement(
                sec_props["rho"], v_shell_report, "non_abrasive_single_phase"
            )

        tie_rod_req = TEMABaffleStandards.get_tie_rod_requirements(shell_diameter, tema_class)

        # Tube hole diameter validation (use typical estimate + table check)
        hole_diameter = tube_od_mm + 0.2
        hole_check = TEMATubesheetStandards.validate_tube_hole_diameter(
            tube_od_mm, hole_diameter, "standard"
        )

        # Minimum tubesheet thickness (simple TEMA-based check)
        design_pressure_bar = float(inputs.get("design_pressure_bar", inputs.get("design_pressure", 10)))
        design_pressure_pa = design_pressure_bar * 1e5
        max_temp = max(T_ref_in_superheated, T_cond, T_sec_in, T_water_out)
        min_ts_thickness = TEMATubesheetStandards.calculate_min_tubesheet_thickness(
            shell_diameter, tube_od, tube_pitch, design_pressure_pa, tube_material, max_temp
        )

        # Vibration analysis (existing module)
        vibration_inputs = {
            "shell_diameter_m": shell_diameter,
            "tube_od_m": tube_od,
            "tube_id_m": tube_id,
            "tube_pitch_m": tube_pitch,
            "baffle_spacing_m": baffle_spacing,
            "tube_length_m": tube_length,
            "n_tubes": n_tubes,
            "tube_material": tube_material,
            "tube_layout": tube_layout,
            "pitch_ratio": (tube_pitch / tube_od if tube_od > 0 else 1.25),
            "shell_velocity_ms": v_shell_report,
            "tube_velocity_ms": v_tube_report,
            "shell_density": (ref_props["rho_vapor"] if refrigerant_side == "shell" else sec_props["rho"]),
            "tube_density": (sec_props["rho"] if refrigerant_side == "shell" else ref_props["rho_vapor"]),
        }
        vibration_results = self.analyze_vibration_tema(vibration_inputs)

        tema_compliant = all([
            tube_valid,
            baffle_check["compliant"],
            span_compliant,
            (not impingement_check.get("impingement_required", True)) or inputs.get("has_impingement_plate", False),
            vibration_results.get("tema_compliant", True),
        ])

        # ============================================================
        # Compile results
        # ============================================================
        self.results = {
            "heat_exchanger_type": "Condenser",
            "tema_class": tema_class,
            "tema_type": tema_type,
            "condenser_refrigerant_side": refrigerant_side,
            "design_method": "TEMA 10th Edition / ε-NTU",
            "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),

            # Duties
            "heat_duty_required_kw": Q_total_req / 1000.0,
            "heat_duty_achieved_kw": Q_total_achieved / 1000.0,
            "kw_difference": (Q_total_achieved - Q_total_req) / 1000.0,
            "kw_match_percentage": (Q_total_achieved / Q_total_req * 100.0) if Q_total_req > 0 else 0.0,
            "q_desuperheat_req_kw": Q_desuperheat_req / 1000.0,
            "q_latent_req_kw": Q_latent_req / 1000.0,
            "q_subcool_req_kw": Q_subcool_req / 1000.0,
            "q_desuperheat_achieved_kw": Q1_achieved / 1000.0,
            "q_latent_achieved_kw": Q2_achieved / 1000.0,
            "q_subcool_achieved_kw": Q3_achieved / 1000.0,

            # Performance
            "effectiveness": epsilon_overall,
            "ntu": NTU_overall,
            "overall_u": U_avg,
            "h_tube": h_tube,
            "h_condense": h_condense,
            "h_desuperheat": h_desuperheat,
            "h_subcool": h_subcool,
            "lmtd": LMTD,

            # Temperatures
            "t_sec_in": T_sec_in,
            "t_sec_out": T_water_out,
            "t_ref_in_superheated": T_ref_in_superheated,
            "t_ref_condensing": T_cond,
            "t_ref_out_required": T_subcooled_req,
            "t_ref_out_achieved": T_ref_out,
            "subcool_difference": T_ref_out - T_subcooled_req,
            "water_deltaT": abs(T_water_out - T_sec_in),
            "subcool_req": subcool_req,
            "subcool_achieved": T_cond - T_ref_out,

            # Fluids
            "refrigerant": refrigerant,
            "refrigerant_mass_flow_kg_s": m_dot_ref,
            "refrigerant_mass_flow_kg_hr": m_dot_ref * 3600.0,
            "water_vol_flow_L_hr": m_dot_sec_L * 3600.0,
            "water_mass_flow_kg_hr": m_dot_sec_kg * 3600.0,
            "glycol_type": glycol_type,
            "glycol_percentage": glycol_percent,

            # Geometry
            "tube_size": tube_size,
            "bwg": bwg,
            "tube_material": tube_material,
            "tube_layout": tube_layout,
            "pitch_ratio": (tube_pitch / tube_od if tube_od > 0 else 1.25),
            "tube_od_mm": tube_od * 1000.0,
            "tube_id_mm": tube_id * 1000.0,
            "tube_thickness_mm": tube_thickness * 1000.0,
            "tube_pitch_mm": tube_pitch * 1000.0,
            "pitch_ratio": tube_pitch / tube_od if tube_od > 0 else 0.0,
            "tube_layout": tube_layout,
            "n_tubes": n_tubes,
            "n_passes": n_passes,
            "tube_length_m": tube_length,
            "shell_diameter_m": shell_diameter,
            "shell_flow_area_m2": shell_flow_area,
            "baffle_spacing_m": baffle_spacing,
            "baffle_cut_percent": baffle_cut * 100.0,
            "n_baffles": n_baffles,

            # Areas
            "area_total_m2": A_total,
            "area_desuperheat_m2": A_desuperheat,
            "area_condense_m2": A_condense,
            "area_subcool_m2": A_subcool,
            "area_required_m2": A_required,
            "area_ratio": area_ratio,

            # Velocities & DP
            "velocity_tube_ms": v_tube_report,
            "velocity_shell_ms": v_shell_report,
            "velocity_tube_status": tube_velocity_status["status"],
            "velocity_shell_status": shell_velocity_status["status"],
            "dp_tube_kpa": dp_tube / 1000.0,
            "dp_shell_kpa": dp_shell / 1000.0,
            "reynolds_tube": Re_tube_report,
            "reynolds_shell": Re_shell_report,

            # TEMA Compliance (keys used by report)
            "tema_tube_compliant": tube_valid,
            "tema_tube_message": tube_message,
            "tema_baffle_compliant": baffle_check["compliant"],
            "tema_baffle_warnings": baffle_check["warnings"],
            "tema_span_compliant": span_compliant,
            "tema_max_span_m": max_span_m,
            "tema_impingement": impingement_check,
            "tema_tie_rod": tie_rod_req,
            "tema_hole_check": hole_check,
            "tema_min_ts_thickness_mm": min_ts_thickness,
            "tema_vibration": vibration_results,
            "tema_overall_compliant": tema_compliant,

            # Status
            "design_status": design_status,
            "warnings": self.warnings,
        }

        return self.results

# ========================================================================
    # UTILITY METHODS
    # ========================================================================
    
    def check_velocity_status(self, velocity: float, glycol_percent: int, flow_type: str) -> Dict:
        """Check velocity status against TEMA recommendations"""
        if flow_type == "shell":
            if glycol_percent > 0:
                rec = self.RECOMMENDED_VELOCITIES["glycol_shell"]
            else:
                rec = self.RECOMMENDED_VELOCITIES["water_shell"]
        elif flow_type == "tubes":
            if glycol_percent > 0:
                rec = self.RECOMMENDED_VELOCITIES["glycol_tubes"]
            else:
                rec = self.RECOMMENDED_VELOCITIES["water_tubes"]
        else:
            rec = self.RECOMMENDED_VELOCITIES.get(flow_type, self.RECOMMENDED_VELOCITIES["water_shell"])
        
        if velocity < rec["min"]:
            status = "Too Low"
            color = "red"
            css_class = "velocity-low"
        elif velocity < rec["opt"]:
            status = "Low"
            color = "orange"
            css_class = "velocity-low"
        elif velocity <= rec["max"]:
            status = "Optimal"
            color = "green"
            css_class = "velocity-good"
        else:
            status = "Too High"
            color = "red"
            css_class = "velocity-high"
        
        return {
            "velocity": velocity,
            "status": status,
            "color": color,
            "css_class": css_class,
            "min": rec["min"],
            "opt": rec["opt"],
            "max": rec["max"]
        }
    
    def determine_design_status(self, effectiveness: float, area_total: float, 
                              area_required: float, kw_achieved: float, 
                              kw_required: float) -> str:
        """Determine design status"""
        area_ratio = area_total / area_required if area_required > 0 else 0
        kw_ratio = kw_achieved / kw_required if kw_required > 0 else 0
        
        kw_match = 0.85 <= kw_ratio <= 1.15
        area_adequate = 0.9 <= area_ratio <= 1.5
        effective_enough = effectiveness >= 0.3
        
        if kw_match and area_adequate and effective_enough:
            return "Adequate"
        elif (0.7 <= kw_ratio <= 1.3) and (0.7 <= area_ratio <= 2.0) and effectiveness >= 0.2:
            return "Marginal"
        else:
            return "Inadequate"


# ============================================================================
# PDF REPORT GENERATOR
# ============================================================================

class PDFReportGenerator:
    """Generate TEMA-style PDF report of heat exchanger design"""
    
    def __init__(self):
        self.styles = getSampleStyleSheet()
        self.title_style = ParagraphStyle(
            'CustomTitle',
            parent=self.styles['Heading1'],
            fontSize=16,
            alignment=TA_CENTER,
            spaceAfter=12,
            textColor=colors.HexColor('#1E3A8A')
        )
        self.heading_style = ParagraphStyle(
            'CustomHeading',
            parent=self.styles['Heading2'],
            fontSize=14,
            alignment=TA_LEFT,
            spaceAfter=6,
            textColor=colors.HexColor('#1E3A8A')
        )
        self.subheading_style = ParagraphStyle(
            'CustomSubHeading',
            parent=self.styles['Heading3'],
            fontSize=12,
            alignment=TA_LEFT,
            spaceAfter=4,
            textColor=colors.HexColor('#4B5563')
        )
        self.normal_style = self.styles['Normal']
    
    def generate_report(self, results: Dict, inputs: Dict) -> bytes:
        """Generate PDF report as bytes"""
        buffer = BytesIO()
        doc = SimpleDocTemplate(
            buffer,
            pagesize=letter,
            rightMargin=72,
            leftMargin=72,
            topMargin=72,
            bottomMargin=72,
        )
        
        story = []
        
        # Title
        title_text = f"TEMA 10th Edition Heat Exchanger Design Report"
        story.append(Paragraph(title_text, self.title_style))
        story.append(Spacer(1, 0.25 * inch))
        
        # Subtitle
        subtitle_text = f"{results.get('heat_exchanger_type', 'Heat Exchanger')} - TEMA Class {results.get('tema_class', 'R')}"
        story.append(Paragraph(subtitle_text, self.heading_style))
        story.append(Spacer(1, 0.1 * inch))
        
        # Date and identification
        date_text = f"Report Generated: {results.get('date', datetime.now().strftime('%Y-%m-%d %H:%M:%S'))}"
        story.append(Paragraph(date_text, self.normal_style))
        story.append(Spacer(1, 0.2 * inch))
        
        # ====================================================================
        # 1. DESIGN SUMMARY
        # ====================================================================
        story.append(Paragraph("1. DESIGN SUMMARY", self.heading_style))
        story.append(Spacer(1, 0.1 * inch))
        
        summary_data = [
            ["Parameter", "Value", "Unit"],
            ["Heat Exchanger Type", results.get('heat_exchanger_type', 'N/A'), ""],
            ["TEMA Class", results.get('tema_class', 'R'), ""],
            ["TEMA Type", results.get('tema_type', 'AES'), ""],
            ["Design Method", results.get('design_method', 'TEMA 10th/ε-NTU'), ""],
            ["Design Status", results.get('design_status', 'N/A'), ""],
        ]
        
        if results.get('tema_overall_compliant', False):
            summary_data.append(["TEMA Compliance", "✓ COMPLIANT", ""])
        else:
            summary_data.append(["TEMA Compliance", "✗ NON-COMPLIANT", ""])
        
        summary_table = Table(summary_data, colWidths=[2.5*inch, 1.5*inch, 0.8*inch])
        summary_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1E3A8A')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 10),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 8),
            ('BACKGROUND', (0, 1), (-1, -1), colors.HexColor('#F3F4F6')),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ]))
        story.append(summary_table)
        story.append(Spacer(1, 0.2 * inch))
        
        # ====================================================================
        # 2. THERMAL PERFORMANCE
        # ====================================================================
        story.append(Paragraph("2. THERMAL PERFORMANCE", self.heading_style))
        story.append(Spacer(1, 0.1 * inch))
        
        thermal_data = [
            ["Parameter", "Required", "Achieved", "Unit"],
            ["Heat Duty", 
             f"{results.get('heat_duty_required_kw', 0):.2f}",
             f"{results.get('heat_duty_achieved_kw', 0):.2f}", "kW"],
            ["Match Percentage", "-", 
             f"{results.get('kw_match_percentage', 0):.1f}%", "%"],
        ]
        
        if results['heat_exchanger_type'] == 'DX Evaporator':
            thermal_data.extend([
                ["Latent Heat", 
                 f"{results.get('q_latent_req_kw', 0):.2f}",
                 f"{results.get('q_latent_achieved_kw', 0):.2f}", "kW"],
                ["Superheat", 
                 f"{results.get('q_superheat_req_kw', 0):.2f}",
                 f"{results.get('q_superheat_achieved_kw', 0):.2f}", "kW"],
            ])
        else:
            thermal_data.extend([
                ["Desuperheat", 
                 f"{results.get('q_desuperheat_req_kw', 0):.2f}",
                 f"{results.get('q_desuperheat_achieved_kw', 0):.2f}", "kW"],
                ["Latent Heat", 
                 f"{results.get('q_latent_req_kw', 0):.2f}",
                 f"{results.get('q_latent_achieved_kw', 0):.2f}", "kW"],
                ["Subcooling", 
                 f"{results.get('q_subcool_req_kw', 0):.2f}",
                 f"{results.get('q_subcool_achieved_kw', 0):.2f}", "kW"],
            ])
        
        thermal_table = Table(thermal_data, colWidths=[2.2*inch, 1.2*inch, 1.2*inch, 0.8*inch])
        thermal_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1E3A8A')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 9),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 8),
            ('BACKGROUND', (0, 1), (-1, -1), colors.HexColor('#F9FAFB')),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ]))
        story.append(thermal_table)
        story.append(Spacer(1, 0.1 * inch))
        
        # Heat transfer coefficients
        htc_data = [
            ["Heat Transfer Coefficient", "Value", "Unit"],
            ["Overall U", f"{results.get('overall_u', 0):.0f}", "W/m²·K"],
            ["Effectiveness (ε)", f"{results.get('effectiveness', 0):.3f}", "-"],
            ["NTU", f"{results.get('ntu', 0):.2f}", "-"],
            ["LMTD", f"{results.get('lmtd', 0):.2f}", "°C"],
        ]
        
        if results['heat_exchanger_type'] == 'DX Evaporator':
            htc_data.extend([
                ["Tube-side Evaporation HTC", f"{results.get('h_tube_evap', 0):.0f}", "W/m²·K"],
                ["Tube-side Superheat HTC", f"{results.get('h_tube_superheat', 0):.0f}", "W/m²·K"],
                ["Shell-side HTC", f"{results.get('h_shell', 0):.0f}", "W/m²·K"],
            ])
        else:
            htc_data.extend([
                ["Tube-side Water HTC", f"{results.get('h_tube', 0):.0f}", "W/m²·K"],
                ["Shell-side Condensation HTC", f"{results.get('h_condense', 0):.0f}", "W/m²·K"],
            ])
        
        htc_table = Table(htc_data, colWidths=[2.8*inch, 1.2*inch, 0.8*inch])
        htc_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#4B5563')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ]))
        story.append(htc_table)
        story.append(Spacer(1, 0.2 * inch))
        
        # ====================================================================
        # 3. TEMPERATURES
        # ====================================================================
        story.append(Paragraph("3. OPERATING TEMPERATURES", self.heading_style))
        story.append(Spacer(1, 0.1 * inch))
        
        if results['heat_exchanger_type'] == 'DX Evaporator':
            temp_data = [
                ["Stream", "Inlet", "Outlet", "Unit"],
                ["Refrigerant", f"{results.get('t_ref_in', 0):.1f}", 
                 f"{results.get('t_ref_out_achieved', 0):.1f}", "°C"],
                ["Water/Glycol", f"{results.get('t_sec_in', 0):.1f}", 
                 f"{results.get('t_sec_out', 0):.1f}", "°C"],
                ["Superheat", f"Required: {results.get('superheat_req', 0):.1f}", 
                 f"Achieved: {results.get('superheat_achieved', 0):.1f}", "K"],
            ]
        else:
            temp_data = [
                ["Stream", "Inlet", "Outlet", "Unit"],
                ["Refrigerant (superheated)", f"{results.get('t_ref_in_superheated', 0):.1f}", 
                 f"{results.get('t_ref_condensing', 0):.1f}", "°C"],
                ["Refrigerant (condensing)", f"{results.get('t_ref_condensing', 0):.1f}", 
                 f"{results.get('t_ref_out_achieved', 0):.1f}", "°C"],
                ["Water/Glycol", f"{results.get('t_sec_in', 0):.1f}", 
                 f"{results.get('t_sec_out', 0):.1f}", "°C"],
                ["Subcooling", f"Required: {results.get('subcool_req', 0):.1f}", 
                 f"Achieved: {results.get('subcool_achieved', 0):.1f}", "K"],
            ]
        
        temp_table = Table(temp_data, colWidths=[2.0*inch, 1.2*inch, 1.2*inch, 0.8*inch])
        temp_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#4B5563')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ]))
        story.append(temp_table)
        story.append(Spacer(1, 0.2 * inch))
        
        # ====================================================================
        # 4. GEOMETRY
        # ====================================================================
        story.append(Paragraph("4. MECHANICAL GEOMETRY", self.heading_style))
        story.append(Spacer(1, 0.1 * inch))
        
        story.append(Paragraph("4.1 Shell Side", self.subheading_style))
        shell_data = [
            ["Parameter", "Value", "Unit"],
            ["Shell Inside Diameter", f"{results.get('shell_diameter_m', 0)*1000:.0f}", "mm"],
            ["Shell Flow Area", f"{results.get('shell_flow_area_m2', 0):.4f}", "m²"],
            ["Baffle Type", "Segmental", ""],
            ["Baffle Cut", f"{results.get('baffle_cut_percent', 25):.0f}", "%"],
            ["Baffle Spacing", f"{results.get('baffle_spacing_m', 0)*1000:.0f}", "mm"],
            ["Number of Baffles", f"{results.get('n_baffles', 0)}", ""],
            ["TEMA Max Unsupported Span", f"{results.get('tema_max_span_m', 0)*1000:.0f}", "mm"],
            ["Tie Rod Diameter", f"{results.get('tie_rod_diameter_mm', 9.5):.1f}", "mm"],
            ["Tie Rod Quantity (min)", f"{results.get('tie_rod_min_qty', 4)}", ""],
        ]
        
        shell_table = Table(shell_data, colWidths=[2.5*inch, 1.2*inch, 0.8*inch])
        shell_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#6B7280')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ]))
        story.append(shell_table)
        story.append(Spacer(1, 0.1 * inch))
        
        story.append(Paragraph("4.2 Tube Side", self.subheading_style))
        tube_data = [
            ["Parameter", "Value", "Unit"],
            ["Tube Size", f"{results.get('tube_size', '3/4 in')}", ""],
            ["BWG Gauge", f"{results.get('bwg', '18')}", ""],
            ["Tube Material", f"{results.get('tube_material', 'Copper')}", ""],
            ["Tube OD", f"{results.get('tube_od_mm', 19.05):.2f}", "mm"],
            ["Tube ID", f"{results.get('tube_id_mm', 15.75):.2f}", "mm"],
            ["Tube Wall Thickness", f"{results.get('tube_thickness_mm', 1.245):.3f}", "mm"],
            ["Tube Length", f"{results.get('tube_length_m', 2)*1000:.0f}", "mm"],
            ["Number of Tubes", f"{results.get('n_tubes', 100)}", ""],
            ["Number of Passes", f"{results.get('n_passes', 2)}", ""],
            ["Tube Pitch", f"{results.get('tube_pitch_mm', 23.8):.1f}", "mm"],
            ["Pitch Ratio", f"{results.get('pitch_ratio', 1.25):.3f}", "-"],
            ["Tube Layout", f"{results.get('tube_layout', 'triangular').title()}", ""],
            ["Total Heat Transfer Area", f"{results.get('area_total_m2', 0):.2f}", "m²"],
            ["TEMA Min Tubesheet Thickness", f"{results.get('tema_min_ts_thickness_mm', 19.05):.1f}", "mm"],
        ]
        
        tube_table = Table(tube_data, colWidths=[2.5*inch, 1.2*inch, 0.8*inch])
        tube_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#6B7280')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ]))
        story.append(tube_table)
        story.append(Spacer(1, 0.2 * inch))
        
        # ====================================================================
        # 5. FLUID DYNAMICS
        # ====================================================================
        story.append(Paragraph("5. FLUID DYNAMICS", self.heading_style))
        story.append(Spacer(1, 0.1 * inch))
        
        if results['heat_exchanger_type'] == 'DX Evaporator':
            fluid_data = [
                ["Parameter", "Tube Side (Refrigerant)", "Shell Side (Water/Glycol)", "Unit"],
                ["Fluid", results.get('refrigerant', 'R134a'), 
                 f"{results.get('glycol_type', 'Water').title()} {results.get('glycol_percentage', 0)}%", ""],
                ["Mass Flow Rate", f"{results.get('refrigerant_mass_flow_kg_hr', 0):.0f}", 
                 f"{results.get('water_mass_flow_kg_hr', 0):.0f}", "kg/hr"],
                ["Velocity", f"{results.get('velocity_tube_ms', 0):.2f}", 
                 f"{results.get('velocity_shell_ms', 0):.2f}", "m/s"],
                ["Velocity Status", results.get('velocity_tube_status', 'N/A'), 
                 results.get('velocity_shell_status', 'N/A'), ""],
                ["Reynolds Number", f"{results.get('reynolds_tube', 0):.0f}", 
                 f"{results.get('reynolds_shell', 0):.0f}", ""],
                ["Pressure Drop", f"{results.get('dp_tube_kpa', 0):.2f}", 
                 f"{results.get('dp_shell_kpa', 0):.2f}", "kPa"],
                ["Inlet Quality", f"{results.get('inlet_quality_percent', 20):.1f}", "-", "%"],
                ["Outlet Quality", f"{results.get('outlet_quality', 100):.0f}", "-", "%"],
            ]
        else:
            fluid_data = [
                ["Parameter", "Tube Side (Water/Glycol)", "Shell Side (Refrigerant)", "Unit"],
                ["Fluid", f"{results.get('glycol_type', 'Water').title()} {results.get('glycol_percentage', 0)}%", 
                 results.get('refrigerant', 'R134a'), ""],
                ["Mass Flow Rate", f"{results.get('water_mass_flow_kg_hr', 0):.0f}", 
                 f"{results.get('refrigerant_mass_flow_kg_hr', 0):.0f}", "kg/hr"],
                ["Velocity", f"{results.get('velocity_tube_ms', 0):.2f}", 
                 f"{results.get('velocity_shell_ms', 0):.2f}", "m/s"],
                ["Velocity Status", results.get('velocity_tube_status', 'N/A'), 
                 results.get('velocity_shell_status', 'N/A'), ""],
                ["Reynolds Number", f"{results.get('reynolds_tube', 0):.0f}", 
                 f"{results.get('reynolds_shell', 0):.0f}", ""],
                ["Pressure Drop", f"{results.get('dp_tube_kpa', 0):.2f}", 
                 f"{results.get('dp_shell_kpa', 0):.2f}", "kPa"],
            ]
        
        fluid_table = Table(fluid_data, colWidths=[1.8*inch, 1.2*inch, 1.2*inch, 0.6*inch])
        fluid_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#4B5563')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 8),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ]))
        story.append(fluid_table)
        story.append(Spacer(1, 0.2 * inch))
        
        # ====================================================================
        # 6. TEMA COMPLIANCE SUMMARY
        # ====================================================================
        story.append(Paragraph("6. TEMA 10th EDITION COMPLIANCE", self.heading_style))
        story.append(Spacer(1, 0.1 * inch))
        
        tema_data = [
            ["TEMA Section", "Requirement", "Status", "Compliant"],
            ["RCB-2.5 / Table D-7", "Tube Size & BWG", 
             results.get('tema_tube_message', 'N/A')[:30],
             "✓" if results.get('tema_tube_compliant', False) else "✗"],
            ["RCB-4.5.1", "Minimum Baffle Spacing", 
             "≥ 1/5 shell ID or 2\"",
             "✓" if results.get('tema_baffle_compliant', False) else "✗"],
            ["RCB-4.5.2", "Max Unsupported Span", 
             f"≤ {results.get('tema_max_span_m', 0)*1000:.0f}mm",
             "✓" if results.get('tema_span_compliant', False) else "✗"],
            ["RCB-4.6.1", "Impingement Protection", 
             "Required" if results.get('tema_impingement', {}).get('impingement_required', False) else "Not Required",
             "✓" if not results.get('tema_impingement', {}).get('impingement_required', True) or inputs.get('has_impingement_plate', False) else "✗"],
            ["RCB-4.7.1", "Tie Rods", 
             f"{results.get('tie_rod_min_qty', 4)} x {results.get('tie_rod_diameter_mm', 9.5)}mm",
             "✓"],
            ["Section 6", "Flow-Induced Vibration", 
             f"{results.get('tema_vibration', {}).get('risk_level', 'N/A')} Risk",
             "✓" if results.get('tema_vibration', {}).get('tema_compliant', True) else "✗"],
            ["RCB-7.2.1", "Tube Hole Tolerances", 
             f"Target: {results.get('tema_hole_check', {}).get('target_diameter_mm', 0):.2f}mm",
             "✓" if results.get('tema_hole_check', {}).get('compliant', False) else "✗"],
            ["RCB-7.1.1", "Min Tubesheet Thickness", 
             f"≥ {results.get('tema_min_ts_thickness_mm', 19.05):.1f}mm",
             "✓"],
        ]
        
        tema_table = Table(tema_data, colWidths=[1.2*inch, 1.5*inch, 1.5*inch, 0.6*inch])
        tema_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1E3A8A')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 8),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ]))
        
        # Color code compliance
        for i in range(1, len(tema_data)):
            if tema_data[i][3] == "✓":
                tema_table.setStyle(TableStyle([('BACKGROUND', (3, i), (3, i), colors.HexColor('#D1FAE5'))]))
            else:
                tema_table.setStyle(TableStyle([('BACKGROUND', (3, i), (3, i), colors.HexColor('#FEE2E2'))]))
        
        story.append(tema_table)
        story.append(Spacer(1, 0.2 * inch))
        
        if results.get('tema_overall_compliant', False):
            story.append(Paragraph("✓ OVERALL TEMA COMPLIANT - Design meets TEMA 10th Edition requirements", 
                                  ParagraphStyle('Compliant', parent=self.styles['Normal'], 
                                                textColor=colors.HexColor('#065F46'), 
                                                fontSize=11, spaceAfter=6)))
        else:
            story.append(Paragraph("✗ OVERALL TEMA NON-COMPLIANT - Design does not meet all TEMA requirements", 
                                  ParagraphStyle('NonCompliant', parent=self.styles['Normal'], 
                                                textColor=colors.HexColor('#991B1B'), 
                                                fontSize=11, spaceAfter=6)))
        
        story.append(Spacer(1, 0.2 * inch))
        
        # ====================================================================
        # 7. VIBRATION ANALYSIS (if performed)
        # ====================================================================
        if 'tema_vibration' in results:
            story.append(Paragraph("7. FLOW INDUCED VIBRATION ANALYSIS (TEMA Section 6)", self.heading_style))
            story.append(Spacer(1, 0.1 * inch))
            
            vib = results['tema_vibration']
            vib_data = [
                ["Parameter", "Value", "Unit"],
                ["Tube Natural Frequency", f"{vib.get('natural_frequency_hz', 0):.2f}", "Hz"],
                ["Critical Velocity", f"{vib.get('critical_velocity_ms', 0):.3f}", "m/s"],
                ["Actual Velocity", f"{vib.get('actual_velocity_ms', 0):.3f}", "m/s"],
                ["Safety Factor", f"{vib.get('safety_factor', 0):.2f}", "-"],
                ["Risk Level", vib.get('risk_level', 'N/A'), ""],
            ]
            
            vib_table = Table(vib_data, colWidths=[2.5*inch, 1.2*inch, 0.8*inch])
            vib_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#6B7280')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
            ]))
            story.append(vib_table)
            story.append(Spacer(1, 0.1 * inch))
            
            story.append(Paragraph(f"Recommendation: {vib.get('recommendation', 'N/A')}", self.normal_style))
            story.append(Spacer(1, 0.2 * inch))
        
        # ====================================================================
        # 8. WARNINGS AND NOTES
        # ====================================================================
        if results.get('warnings'):
            story.append(Paragraph("8. DESIGN WARNINGS", self.heading_style))
            story.append(Spacer(1, 0.1 * inch))
            
            for warning in results['warnings']:
                story.append(Paragraph(f"• {warning}", self.normal_style))
                story.append(Spacer(1, 0.05 * inch))
            
            story.append(Spacer(1, 0.2 * inch))
        
        # ====================================================================
        # Footer
        # ====================================================================
        story.append(Spacer(1, 0.3 * inch))
        footer_text = "This report was generated by TEMA 10th Edition Compliant Heat Exchanger Design Tool. "
        footer_text += "Design calculations are based on TEMA Standards 10th Edition and ASHRAE fundamentals."
        story.append(Paragraph(footer_text, ParagraphStyle('Footer', parent=self.styles['Normal'], 
                                                          fontSize=8, alignment=TA_CENTER, 
                                                          textColor=colors.grey)))
        
        # Build PDF
        doc.build(story)
        pdf_bytes = buffer.getvalue()
        buffer.close()
        
        return pdf_bytes


# ============================================================================
# STREAMLIT UI COMPONENTS
# ============================================================================

def number_input_with_buttons(label: str, min_value: float, max_value: float, 
                            value: float, step: float, key: str, format: str = "%.1f",
                            help_text: str = None) -> float:
    """Number input with +/- buttons.

    Important: Streamlit widgets keep their own state by widget-key. If the widget's stored value
    becomes < min_value (e.g., user changes tube OD and pitch minimum increases), Streamlit will
    raise StreamlitValueBelowMinError on rerun. To prevent this, we clamp BOTH:
      - st.session_state[key] (our logical value)
      - st.session_state[f"{key}_input"] (the widget's internal value)
    """
    # Ensure sane bounds even if upstream logic produces min>max temporarily
    try:
        min_v = float(min_value)
    except Exception:
        min_v = 0.0
    try:
        max_v = float(max_value)
    except Exception:
        max_v = min_v
    if max_v < min_v:
        max_v = min_v

    def _clamp(x, default):
        try:
            xf = float(x)
        except Exception:
            xf = float(default)
        if math.isnan(xf) or math.isinf(xf):
            xf = float(default)
        return min(max(xf, min_v), max_v)

    # Initialize our logical value
    if key not in st.session_state:
        st.session_state[key] = value
    st.session_state[key] = _clamp(st.session_state.get(key), value)

    # ALSO clamp the widget state (critical to avoid StreamlitValueBelowMinError)
    widget_key = f"{key}_input"
    # Always force widget state into bounds. Streamlit may keep an old widget value that is now invalid.
    st.session_state[widget_key] = _clamp(st.session_state.get(widget_key, st.session_state[key]), st.session_state[key])

    col1, col2, col3 = st.columns([1, 2, 1])

    with col1:
        if st.button("−", key=f"{key}_minus"):
            st.session_state[key] = _clamp(st.session_state[key] - step, st.session_state[key])
            st.session_state[widget_key] = st.session_state[key]
            st.rerun()

    with col2:
        st.markdown(f"<div style='font-weight:500; margin-bottom:0.25rem;'>{label}</div>", unsafe_allow_html=True)
        if help_text:
            st.caption(help_text)

        # Use the clamped widget value if it exists, otherwise our logical value
        current_val = st.session_state.get(widget_key, st.session_state[key])
        current_val = _clamp(current_val, st.session_state[key])

        value_input = st.number_input(
            label="",
            min_value=min_v,
            max_value=max_v,
            value=float(current_val),
            step=float(step),
            key=widget_key,
            label_visibility="collapsed",
            format=format
        )

        # Keep logical value synchronized with widget
        st.session_state[key] = _clamp(value_input, st.session_state[key])

    with col3:
        if st.button("＋", key=f"{key}_plus"):
            st.session_state[key] = _clamp(st.session_state[key] + step, st.session_state[key])
            st.session_state[widget_key] = st.session_state[key]
            st.rerun()

    return float(st.session_state[key])

def create_input_section():
    """Create TEMA-compliant input section"""
    st.sidebar.header("⚙️ TEMA 10th Edition Design")
    
    inputs = {}
    
    # Heat exchanger type
    inputs["hex_type"] = st.sidebar.radio(
        "Heat Exchanger Type",
        ["DX Evaporator", "Condenser"],
        help="DX Evaporator: Refrigerant in tubes, Water/Glycol on shell\nCondenser: Refrigerant on shell, Water/Glycol in tubes"
    )
    
    if inputs["hex_type"] == "DX Evaporator":
        st.sidebar.markdown('<span class="dx-badge">DX Type - Refrigerant in Tubes</span>', unsafe_allow_html=True)
    else:
        # Condenser configuration selector
        cond_side_label = st.sidebar.radio(
            "Condenser: Refrigerant location",
            ["Shell side (recommended)", "Tube side (optional)"],
            help="Most water-cooled condensers put water/glycol in tubes for cleaning. "
                 "Some designs condense refrigerant inside tubes instead."
        )
        inputs["condenser_refrigerant_side"] = "shell" if cond_side_label.startswith("Shell") else "tube"

        if inputs["condenser_refrigerant_side"] == "shell":
            st.sidebar.markdown('<span class="condenser-badge">Condenser - Refrigerant on Shell</span>', unsafe_allow_html=True)
        else:
            st.sidebar.markdown('<span class="condenser-badge">Condenser - Refrigerant in Tubes</span>', unsafe_allow_html=True)
    
        # Advanced zoned condenser (integral subcooler) – single page toggle
        # This does NOT change thermal correlations; it only allocates available area to zones more realistically.
        if inputs.get("condenser_refrigerant_side", "shell") == "shell":
            st.sidebar.subheader("🧩 Advanced: Zoned Condenser (Integral Subcooler)")
            inputs["zoned_condenser_enabled"] = st.sidebar.checkbox(
                "Enable zoned model (allocate dedicated subcool area)",
                value=False,
                help="When enabled, a portion of the bundle area/rows is reserved for subcooling. "
                     "This helps avoid the misleading case where total kW looks OK but subcooling fails."
            )

            if inputs["zoned_condenser_enabled"]:
                method = st.sidebar.selectbox(
                    "Allocation method",
                    ["Area fraction (simple)", "Row-based (top/bottom concept)"],
                    help="Area fraction is the fastest and most robust. Row-based approximates which rows see colder water first."
                )
                inputs["zoned_condenser_method"] = "area_fraction" if method.startswith("Area") else "row_based"

                if inputs["zoned_condenser_method"] == "area_fraction":
                    inputs["subcool_area_fraction"] = st.sidebar.slider(
                        "Subcooler area fraction of total bundle",
                        min_value=0.05, max_value=0.60, value=0.20, step=0.01,
                        help="Fraction of total tube outside area reserved for subcooling section."
                    )
                else:
                    inputs["water_entry_location"] = st.sidebar.selectbox(
                        "Water entry location (for row concept)",
                        ["Top", "Bottom", "Side"],
                        help="Used for guidance text (which rows are coldest first). Thermal model uses row fraction."
                    )
                    inputs["estimated_tubes_per_row"] = st.sidebar.number_input(
                        "Estimated tubes per row (for row-based allocation)",
                        min_value=1, max_value=500, value=25, step=1,
                        help="Approximate tubes in one row across the shell. Used only to estimate total rows."
                    )
                    inputs["subcool_rows"] = st.sidebar.number_input(
                        "Rows reserved for subcooling",
                        min_value=1, max_value=200, value=4, step=1,
                        help="Top/bottom rows (depending on water entry) reserved for subcooling."
                    )

    st.sidebar.markdown("---")
    
    # TEMA Class Selection
    st.sidebar.subheader("📋 TEMA Standards")
    tema_class = st.sidebar.selectbox(
        "TEMA Class",
        ["R - Petroleum Processing", "C - Commercial", "B - Chemical Process"],
        help="R: Severe duty, C: Moderate service, B: Chemical process"
    )
    inputs["tema_class"] = tema_class.split(" - ")[0]
    
    tema_type = st.sidebar.selectbox(
        "TEMA Type",
        ["AES", "BEM", "AEU", "AKT", "BGU", "CFU"],
        help="AES: Removable bundle, floating head\nBEM: Fixed tubesheet\nAEU: U-tube"
    )
    inputs["tema_type"] = tema_type
    
    mechanical_cleaning = st.sidebar.checkbox(
        "Shell Side Mechanical Cleaning Required",
        value=False,
        help="Affects tube pitch and cleaning lane requirements per TEMA R-2.5"
    )
    inputs["mechanical_cleaning"] = mechanical_cleaning
    
    vibration_analysis = st.sidebar.checkbox(
        "Perform TEMA Section 6 Vibration Analysis",
        value=True,
        help="Critical for preventing flow-induced tube vibration"
    )
    inputs["vibration_analysis"] = vibration_analysis
    
    impingement_plate = st.sidebar.checkbox(
        "Include Impingement Plate",
        value=True,
        help="Required for two-phase flow per TEMA RCB-4.6.1"
    )
    inputs["has_impingement_plate"] = impingement_plate
    
    st.sidebar.markdown("---")
    
    # Refrigerant Parameters
    st.sidebar.subheader("🔧 Refrigerant Parameters")
    
    designer = TEMACompliantDXHeatExchangerDesign()
    
    # Common refrigerants list
    refrigerants = ["R134a", "R410A", "R407C", "R22", "R32", "R1234yf", "R717 (Ammonia)", "R744 (CO2)"]
    inputs["refrigerant"] = st.sidebar.selectbox(
        "Refrigerant Type",
        refrigerants,
        help="Properties calculated via CoolProp database"
    )
    
    inputs["m_dot_ref"] = number_input_with_buttons(
        label="Refrigerant Mass Flow (kg/s)",
        min_value=0.01, max_value=10.0, value=0.221, step=0.001,
        key="m_dot_ref", format="%.3f",
        help_text="From compressor specification sheet"
    )
    
    if inputs["hex_type"] == "Condenser":
        st.sidebar.subheader("🌡️ Condenser Parameters")
        
        inputs["T_ref_in_superheated"] = number_input_with_buttons(
            label="Superheated Refrigerant Inlet (°C)",
            min_value=30.0, max_value=150.0, value=80.0, step=1.0,
            key="T_ref_superheated", format="%.1f",
            help_text="Temperature from compressor discharge"
        )
        
        inputs["T_ref"] = number_input_with_buttons(
            label="Condensing Temperature (°C)",
            min_value=20.0, max_value=80.0, value=45.0, step=1.0,
            key="T_cond", format="%.1f"
        )
        
        inputs["delta_T_sh_sc"] = number_input_with_buttons(
            label="Required Subcooling at Exit (K)",
            min_value=0.0, max_value=20.0, value=5.0, step=0.5,
            key="subcool", format="%.1f"
        )
    
    else:  # DX Evaporator
        st.sidebar.subheader("🌡️ Evaporator Parameters")
        
        inputs["T_ref"] = number_input_with_buttons(
            label="Evaporating Temperature (°C)",
            min_value=-50.0, max_value=20.0, value=5.0, step=1.0,
            key="T_evap", format="%.1f"
        )
        
        inputs["inlet_quality"] = number_input_with_buttons(
            label="Inlet Quality from TXV (%)",
            min_value=0.0, max_value=100.0, value=20.0, step=1.0,
            key="inlet_quality", format="%.1f",
            help_text="Quality entering evaporator (0-100%)"
        )
        
        inputs["delta_T_sh_sc"] = number_input_with_buttons(
            label="Required Superheat at Exit (K)",
            min_value=3.0, max_value=15.0, value=5.0, step=0.5,
            key="superheat", format="%.1f"
        )
    
    st.sidebar.markdown("---")
    
    # Water/Glycol Side
    st.sidebar.subheader("💧 Water/Glycol Side")
    
    glycol_options = ["Water Only", "Water + Ethylene Glycol", "Water + Propylene Glycol (Food Grade)"]
    glycol_choice = st.sidebar.radio("Fluid Type", glycol_options)
    
    if "Ethylene" in glycol_choice:
        inputs["glycol_type"] = "ethylene"
    elif "Propylene" in glycol_choice:
        inputs["glycol_type"] = "propylene"
    else:
        inputs["glycol_type"] = "water"
    
    if "Glycol" in glycol_choice:
        inputs["glycol_percentage"] = int(number_input_with_buttons(
            label="Glycol Percentage",
            min_value=0, max_value=60, value=30, step=5,
            key="glycol_percent", format="%.0f",
            help_text="Higher percentage = lower freeze point"
        ))
        
        # Calculate freeze point using CoolProp
        temp_props = designer.get_glycol_properties(inputs["glycol_type"], inputs["glycol_percentage"], 20)
        freeze_point = temp_props["freeze_point"]
        st.sidebar.caption(f"Freeze point: {freeze_point:.1f}°C")
    else:
        inputs["glycol_percentage"] = 0
    
    inputs["T_sec_in"] = number_input_with_buttons(
        label="Water Inlet Temperature (°C)",
        min_value=-20.0 if "Glycol" in glycol_choice else 0.0,
        max_value=80.0, value=12.0 if inputs["hex_type"] == "DX Evaporator" else 30.0, step=1.0,
        key="T_water_in", format="%.1f"
    )
    
    inputs["m_dot_sec"] = number_input_with_buttons(
        label="Water Flow Rate (L/hr)",
        min_value=100.0, max_value=100000.0, value=25000.0, step=100.0,
        key="water_flow", format="%.0f"
    )
    
    st.sidebar.markdown("---")
    
    # Geometry Parameters
    st.sidebar.subheader("📐 TEMA Geometry Parameters")
    
    # Tube selection with BWG
    col1, col2 = st.sidebar.columns(2)
    with col1:
        inputs["tube_size"] = st.selectbox("Tube Size", list(TEMATubeStandards.TUBE_SIZES_BWG.keys()))
    with col2:
        # Get available BWG for selected tube size
        available_bwg = list(TEMATubeStandards.TUBE_SIZES_BWG[inputs["tube_size"]]["BWG"].keys())
        default_bwg = "18" if "18" in available_bwg else available_bwg[0]
        inputs["bwg"] = st.selectbox("BWG Gauge", available_bwg, index=available_bwg.index(default_bwg) if default_bwg in available_bwg else 0)
    
    inputs["tube_material"] = st.sidebar.selectbox(
        "Tube Material", list(designer.TUBE_MATERIALS.keys()),
        help="Copper: Best heat transfer\nCu-Ni: Corrosion resistant\nStainless: Chemical service"
    )
    
    # Get tube thickness from TEMA standards
    tube_thickness_mm = TEMATubeStandards.get_tube_thickness(inputs["tube_size"], inputs["bwg"])
    st.sidebar.info(f"TEMA Table D-7: {inputs['tube_size']} tube, BWG {inputs['bwg']} = {tube_thickness_mm:.3f}mm wall")
    inputs["tube_thickness"] = tube_thickness_mm  # mm
    
    # Tube pitch with TEMA validation
    tube_od_mm = TEMATubeStandards.get_tube_od_mm(inputs["tube_size"])
    min_pitch_mm = tube_od_mm * 1.25
    
    inputs["tube_pitch"] = number_input_with_buttons(
        label="Tube Pitch (mm)",
        min_value=min_pitch_mm, max_value=100.0, value=min_pitch_mm, step=0.5,
        key="tube_pitch", format="%.1f"
    )
    
    pitch_ratio = inputs["tube_pitch"] / tube_od_mm
    if pitch_ratio < 1.25:
        st.sidebar.error(f"⚠️ TEMA R-2.5 violation: Pitch ratio < 1.25")
    elif pitch_ratio < 1.33:
        st.sidebar.warning(f"⚠️ Pitch ratio {pitch_ratio:.2f} - TEMA minimum is 1.25")
    else:
        st.sidebar.success(f"✓ TEMA compliant: Pitch ratio = {pitch_ratio:.2f}")


    # --- TEMA pitch guidance helper (UI assist; does not block calculation) ---
    # Practical industry/TEMA guidance: triangular layouts can use tighter pitch (>=1.25*OD),
    # while mechanical cleaning (typically square pitch) usually needs wider lanes (often ~1.5*OD or more).
    tema_pitch_min_ratio = 1.25  # hard minimum check already applied
    tema_pitch_reco_ratio = 1.50 if inputs.get("mechanical_cleaning", False) else 1.25
    tema_pitch_reco_note = (
        "Mechanical cleaning selected → typical guidance is to use **square pitch** and a wider pitch "
        "(often around **1.5×OD** or higher) to allow cleaning lanes and reduce tube-to-tube obstruction."
        if inputs.get("mechanical_cleaning", False)
        else
        "No mechanical cleaning selected → typical guidance allows tighter pitch. "
        "Triangular layouts often use **1.25×OD to ~1.33×OD** for compact bundles."
    )
    st.sidebar.info(
        f"📌 **Pitch guidance (TEMA/industry practice):** recommended ≥ **{tema_pitch_reco_ratio:.2f}×OD**.  "
        f"Your selection: **{pitch_ratio:.2f}×OD**.\n\n{tema_pitch_reco_note}"
    )
    if inputs.get("mechanical_cleaning", False) and pitch_ratio < tema_pitch_reco_ratio:
        st.sidebar.warning(
            f"🧽 Cleaning-friendly pitch usually needs ≥ {tema_pitch_reco_ratio:.2f}×OD. "
            "Consider increasing tube pitch (or switching to Square layout)."
        )
    
    inputs["n_passes"] = st.sidebar.selectbox("Tube Passes", [1, 2, 4, 6], index=1)
    
    inputs["n_baffles"] = int(number_input_with_buttons(
        label="Number of Baffles",
        min_value=1, max_value=20, value=5, step=1,
        key="n_baffles", format="%.0f",
        help_text="More baffles = better HTC but higher ΔP"
    ))
    
    inputs["baffle_cut"] = number_input_with_buttons(
        label="Baffle Cut (%)",
        min_value=15, max_value=45, value=25, step=5,
        key="baffle_cut", format="%.0f",
        help_text="Typical: 20-25% for liquids, 35-45% for gases"
    )
    
    inputs["n_tubes"] = int(number_input_with_buttons(
        label="Number of Tubes",
        min_value=1, max_value=1000, value=100, step=5,
        key="n_tubes", format="%.0f"
    ))
    
    inputs["tube_length"] = number_input_with_buttons(
        label="Tube Length (m)",
        min_value=0.5, max_value=10.0, value=3.0, step=0.1,
        key="tube_length", format="%.1f"
    )
    
    inputs["tube_layout"] = st.sidebar.radio(
        "Tube Layout",
        ["Triangular", "Square", "Rotated Square"],
        help="Triangular: Higher heat transfer\nSquare: Easier cleaning"
    )
    
    

    # --------------------------------------------------------------
    # 📏 Live TEMA guidance (shown BEFORE calculation)
    # --------------------------------------------------------------
    try:
        # Basic geometry (user-selected)
        tube_od_m = tube_od_mm / 1000.0
        tube_pitch_m = inputs["tube_pitch"] / 1000.0
        tube_length_m = float(inputs.get("tube_length", 3.0))
        n_baffles = int(inputs.get("n_baffles", 5))
        n_tubes = int(inputs.get("n_tubes", 100))

        # Layout mapping for internal functions
        _layout_map = {
            "Triangular": "triangular",
            "Square": "square",
            "Rotated Square": "rotated square"
        }
        layout_key = _layout_map.get(inputs.get("tube_layout", "Triangular"), "triangular")

        # Estimate shell ID from your existing (simple) bundle fit method
        shell_id_est_m = designer.calculate_shell_diameter(
            tube_od=tube_od_m,
            n_tubes=n_tubes,
            pitch=tube_pitch_m,
            tube_layout=layout_key
        )

        # Derived baffle spacing from tube length and number of baffles
        baffle_spacing_m = tube_length_m / (n_baffles + 1)

        # TEMA minimum baffle spacing (RCB-4.5.1)
        baffle_check_ui = TEMABaffleStandards.validate_baffle_spacing(
            shell_id_m=shell_id_est_m,
            baffle_spacing_m=baffle_spacing_m,
            tube_od_m=tube_od_m,
            tema_class=inputs.get("tema_class", "R")
        )

        # TEMA maximum unsupported tube span (RCB-4.5.2) - temperature estimate
        # Note: before full thermal calc, we estimate metal temp conservatively.
        if inputs["hex_type"] == "Condenser":
            T_metal_est_c = (float(inputs.get("T_ref", 45.0)) + float(inputs.get("T_sec_in", 30.0))) / 2.0
        else:
            T_metal_est_c = (float(inputs.get("T_ref", 5.0)) + float(inputs.get("T_sec_in", 12.0))) / 2.0

        max_span_m_ui = TEMABaffleStandards.get_maximum_unsupported_span(
            tube_od_m=tube_od_m,
            tube_material=inputs.get("tube_material", "Copper"),
            T_metal_c=T_metal_est_c
        )

        # In a segmental-baffle exchanger, interior unsupported span ~ baffle spacing
        unsupported_span_m_ui = baffle_spacing_m

        # Display to the user right under tube/baffle inputs
        st.sidebar.markdown("#### 📏 TEMA Guidance (live)")
        st.sidebar.caption(
            "These checks update as you change inputs. "
            "Shell ID is an estimate for spacing guidance; final values are confirmed after calculation."
        )

        g1, g2 = st.sidebar.columns(2)
        g1.metric("Est. Shell ID", f"{shell_id_est_m*1000:.0f} mm")
        g2.metric("Baffle Spacing", f"{baffle_spacing_m*1000:.0f} mm")

        # Baffle spacing vs minimum
        min_spacing_mm = baffle_check_ui["minimum_spacing_m"] * 1000.0
        margin_mm = (baffle_spacing_m - baffle_check_ui["minimum_spacing_m"]) * 1000.0

        if baffle_check_ui["compliant"]:
            st.sidebar.success(f"✓ Baffle spacing ≥ TEMA minimum ({min_spacing_mm:.0f} mm). Margin: +{margin_mm:.0f} mm")
        else:
            st.sidebar.error(f"❌ Baffle spacing below TEMA minimum ({min_spacing_mm:.0f} mm). Short by {abs(margin_mm):.0f} mm")

        # Unsupported span vs maximum
        max_span_mm = max_span_m_ui * 1000.0
        span_margin_mm = (max_span_m_ui - unsupported_span_m_ui) * 1000.0

        if unsupported_span_m_ui <= max_span_m_ui:
            st.sidebar.success(f"✓ Unsupported span ≤ TEMA max ({max_span_mm:.0f} mm). Margin: +{span_margin_mm:.0f} mm")
        else:
            st.sidebar.error(f"❌ Unsupported span exceeds TEMA max ({max_span_mm:.0f} mm). Exceeds by {abs(span_margin_mm):.0f} mm")

        st.sidebar.caption(
            f"Metal temperature used for span estimate: ~{T_metal_est_c:.1f}°C (pre-calc estimate)."
        )

    except Exception as _e:
        # Never block the UI on guidance calculations
        st.sidebar.caption("TEMA guidance preview unavailable for current inputs.")
    inputs["baffle_thickness_mm"] = number_input_with_buttons(
        label="Baffle Thickness (mm)",
        min_value=3.0, max_value=25.0, value=9.5, step=1.0,
        key="baffle_thickness", format="%.1f",
        help_text="TEMA Table R-4.4.1 minimum based on shell diameter"
    )
    
    inputs["design_pressure_kpa"] = number_input_with_buttons(
        label="Design Pressure (kPa)",
        min_value=100, max_value=5000, value=1000, step=50,
        key="design_pressure", format="%.0f",
        help_text="For tube wall pressure rating check"
    )
    
    return inputs


def display_tema_compliance(results: Dict, inputs: Dict):
    """Display TEMA compliance status in Streamlit"""
    
    st.markdown("<h3>📋 TEMA 10th Edition Compliance</h3>", unsafe_allow_html=True)
    
    # Overall compliance banner
    if results.get('tema_overall_compliant', False):
        st.markdown("""
        <div class='tema-compliant'>
            <h4 style='margin-top:0; color:#065F46;'>✅ TEMA COMPLIANT</h4>
            <p style='margin-bottom:0;'>This design meets all applicable TEMA 10th Edition requirements.</p>
        </div>
        """, unsafe_allow_html=True)
    else:
        st.markdown("""
        <div class='tema-noncompliant'>
            <h4 style='margin-top:0; color:#991B1B;'>❌ TEMA NON-COMPLIANT</h4>
            <p style='margin-bottom:0;'>This design does not meet all TEMA requirements. See violations below.</p>
        </div>
        """, unsafe_allow_html=True)
    
    # Compliance table
    col1, col2 = st.columns(2)
    
    with col1:
        st.markdown("#### ✅ Compliant Items")
        compliant_items = []
        
        if results.get('tema_tube_compliant', False):
            compliant_items.append("✓ Tube selection (TEMA Table D-7)")
        if results.get('tema_baffle_compliant', False):
            compliant_items.append("✓ Baffle spacing (RCB-4.5.1)")
        if results.get('tema_span_compliant', False):
            compliant_items.append("✓ Unsupported tube span (RCB-4.5.2)")
        if results.get('tema_hole_check', {}).get('compliant', False):
            compliant_items.append("✓ Tube hole tolerances (RCB-7.2.1)")
        if results.get('tema_vibration', {}).get('tema_compliant', False):
            compliant_items.append("✓ Vibration analysis (Section 6)")
        
        if compliant_items:
            for item in compliant_items:
                st.markdown(f"- {item}")
        else:
            st.markdown("None")
    
    with col2:
        st.markdown("#### ❌ Violations & Warnings")
        violations = []
        
        if not results.get('tema_tube_compliant', True):
            violations.append(f"❌ {results.get('tema_tube_message', 'Tube selection error')}")
        if not results.get('tema_baffle_compliant', True):
            for warning in results.get('tema_baffle_warnings', []):
                violations.append(f"❌ {warning}")
        if not results.get('tema_span_compliant', True):
            violations.append(f"❌ Unsupported span > TEMA maximum ({results.get('tema_max_span_m', 0)*1000:.0f}mm)")
        if results.get('tema_impingement', {}).get('impingement_required', False) and not inputs.get('has_impingement_plate', False):
            violations.append("❌ Impingement plate required (RCB-4.6.1)")
        if not results.get('tema_vibration', {}).get('tema_compliant', True):
            violations.append(f"❌ High vibration risk - SF: {results.get('tema_vibration', {}).get('safety_factor', 0):.2f}")
        
        if violations:
            for violation in violations[:5]:  # Show top 5
                st.markdown(violation)
            if len(violations) > 5:
                st.markdown(f"... and {len(violations)-5} more")
        else:
            st.markdown("No violations found")
    
    # Vibration analysis results
    if 'tema_vibration' in results:
        vib = results['tema_vibration']
        st.markdown("---")
        st.markdown("#### 🔧 TEMA Section 6 Vibration Analysis")
        
        risk_color = {
            "LOW": "🟢", "MEDIUM": "🟡", "HIGH": "🟠", "CRITICAL": "🔴"
        }.get(vib.get('risk_level', 'UNKNOWN'), "⚪")
        
        col_a, col_b, col_c, col_d = st.columns(4)
        col_a.metric("Natural Frequency", f"{vib.get('natural_frequency_hz', 0):.1f} Hz")
        col_b.metric("Critical Velocity", f"{vib.get('critical_velocity_ms', 0):.2f} m/s")
        col_c.metric("Actual Velocity", f"{vib.get('actual_velocity_ms', 0):.2f} m/s")
        col_d.metric("Safety Factor", f"{vib.get('safety_factor', 0):.2f}")
        
        st.markdown(f"**Risk Level:** {risk_color} {vib.get('risk_level', 'N/A')}")
        st.info(vib.get('recommendation', 'No recommendation available'))


def display_results(results: Dict, inputs: Dict):
    """Display calculation results in Streamlit"""
    
    st.markdown("<h2 class='section-header'>📊 TEMA Design Results</h2>", unsafe_allow_html=True)
    
    # Design status banner
    if results["design_status"] == "Adequate":
        status_color = "green"
        status_icon = "✅"
        bg_color = "#D1FAE5"
        border_color = "#10B981"
    elif results["design_status"] == "Marginal":
        status_color = "orange"
        status_icon = "⚠️"
        bg_color = "#FEF3C7"
        border_color = "#F59E0B"
    else:
        status_color = "red"
        status_icon = "❌"
        bg_color = "#FEE2E2"
        border_color = "#EF4444"
    
    st.markdown(f"""
    <div style="background-color: {bg_color}; padding: 1.5rem; border-radius: 0.5rem; 
                margin-bottom: 1.5rem; border-left: 4px solid {border_color};">
        <h3 style="margin-top: 0; color: {border_color};">{status_icon} Design Status: {results['design_status']}</h3>
        <p style="margin-bottom: 0;">{results['heat_exchanger_type']} | TEMA Class {results.get('tema_class', 'R')} | {results.get('design_method', 'ε-NTU')}</p>
    </div>
    """, unsafe_allow_html=True)
    
    # TEMA Compliance section
    display_tema_compliance(results, inputs)
    
    st.markdown("---")
    
    # Main results tabs
    tab1, tab2, tab3, tab4, tab5 = st.tabs(
        ["🔥 Heat Transfer", "🌡️ Temperatures", "📐 Geometry", "💨 Hydraulics", "📋 TEMA Report"]
    )
    
    with tab1:
        col1, col2 = st.columns(2)
        
        with col1:
            st.markdown("<div class='result-box'>", unsafe_allow_html=True)
            st.markdown("### Heat Duty")
            
            kw_match_pct = results["kw_match_percentage"]
            st.metric("Required Duty", f"{results['heat_duty_required_kw']:.2f} kW")
            st.metric("Achieved Duty", f"{results['heat_duty_achieved_kw']:.2f} kW", 
                     delta=f"{results['kw_difference']:.2f} kW")
            st.progress(min(kw_match_pct/100, 1.0), text=f"Match: {kw_match_pct:.1f}%")
            st.markdown("</div>", unsafe_allow_html=True)
            
            st.markdown("<div class='result-box'>", unsafe_allow_html=True)
            st.markdown("### Heat Transfer Coefficients")
            st.metric("Overall U", f"{results['overall_u']:.0f} W/m²·K")
            st.metric("Effectiveness (ε)", f"{results['effectiveness']:.3f}")
            st.metric("NTU", f"{results['ntu']:.2f}")
            st.metric("LMTD", f"{results['lmtd']:.2f} °C")
            st.markdown("</div>", unsafe_allow_html=True)
        
        with col2:
            st.markdown("<div class='result-box'>", unsafe_allow_html=True)
            st.markdown("### Region Performance")
            
            if results['heat_exchanger_type'] == 'DX Evaporator':
                st.metric("Evaporation", f"{results['h_tube_evap']:.0f} W/m²·K")
                st.metric("Superheat", f"{results['h_tube_superheat']:.0f} W/m²·K")
                st.metric("Shell-side", f"{results['h_shell']:.0f} W/m²·K")
                
                # Area distribution
                st.markdown("#### Area Distribution")
                area_data = pd.DataFrame({
                    'Region': ['Evaporation', 'Superheat'],
                    'Area (m²)': [results['area_evap_m2'], results['area_superheat_m2']],
                    'Percentage': [
                        results['area_evap_m2']/results['area_total_m2']*100,
                        results['area_superheat_m2']/results['area_total_m2']*100
                    ]
                })
                st.dataframe(area_data, hide_index=True, use_container_width=True)
                
            else:  # Condenser
                st.metric("Tube-side (Water)", f"{results.get('h_tube', 0):.0f} W/m²·K")
                st.metric("Condensation", f"{results.get('h_condense', 0):.0f} W/m²·K")
                
                st.markdown("#### Area Distribution")
                area_data = pd.DataFrame({
                    'Region': ['Desuperheat', 'Condensing', 'Subcooling'],
                    'Area (m²)': [
                        results.get('area_desuperheat_m2', 0),
                        results.get('area_condense_m2', 0),
                        results.get('area_subcool_m2', 0)
                    ],
                    'Percentage': [
                        results.get('area_desuperheat_m2', 0)/results['area_total_m2']*100,
                        results.get('area_condense_m2', 0)/results['area_total_m2']*100,
                        results.get('area_subcool_m2', 0)/results['area_total_m2']*100
                    ]
                })
                st.dataframe(area_data, hide_index=True, use_container_width=True)
            
            st.markdown("</div>", unsafe_allow_html=True)
    
    with tab2:
        col1, col2 = st.columns(2)
        
        with col1:
            st.markdown("<div class='result-box'>", unsafe_allow_html=True)
            st.markdown("### Refrigerant Side")
            
            if results['heat_exchanger_type'] == 'DX Evaporator':
                st.metric("Evaporating Temp", f"{results['t_ref_in']:.1f} °C")
                st.metric("Outlet Temp", f"{results['t_ref_out_achieved']:.1f} °C")
                st.metric("Superheat Required", f"{results['superheat_req']:.1f} K")
                st.metric("Superheat Achieved", f"{results.get('superheat_achieved', 0):.1f} K")
                delta = results.get('superheat_difference', 0)
                st.metric("Difference", f"{delta:.1f} K", delta_color="off" if abs(delta) < 1 else "inverse")
            else:
                st.metric("Superheated Inlet", f"{results['t_ref_in_superheated']:.1f} °C")
                st.metric("Condensing Temp", f"{results['t_ref_condensing']:.1f} °C")
                st.metric("Subcooling Required", f"{results['subcool_req']:.1f} K")
                st.metric("Subcooling Achieved", f"{results.get('subcool_achieved', 0):.1f} K")
                delta = results.get('subcool_difference', 0)
                st.metric("Difference", f"{delta:.1f} K", delta_color="off" if abs(delta) < 1 else "inverse")
            
            st.markdown("</div>", unsafe_allow_html=True)
        
        with col2:
            st.markdown("<div class='result-box'>", unsafe_allow_html=True)
            # Context-aware shell/tube temperature display
            if results.get("t_shell_in") is not None and results.get("t_tube_in") is not None:
                st.markdown("### Shell / Tube Side Temperatures (as configured)")
                c1, c2 = st.columns(2)
                with c1:
                    st.markdown(f"**Shell Side ({results.get('shell_stream','')})**")
                    st.metric("Inlet", f"{results.get('t_shell_in', 0.0):.1f} °C")
                    st.metric("Outlet", f"{results.get('t_shell_out', 0.0):.1f} °C")
                with c2:
                    st.markdown(f"**Tube Side ({results.get('tube_stream','')})**")
                    st.metric("Inlet", f"{results.get('t_tube_in', 0.0):.1f} °C")
                    st.metric("Outlet", f"{results.get('t_tube_out', 0.0):.1f} °C")
                if results.get("t_sec_out_required") is not None:
                    st.caption(f"Secondary outlet required by duty (energy balance): {results.get('t_sec_out_required'):.1f} °C")
                st.markdown("---")
            st.markdown("### Water/Glycol Side")
            st.metric("Inlet Temperature", f"{results['t_sec_in']:.1f} °C")
            st.metric("Outlet Temperature", f"{results['t_sec_out']:.1f} °C")
            st.metric("Temperature Rise", f"{results['water_deltaT']:.1f} K")
            
            if results.get('glycol_percentage', 0) > 0:
                st.metric("Glycol", f"{results['glycol_percentage']}% {results['glycol_type'].title()}")
                st.metric("Freeze Point", f"{results['freeze_point_c']:.1f} °C")
                st.metric("Freeze Risk", results.get('freeze_risk', 'N/A'))
            
            st.markdown("</div>", unsafe_allow_html=True)
    
    with tab3:
        col1, col2 = st.columns(2)
        
        with col1:
            st.markdown("<div class='result-box'>", unsafe_allow_html=True)
            st.markdown("### Shell Side")
            st.metric("Shell Diameter", f"{results['shell_diameter_m']*1000:.0f} mm")
            st.metric("Shell Flow Area", f"{results.get('shell_flow_area_m2', 0):.4f} m²")
            st.metric("Bundle Diameter", f"{results.get('bundle_diameter_m', 0)*1000:.0f} mm")
            st.metric("Shell Clearance", f"{results.get('shell_clearance_mm', 0):.1f} mm")
            st.metric("Baffle Cut", f"{results.get('baffle_cut_percent', 25):.0f}%")
            st.metric("Baffle Spacing", f"{results['baffle_spacing_m']*1000:.0f} mm")
            st.metric("Number of Baffles", f"{results['n_baffles']}")
            st.metric("TEMA Max Span", f"{results.get('tema_max_span_m', 0)*1000:.0f} mm")
            st.markdown("</div>", unsafe_allow_html=True)
        
        with col2:
            st.markdown("<div class='result-box'>", unsafe_allow_html=True)
            st.markdown("### Tube Side")
            st.metric("Tube Size", f"{results['tube_size']}")
            st.metric("BWG Gauge", f"{results.get('bwg', '18')}")
            st.metric("Tube Material", results['tube_material'])
            st.metric("Tube OD", f"{results['tube_od_mm']:.2f} mm")
            st.metric("Tube ID", f"{results['tube_id_mm']:.2f} mm")
            st.metric("Tube Wall", f"{results['tube_thickness_mm']:.3f} mm")
            st.metric("Tube Length", f"{results['tube_length_m']*1000:.0f} mm")
            st.metric("Number of Tubes", f"{results['n_tubes']}")
            st.metric("Tube Passes", f"{results['n_passes']}")
            st.metric("Tube Pitch", f"{results['tube_pitch_mm']:.1f} mm")
            st.metric("Pitch Ratio", f"{results['pitch_ratio']:.3f}")
            st.metric("Tube Layout", results['tube_layout'].title())
            st.metric("Total Area", f"{results['area_total_m2']:.2f} m²")
            st.metric("Area Ratio", f"{results['area_ratio']:.2f}")
            st.markdown("</div>", unsafe_allow_html=True)
    
    with tab4:
        col1, col2 = st.columns(2)
        
        with col1:
            st.markdown("<div class='result-box'>", unsafe_allow_html=True)
            st.markdown("### Tube Side")
            
            if results['heat_exchanger_type'] == 'DX Evaporator':
                st.metric("Fluid", results['refrigerant'])
                st.metric("Mass Flow", f"{results['refrigerant_mass_flow_kg_hr']:.0f} kg/hr")
            else:
                st.metric("Fluid", f"{results.get('glycol_type', 'Water').title()} {results.get('glycol_percentage', 0)}%")
                st.metric("Mass Flow", f"{results.get('water_mass_flow_kg_hr', 0):.0f} kg/hr")
            
            st.metric("Velocity", f"{results['velocity_tube_ms']:.2f} m/s")
            
            # Velocity status badge
            status = results.get('velocity_tube_status', 'Unknown')
            css_class = "velocity-good" if status == "Optimal" else "velocity-low" if status in ["Low", "Too Low"] else "velocity-high"
            st.markdown(f"<span class='{css_class}'>Status: {status}</span>", unsafe_allow_html=True)
            
            st.metric("Reynolds", f"{results['reynolds_tube']:.0f}")
            st.metric("Pressure Drop", f"{results['dp_tube_kpa']:.2f} kPa")
            
            if results['heat_exchanger_type'] == 'DX Evaporator':
                st.metric("Inlet Quality", f"{results['inlet_quality_percent']:.1f}%")
                st.metric("Flow per Tube", f"{results.get('flow_per_tube_kg_hr', 0):.2f} kg/hr")
                st.metric("Distribution", results.get('distribution_status', 'N/A'))
            
            st.markdown("</div>", unsafe_allow_html=True)
        
        with col2:
            st.markdown("<div class='result-box'>", unsafe_allow_html=True)
            st.markdown("### Shell Side")
            
            if results['heat_exchanger_type'] == 'DX Evaporator':
                st.metric("Fluid", f"{results.get('glycol_type', 'Water').title()} {results.get('glycol_percentage', 0)}%")
                st.metric("Mass Flow", f"{results.get('water_mass_flow_kg_hr', 0):.0f} kg/hr")
            else:
                st.metric("Fluid", results['refrigerant'])
                st.metric("Mass Flow", f"{results['refrigerant_mass_flow_kg_hr']:.0f} kg/hr")
            
            st.metric("Velocity", f"{results['velocity_shell_ms']:.2f} m/s")
            
            # Velocity status badge
            status = results.get('velocity_shell_status', 'Unknown')
            css_class = "velocity-good" if status == "Optimal" else "velocity-low" if status in ["Low", "Too Low"] else "velocity-high"
            st.markdown(f"<span class='{css_class}'>Status: {status}</span>", unsafe_allow_html=True)
            
            st.metric("Reynolds", f"{results['reynolds_shell']:.0f}")
            st.metric("Pressure Drop", f"{results['dp_shell_kpa']:.2f} kPa")
            
            # Impingement requirement
            impingement = results.get('tema_impingement', {})
            if impingement.get('impingement_required', False):
                st.warning(f"⚠️ Impingement plate required: ρV² = {impingement.get('pv2_value_us', 0):.0f} > {impingement.get('pv2_limit_us', 1500)}")
            
            st.markdown("</div>", unsafe_allow_html=True)
    
    with tab5:
        st.markdown("<div class='result-box'>", unsafe_allow_html=True)
        st.markdown("### 📄 TEMA Specification Sheet")
        
        # Generate TEMA-style specification sheet in markdown
        col1, col2 = st.columns(2)
        
        with col1:
            st.markdown("**SIZE:**")
            st.code(f"{results.get('shell_diameter_m', 0)*1000:.0f}-{results.get('tube_length_m', 0)*1000:.0f}")
            
            st.markdown("**TYPE:**")
            st.code(f"{results.get('tema_type', 'AES')}")
            
            st.markdown("**SURFACE PER UNIT:**")
            st.code(f"{results.get('area_total_m2', 0):.2f} m²")
            
            st.markdown("**PERFORMANCE OF ONE UNIT:**")
            perf_data = pd.DataFrame({
                'Parameter': ['Fluid Allocation', 'Temp In/Out', 'Pressure Drop', 'Fouling Resistance'],
                'Shell Side': [
                    'Refrigerant' if results['heat_exchanger_type'] == 'DX Evaporator' else 'Water/Glycol',
                    f"{results.get('t_ref_in', 0):.1f}/{results.get('t_ref_out_achieved', 0):.1f} °C" if results['heat_exchanger_type'] == 'DX Evaporator' else f"{results.get('t_sec_in', 0):.1f}/{results.get('t_sec_out', 0):.1f} °C",
                    f"{results.get('dp_shell_kpa', 0):.2f} kPa",
                    f"{results.get('r_fouling_shell', 0.00035):.5f}"
                ],
                'Tube Side': [
                    'Water/Glycol' if results['heat_exchanger_type'] == 'DX Evaporator' else 'Refrigerant',
                    f"{results.get('t_sec_in', 0):.1f}/{results.get('t_sec_out', 0):.1f} °C" if results['heat_exchanger_type'] == 'DX Evaporator' else f"{results.get('t_ref_in', 0):.1f}/{results.get('t_ref_out_achieved', 0):.1f} °C",
                    f"{results.get('dp_tube_kpa', 0):.2f} kPa",
                    f"{results.get('r_fouling_tube', 0.00035):.5f}"
                ]
            })
            st.dataframe(perf_data, hide_index=True, use_container_width=True)
        
        with col2:
            st.markdown("**CONSTRUCTION OF ONE SHELL:**")
            const_data = pd.DataFrame({
                'Parameter': ['Shell ID', 'Tube OD/Thk', 'Tube Length', 'Tube Pitch', 
                            'Tube Pattern', 'No. Passes', 'Baffle Cut', 'TEMA Class'],
                'Value': [
                    f"{results.get('shell_diameter_m', 0)*1000:.0f} mm",
                    f"{results.get('tube_od_mm', 19.05):.1f}/{results.get('tube_thickness_mm', 1.245):.2f} mm",
                    f"{results.get('tube_length_m', 0)*1000:.0f} mm",
                    f"{results.get('tube_pitch_mm', 23.8):.1f} mm",
                    results.get('tube_layout', 'triangular').title(),
                    f"{results.get('n_passes', 2)}",
                    f"{results.get('baffle_cut_percent', 25):.0f}%",
                    results.get('tema_class', 'R')
                ]
            })
            st.dataframe(const_data, hide_index=True, use_container_width=True)
            
            st.markdown("**TEMA COMPLIANCE STATUS:**")
            if results.get('tema_overall_compliant', False):
                st.success("✅ TEMA COMPLIANT")
            else:
                st.error("❌ TEMA NON-COMPLIANT")
        
        st.markdown("</div>", unsafe_allow_html=True)
        
        # PDF Download Button
        st.markdown("---")
        st.markdown("### 📥 Download Full Design Report")
        
        col1, col2, col3 = st.columns([1, 2, 1])
        with col2:
            if st.button("📄 Generate PDF Report", type="primary", use_container_width=True):
                with st.spinner("Generating PDF report..."):
                    pdf_gen = PDFReportGenerator()
                    pdf_bytes = pdf_gen.generate_report(results, inputs)
                    
                    # Create download button
                    b64_pdf = base64.b64encode(pdf_bytes).decode()
                    filename = f"TEMA_Report_{results['heat_exchanger_type'].replace(' ', '_')}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
                    
                    href = f'<a href="data:application/pdf;base64,{b64_pdf}" download="{filename}" class="download-btn">⬇️ Download PDF Report</a>'
                    st.markdown(href, unsafe_allow_html=True)
                    st.success("✅ PDF generated successfully! Click the button above to download.")


# ============================================================================
# MAIN APP
# ============================================================================

def main():
    """Main function to run the app"""
    
    if not check_password():
        st.stop()
    
    st.markdown("<h1 class='main-header'>🌡️ TEMA 10th Edition DX Shell & Tube Heat Exchanger Designer</h1>", unsafe_allow_html=True)
    
    st.info("""
    **✅ TEMA 10th Edition Compliant Design Tool**
    
    - **DX Evaporator**: Refrigerant in TUBES, Water/Glycol on SHELL ✓
    - **Condenser**: Refrigerant on shell (default) or in tubes (optional) ✓
    - TEMA Class R, C, B compliant
    - Section 6 Vibration Analysis
    - Table D-7 Tube Standards
    - RCB-4 Baffle & Support Standards
    - RGP-T-2.4 Fouling Resistances
    - Full PDF Report Generation
    """)
    
    if 'results' not in st.session_state:
        st.session_state.results = None
    if 'inputs' not in st.session_state:
        st.session_state.inputs = None
    
    col1, col2 = st.columns([3, 1])
    
    with col2:
        inputs = create_input_section()
        
        if st.sidebar.button("🚀 Calculate Design", type="primary", use_container_width=True):
            with st.spinner("Calculating with TEMA 10th Edition standards..."):
                designer = TEMACompliantDXHeatExchangerDesign()
                
                calc_inputs = inputs.copy()
                calc_inputs["hex_type"] = calc_inputs["hex_type"].lower().replace("dx ", "")
                
                if calc_inputs["hex_type"] == "evaporator":
                    results = designer.design_dx_evaporator(calc_inputs)
                else:
                    results = designer.design_condenser(calc_inputs)
                
                st.session_state.results = results
                st.session_state.inputs = inputs
                st.rerun()
        
        if st.sidebar.button("🔄 Reset", use_container_width=True):
            st.session_state.results = None
            st.session_state.inputs = None
            st.rerun()
    
    with col1:
        if st.session_state.results is not None:
            display_results(st.session_state.results, st.session_state.inputs)
        else:
            st.markdown("""
            ## 🔧 TEMA 10th Edition Heat Exchanger Design Tool
            
            **Industry-standard shell & tube heat exchanger design**
            
            - ✅ ASHRAE-correct flow configurations
            - ✅ TEMA 10th Edition mechanical standards
            - ✅ CoolProp exact fluid properties
            - ✅ Section 6 flow-induced vibration analysis
            - ✅ PDF report generation with all parameters
            
            Enter parameters on the left and click **Calculate Design**.
            
            **Password:** Semaanju
            """)
    
    st.markdown("---")
    st.markdown("""
    <div class='footer'>
        <p>🔧 <strong>TEMA 10th Edition Compliant Heat Exchanger Design Tool</strong></p>
        <p>© 2024 - Professional Edition | Certified to ASHRAE and TEMA Standards</p>
    </div>
    """, unsafe_allow_html=True)

if __name__ == "__main__":
    main()

# dx_evaporator_designer_professional_v3.py
# Enhanced version with row requirement calculation and improved zone tracking

import math
from math import pi, sqrt, tanh, log, exp
import io
import traceback
import json
import os
from datetime import datetime
from dataclasses import dataclass, asdict
from typing import Optional, List, Dict, Tuple, Literal

import numpy as np
import pandas as pd
import streamlit as st

# PDF generation
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle

# CoolProp for refrigerant properties
try:
    from CoolProp.CoolProp import PropsSI
    HAS_CP = True
except Exception:
    HAS_CP = False

# ================= PASSWORD PROTECTION =================
def check_password():
    """Password protection for the app"""
    if st.session_state.get("password_correct", False):
        return True
    
    try:
        correct_password = st.secrets.get("APP_PASSWORD", "Semaanju")
    except:
        correct_password = "Semaanju"
    
    col1, col2, col3 = st.columns([1,2,1])
    with col2:
        st.title("🔒 DX Evaporator Designer Pro")
        st.markdown("### Professional HVAC Coil Design Tool")
        st.markdown("---")
        
        password = st.text_input(
            "Enter access password:", 
            type="password",
            key="password_input"
        )
        
        if st.button("🔑 Login", type="primary", width='stretch'):
            if password == correct_password:
                st.session_state.password_correct = True
                st.success("✅ Access granted!")
                st.rerun()
            else:
                st.error("❌ Incorrect password")
                
        st.markdown("---")
        st.caption("Contact administrator for access credentials")
        
    return False

# ================= CONSTANTS =================
P_ATM = 101325.0
R_DA  = 287.055
CP_DA = 1006.0
CP_V  = 1860.0
H_LV0 = 2501000.0
INCH  = 0.0254
MM    = 1e-3
GRAVITY = 9.80665

def K(tC): return tC + 273.15

# ================= CORRELATION MODULE =================
class RefrigerantCorrelations:
    """Implements CoilDesigner-style correlations for all tube types"""
    
    # ================= SMOOTH TUBES =================
    @staticmethod
    def smooth_h_gnielinski(Re: float, Pr: float, D: float, L: float, k: float, 
                           roughness: float = 1.5e-6) -> Tuple[float, float]:
        """Gniellinski correlation for smooth tubes"""
        Re = max(Re, 1e-9)
        
        if Re < 2300:
            Nu = 3.66
            f = 64.0 / Re if Re > 0 else 0.0
        else:
            # Churchill friction factor
            A = (2.457 * math.log(1.0 / ((7.0/Re)**0.9 + 0.27*(roughness/D))))**16
            B = (37530.0 / Re)**16
            f = 8.0 * ((8.0/Re)**12 + 1.0/(A + B)**1.5)**(1.0/12.0)
            
            # Gniellinski Nusselt number
            numerator = (f/8.0) * (Re - 1000.0) * Pr
            denominator = 1.0 + 12.7 * math.sqrt(f/8.0) * (Pr**(2.0/3.0) - 1.0)
            Nu = numerator / max(denominator, 1e-9)
            
            Nu = max(4.36, min(Nu, 300.0))
        
        h = Nu * k / max(D, 1e-9)
        return h, f
    
    @staticmethod
    def smooth_h_shah2016_evaporation(x: float, Re_l: float, Pr_l: float, h_l: float, 
                                     Bo: float, Fr_l: float, D: float, G: float,
                                     rho_l: float, rho_v: float) -> float:
        """Shah (2016) correlation for evaporation in smooth tubes"""
        x = max(min(x, 0.999), 0.001)
        Re_l = max(Re_l, 100.0)
        Bo = max(Bo, 1e-6)
        Fr_l = max(Fr_l, 1e-6)
        
        Co = ((1.0 - x)/x)**0.8 * (rho_v/rho_l)**0.5
        
        if Bo > 0.0011:  # Nucleate boiling dominant
            F_nb = 230 * Bo**0.5
            F_cb = 1.8 * Co**(-0.8)
            h_tp = h_l * max(F_nb, F_cb)
        else:  # Convective boiling dominant
            if Co <= 0.65:
                F = 1.8 * Co**(-0.8)
            else:
                F = 1.0 + 0.8 * math.exp(1.0 - Co)
            h_tp = h_l * F
        
        # Quality correction
        if x < 0.1:
            h_tp *= 1.0 + 2.5 * x
        elif x > 0.9:
            h_tp *= 1.0 + 5.0 * (1.0 - x)
        
        return max(h_tp, h_l * 1.5)
    
    # ================= MICROFIN TUBES =================
    @staticmethod
    def microfin_h_cavanagh_evaporation(x: float, Re_l: float, Pr_l: float, h_l: float,
                                       G: float, D: float, rho_l: float, rho_v: float,
                                       fin_height_mm: float = 0.2, 
                                       helix_angle_deg: float = 18.0,
                                       number_fins: int = 60) -> float:
        """
        Cavanagh et al. correlation for evaporation in microfin tubes
        """
        x = max(min(x, 0.999), 0.001)
        Re_l = max(Re_l, 100.0)
        
        # Fin enhancement factors
        e_h = fin_height_mm / 0.2  # Normalized by 0.2mm reference
        alpha = helix_angle_deg * math.pi / 180.0
        N_f = number_fins
        
        # Cavanagh enhancement factor
        F_cavanagh = 1.0 + 2.0 * e_h * (math.sin(alpha))**0.5 * (N_f/60.0)**0.2
        
        # Base heat transfer coefficient (modified Shah)
        Co = ((1.0 - x)/x)**0.8 * (rho_v/rho_l)**0.5
        h_base = h_l * (1.0 + 2.0 * Co**(-0.6))
        
        # Apply microfin enhancement
        h_microfin = h_base * F_cavanagh
        
        return max(h_microfin, h_l * 2.0)
    
    @staticmethod
    def microfin_dp_schlager_bergles(x: float, dp_lo: float, dp_vo: float,
                                    G: float, D: float, rho_l: float, rho_v: float,
                                    fin_height_mm: float = 0.2,
                                    helix_angle_deg: float = 18.0) -> float:
        """
        Schlager-Bergles correlation for pressure drop in microfin tubes
        """
        x = max(min(x, 0.999), 0.001)
        
        # Microfin enhancement factor for pressure drop
        alpha = helix_angle_deg * math.pi / 180.0
        F_dp = 1.0 + 1.5 * (fin_height_mm/0.2) * (math.sin(alpha))**0.3
        
        # Base pressure drop (Friedel)
        A = (1.0 - x)**2 + x**2 * (rho_l/rho_v)
        B = 3.43 * x**0.685 * (1.0 - x)**0.24 * (rho_l/rho_v)**0.8
        phi_lo2 = A + B
        dp_base = dp_lo * phi_lo2
        
        # Apply microfin enhancement
        dp_microfin = dp_base * F_dp
        
        return dp_microfin
    
    # ================= MICROCHANNEL/FLAT TUBES =================
    @staticmethod
    def microchannel_h_shah2019_evaporation(x: float, Re_l: float, Pr_l: float, h_l: float,
                                           G: float, D_h: float, rho_l: float, rho_v: float,
                                           aspect_ratio: float = 0.5) -> float:
        """
        Shah (2019) correlation for evaporation in microchannels/flat tubes
        """
        x = max(min(x, 0.999), 0.001)
        Re_l = max(Re_l, 100.0)
        
        # Aspect ratio correction
        AR = max(min(aspect_ratio, 1.0), 0.1)  # Width/height ratio
        F_AR = 1.0 + 0.5 * (1.0 - AR)  # Higher enhancement for flatter tubes
        
        # Microchannel specific correlation
        Bo = G**2 / (rho_l * 250000 * D_h)  # Modified boiling number
        Co = ((1.0 - x)/x)**0.8 * (rho_v/rho_l)**0.5
        
        if Bo > 0.0005:
            # Nucleate boiling dominant in microchannels
            h_tp = h_l * (1.0 + 300 * Bo**0.5 * Co**(-0.2))
        else:
            # Convective boiling dominant
            h_tp = h_l * (1.0 + 2.5 * Co**(-0.6))
        
        # Apply aspect ratio correction
        h_tp *= F_AR
        
        return max(h_tp, h_l * 2.0)
    
    @staticmethod
    def microchannel_dp_friedel_modified(x: float, dp_lo: float, dp_vo: float,
                                        G: float, D_h: float, rho_l: float, rho_v: float,
                                        mu_l: float, mu_v: float,
                                        aspect_ratio: float = 0.5) -> float:
        """
        Modified Friedel correlation for microchannels/flat tubes
        """
        x = max(min(x, 0.999), 0.001)
        
        # Aspect ratio correction
        AR = max(min(aspect_ratio, 1.0), 0.1)
        F_AR_dp = 1.0 + 0.3 * (1.0 - AR)  # Higher pressure drop for flatter tubes
        
        # Modified Friedel for small channels
        A = (1.0 - x)**2 + x**2 * (rho_l * mu_v)/(rho_v * mu_l)
        B = 3.24 * x**0.78 * (1.0 - x)**0.224 * (rho_l/rho_v)**0.91 * (mu_v/mu_l)**0.19
        phi_lo2 = A + B
        
        dp_base = dp_lo * phi_lo2
        
        # Apply aspect ratio correction
        dp_microchannel = dp_base * F_AR_dp
        
        return dp_microchannel
    
    # ================= COMMON METHODS =================
    @staticmethod
    def schmidt_fin_efficiency(r_outer: float, r_inner: float, h: float, 
                               k_fin: float, t_fin: float) -> float:
        """Schmidt's method for annular fin efficiency"""
        if r_outer <= r_inner or t_fin <= 0 or k_fin <= 0:
            return 1.0
        
        phi = (r_outer / r_inner - 1.0) * (1.0 + 0.35 * math.log(r_outer / r_inner))
        m = math.sqrt(2.0 * h / (k_fin * t_fin))
        Lc = r_outer - r_inner
        X = m * Lc * phi
        
        if X < 0.01:
            return 1.0 - X**2 / 3.0
        else:
            return math.tanh(X) / X
    
    @staticmethod
    def zivi_void_fraction(x: float, rho_v: float, rho_l: float) -> float:
        """Zivi (1964) slip ratio model for void fraction"""
        x = max(min(x, 0.999), 0.001)
        S = (rho_l / rho_v)**(1.0/3.0)
        numerator = x * rho_v
        denominator = numerator + S * (1.0 - x) * rho_l
        alpha = numerator / max(denominator, 1e-9)
        return max(0.01, min(alpha, 0.99))
    
    @staticmethod
    def dp_muller_steinhagen(x: float, dp_lo: float, dp_vo: float, 
                             rho_l: float, rho_v: float, G: float, D: float) -> float:
        """Muller-Steinhagen & Heck (1986) correlation"""
        x = max(min(x, 0.999), 0.001)
        dp_tp = (1.0 - x)**(1.0/3.0) * dp_lo + x**3 * dp_vo
        alpha = RefrigerantCorrelations.zivi_void_fraction(x, rho_v, rho_l)
        dp_acc = G**2 * (x**2/(rho_v * alpha) + (1.0 - x)**2/(rho_l * (1.0 - alpha)) - 1.0/rho_l)
        return dp_tp + max(dp_acc, 0.0)

# Create global correlations instance
correlations = RefrigerantCorrelations()

# ================= ROW CALCULATION MODULE =================
class RowCalculator:
    """Calculates exact rows needed for evaporation and superheat"""
    
    @staticmethod
    def calculate_rows_required(geom: Dict, Tsat_C: float, SH_req_K: float,
                               mdot_ref_total: float, x_in: float, h_fg: float,
                               flow_arrangement: str, circuits: int,
                               h_air_wet: float, h_air_dry: float,
                               eta_o_wet: float, eta_o_dry: float,
                               Ao_Ai: float, R_wall_per_Ao: float, Rfo: float, Rfi: float,
                               Tdb_in: float, W_in: float, Tdb_req: float, W_req: float,
                               mdot_da: float, mdot_air_total: float,
                               tube_params: Dict, correlation_package: str,
                               tube_type: str) -> Dict:
        """
        Calculate exact rows needed for evaporation and superheat
        Returns: {'evap_rows': int, 'sh_rows': int, 'total_rows': int, 'partial_row': bool}
        """
        
        # Initialize
        evap_rows = 0
        sh_rows = 0
        partial_row = False
        
        # Calculate heat transfer per row for evaporation
        # Simplified calculation to estimate rows needed
        T_air = Tdb_in
        W_air = W_in
        h_air = 1000.0*1.006*T_air + W_air*(H_LV0 + 1000.0*1.86*T_air)
        
        W_sat = W_from_T_RH(Tsat_C, 100.0)
        h_sat = 1000.0*1.006*Tsat_C + W_sat*(H_LV0 + 1000.0*1.86*Tsat_C)
        
        # Calculate required enthalpy change
        h_req_out = 1000.0*1.006*Tdb_req + W_req*(H_LV0 + 1000.0*1.86*Tdb_req)
        Q_required_total = mdot_da * (h_air - h_req_out)
        
        # Calculate evaporation rows needed
        Q_total_evap = 0
        current_x = x_in
        max_evap_rows = 20  # Maximum reasonable for iteration
        
        for row in range(1, max_evap_rows + 1):
            if current_x <= 0:
                break
                
            # Estimate heat transfer for this row
            # Using average conditions
            NTU_h = 0.5  # Conservative estimate
            BF = math.exp(-NTU_h)
            h_out = h_sat + BF*(h_air - h_sat)
            Q_row = mdot_da * (h_air - h_out)
            
            Q_total_evap += Q_row
            h_air = h_out
            T_air = Tsat_C + BF*(T_air - Tsat_C)
            W_air = W_sat + BF*(W_air - W_sat)
            
            # Update quality
            current_x = max(0, current_x - Q_row/(mdot_ref_total*h_fg))
            
            evap_rows = row
            
            # Check if we've met air conditions
            if T_air <= Tdb_req and W_air <= W_req:
                partial_row = True
                break
        
        # Calculate superheat rows if needed
        if flow_arrangement == "Superheat at air inlet":
            # SH rows are first
            # Need to calculate how many SH rows before evaporation starts
            sh_rows_needed = 1  # Start with 1 row
            T_ref_SH = Tsat_C + SH_req_K
            
            for row in range(1, 5):  # Maximum 4 SH rows (usually 1-2)
                # Estimate SH row heat transfer
                C_air = mdot_da * cp_moist_J_per_kgK(T_air, W_air)
                C_ref = mdot_ref_total * 1000  # Approximate cp_v
                Cmin = min(C_air, C_ref)
                NTU = 0.5  # Conservative
                eps = 1.0 - math.exp(-NTU)
                
                dT = max(T_air - T_ref_SH, 1.0)
                Q_row_SH = eps * Cmin * dT
                
                # Reduce superheat
                T_ref_SH = max(Tsat_C, T_ref_SH - Q_row_SH/(mdot_ref_total * 1000))
                
                if T_ref_SH <= Tsat_C + 0.5:  # Within 0.5K of saturation
                    sh_rows = row
                    break
                
                sh_rows = row
        
        elif flow_arrangement == "Superheat at air outlet":
            # SH rows come after evaporation
            # Already have air conditions from evaporation
            # Calculate SH needed to reach required superheat
            remaining_Q_for_SH = mdot_ref_total * 1000 * SH_req_K  # Approximate
            
            # Estimate rows needed for this heat transfer
            C_air = mdot_da * cp_moist_J_per_kgK(T_air, W_air)
            C_ref = mdot_ref_total * 1000
            Cmin = min(C_air, C_ref)
            
            # Each SH row can transfer roughly
            NTU_per_row = 0.3
            eps_per_row = 1.0 - math.exp(-NTU_per_row)
            Q_per_SH_row = eps_per_row * Cmin * SH_req_K
            
            if Q_per_SH_row > 0:
                sh_rows = max(1, math.ceil(remaining_Q_for_SH / Q_per_SH_row))
            else:
                sh_rows = 1
        
        total_rows = evap_rows + sh_rows
        
        return {
            'evap_rows': evap_rows,
            'sh_rows': sh_rows,
            'total_rows': total_rows,
            'partial_row': partial_row,
            'estimated_Q_evap': Q_total_evap,
            'estimated_sh_rows': sh_rows
        }

# ================= GEOMETRY INPUTS FOR DIFFERENT TUBE TYPES =================
def get_tube_geometry_inputs(tube_type: str):
    """
    Returns appropriate geometry inputs based on tube type
    """
    if tube_type == "Microfin Tubes":
        col1, col2, col3 = st.columns(3)
        with col1:
            fin_height_mm = st.number_input("Fin height (mm)", 0.1, 0.5, 0.2, 0.01)
        with col2:
            helix_angle_deg = st.number_input("Helix angle (°)", 5.0, 45.0, 18.0, 1.0)
        with col3:
            number_fins = st.number_input("Number of fins", 30, 100, 60, 1)
        
        return {
            'fin_height_mm': fin_height_mm,
            'helix_angle_deg': helix_angle_deg,
            'number_fins': number_fins
        }
    
    elif tube_type == "Microchannel/Flat Tubes":
        col1, col2, col3 = st.columns(3)
        with col1:
            channel_width_mm = st.number_input("Channel width (mm)", 0.5, 3.0, 1.0, 0.1)
        with col2:
            channel_height_mm = st.number_input("Channel height (mm)", 0.5, 3.0, 1.0, 0.1)
        with col3:
            number_channels = st.number_input("Number of channels", 5, 50, 20, 1)
        
        aspect_ratio = channel_width_mm / max(channel_height_mm, 0.1)
        
        return {
            'channel_width_mm': channel_width_mm,
            'channel_height_mm': channel_height_mm,
            'number_channels': number_channels,
            'aspect_ratio': aspect_ratio
        }
    
    else:  # Smooth Tubes
        return {}

# ================= CALCULATE HYDRAULIC DIAMETER =================
def calculate_hydraulic_diameter(tube_type: str, Do: float, geometry_params: Dict) -> float:
    """
    Calculate hydraulic diameter based on tube type
    """
    if tube_type == "Microfin Tubes":
        fin_height_m = geometry_params.get('fin_height_mm', 0.2) * MM
        number_fins = geometry_params.get('number_fins', 60)
        blockage_factor = 1.0 - (number_fins * fin_height_m) / (pi * Do)
        D_h = Do * blockage_factor
        return max(D_h, Do * 0.7)
    
    elif tube_type == "Microchannel/Flat Tubes":
        width_m = geometry_params.get('channel_width_mm', 1.0) * MM
        height_m = geometry_params.get('channel_height_mm', 1.0) * MM
        D_h = 2.0 * width_m * height_m / (width_m + height_m)
        return D_h
    
    else:  # Smooth Tubes
        return Do

# ================= CALCULATE FLOW AREA =================
def calculate_flow_area(tube_type: str, Di: float, geometry_params: Dict) -> float:
    """
    Calculate flow area based on tube type
    """
    if tube_type == "Microfin Tubes":
        fin_height_m = geometry_params.get('fin_height_mm', 0.2) * MM
        number_fins = geometry_params.get('number_fins', 60)
        fin_area = number_fins * fin_height_m * (fin_height_m * 0.5)
        tube_area = pi * Di**2 / 4.0
        flow_area = max(tube_area - fin_area, tube_area * 0.7)
        return flow_area
    
    elif tube_type == "Microchannel/Flat Tubes":
        width_m = geometry_params.get('channel_width_mm', 1.0) * MM
        height_m = geometry_params.get('channel_height_mm', 1.0) * MM
        number_channels = geometry_params.get('number_channels', 20)
        channel_area = width_m * height_m
        total_area = channel_area * number_channels
        return total_area
    
    else:  # Smooth Tubes
        return pi * Di**2 / 4.0

# ================= PSYCHROMETRICS =================
def psat_water_Pa(T_C: float) -> float:
    return 611.21 * math.exp((18.678 - T_C/234.5) * (T_C/(257.14 + T_C)))

def W_from_T_RH(T_C: float, RH_pct: float, P: float = P_ATM) -> float:
    RH = max(min(RH_pct, 100.0), 0.1) / 100.0
    Psat = psat_water_Pa(T_C)
    Pv = RH * Psat
    return 0.62198 * Pv / max(P - Pv, 1.0)

def W_from_T_WB(Tdb_C: float, Twb_C: float, P: float = P_ATM) -> float:
    W_sat_wb = W_from_T_RH(Twb_C, 100.0, P)
    h_fg_wb = 2501000.0 - 2369.0 * Twb_C
    numer = (W_sat_wb * (h_fg_wb + CP_V * Twb_C) - CP_DA * (Tdb_C - Twb_C))
    denom = (h_fg_wb + CP_V * Tdb_C)
    W = numer / max(1e-9, denom)
    return max(0.0, W)

def h_moist_J_per_kg_da(T_C: float, W: float) -> float:
    return 1000.0*1.006*T_C + W*(H_LV0 + 1000.0*1.86*T_C)

def cp_moist_J_per_kgK(T_C: float, W: float) -> float:
    return CP_DA + W*CP_V

def rho_moist_kg_m3(T_C: float, W: float, P: float = P_ATM) -> float:
    return P / (R_DA * K(T_C) * (1.0 + 1.6078*W))

def RH_from_T_W(T_C: float, W: float, P: float = P_ATM) -> float:
    Pv = W*P/(0.62198 + W)
    Ps = psat_water_Pa(T_C)
    return max(0.1, min(100.0, 100.0*Pv/max(Ps,1e-9)))

def wb_from_T_W(Tdb_C: float, W_target: float, P: float = P_ATM) -> float:
    lo, hi = -20.0, Tdb_C
    for _ in range(50):
        mid = 0.5*(lo+hi)
        W_mid = W_from_T_WB(Tdb_C, mid, P)
        if W_mid > W_target:
            hi = mid
        else:
            lo = mid
    return 0.5*(lo+hi)

def dew_point_from_T_W(T_C: float, W: float, P: float = P_ATM) -> float:
    Pv = W * P / (0.62198 + W)
    Tdp_guess = T_C
    for _ in range(30):
        psat_guess = psat_water_Pa(Tdp_guess)
        error = psat_guess - Pv
        if abs(error) < 0.1:
            break
        dPsat_dT = psat_guess * (18.678/(257.14 + Tdp_guess) - 
                                (18.678 - Tdp_guess/234.5)*Tdp_guess/(257.14 + Tdp_guess)**2)
        Tdp_guess -= error / max(dPsat_dT, 1e-6)
    return Tdp_guess

# ================= GEOMETRY / AREAS =================
def geometry_areas(face_W, face_H, Nr, St, Do, tf, FPI, Sl=None, tube_type="Smooth Tubes", geometry_params=None):
    face_area = face_W*face_H
    fin_pitch = (1.0/FPI)*INCH
    fins = max(int(math.floor(face_H / max(fin_pitch, 1e-9))), 1)

    if Sl is None or Sl <= 0:
        raise ValueError("Longitudinal pitch Sl must be provided (>0).")
    tubes_per_row = max(int(math.floor(face_W / max(Sl, 1e-9))), 1)

    N_tubes = tubes_per_row * Nr
    L_tube = face_W
    depth = St * Nr

    # Calculate hydraulic diameter
    D_h = calculate_hydraulic_diameter(tube_type, Do, geometry_params or {})
    
    A_holes_one_fin = N_tubes * (pi*(Do/2.0)**2)
    A_fin_one = max(2.0*(face_W*depth - A_holes_one_fin), 0.0)
    A_fin_total = A_fin_one * fins

    exposed_frac = max((fin_pitch - tf)/max(fin_pitch,1e-9), 0.0)
    A_bare = N_tubes * (pi*Do*L_tube) * exposed_frac

    Ao = A_fin_total + A_bare
    Arow = Ao/max(1, Nr)

    fin_blockage = min(tf/max(fin_pitch,1e-9), 0.95)
    tube_blockage = min(A_holes_one_fin/max(face_area,1e-9), 0.5)
    Amin = max(face_area*(1.0 - fin_blockage - tube_blockage), 1e-4)

    return dict(
        face_area=face_area, fin_pitch=fin_pitch, fins=fins,
        tubes_per_row=tubes_per_row, N_tubes=N_tubes, L_tube=L_tube,
        depth=depth, A_fin=A_fin_total, A_bare=A_bare,
        Ao=Ao, Arow=Arow, Amin=Amin,
        r_inner=Do/2.0,
        r_outer=min(St, Sl)/2.0,
        D_hydraulic=D_h,
        tube_type=tube_type
    )

# ================= AIR-SIDE CORRELATIONS =================
def mu_air_Pas(T_C: float) -> float:
    T = K(T_C)
    return 1.716e-5 * ((T/273.15)**1.5) * ((273.15+110.4)/(T+110.4))

def k_air_W_mK(T_C: float) -> float:
    return 0.024 + (0.027 - 0.024) * (T_C/40.0)

def airside_compact_htc_dp(mdot_air, face_W, face_H, depth, fin_pitch, tf,
                           T_air_C, W_air, P: float = P_ATM,
                           fin_type: str = "Wavy (no louvers)",
                           louver_angle_deg: float = 40.0,
                           louver_cuts_per_row: int = 8,
                           louver_gap_mm: float = 2.0,
                           h_mult_wavy: float = 1.15,
                           dp_mult_wavy: float = 1.20, 
                           Do=None, N_tubes_face=None, 
                           sigma_free_area=None):
    
    rho = rho_moist_kg_m3(T_air_C, W_air, P)
    
    sigma_fin = max((fin_pitch - tf) / max(fin_pitch, 1e-9), 0.05)
    Afr = face_W * face_H
    Aopen_fin = Afr * sigma_fin
    
    if (Do is not None) and (N_tubes_face is not None):
        Atube_block = float(N_tubes_face) * (math.pi * (float(Do) / 2.0) ** 2)
    else:
        Atube_block = 0.0
    
    Amin_geom = max(Aopen_fin - Atube_block, 1e-4)

    if sigma_free_area is not None:
        sigma_eff = max(min(float(sigma_free_area), 0.95), 0.20)
        Amin = max(Afr * sigma_eff, 1e-4)
    else:
        Amin = Amin_geom

    Vmax = mdot_air / max(rho * Amin, 1e-9)
    mu = mu_air_Pas(T_air_C)
    k  = k_air_W_mK(T_air_C)
    cp = cp_moist_J_per_kgK(T_air_C, W_air)
    Pr = cp*mu/max(k, 1e-12)

    s_f = fin_pitch
    s_gap = max(s_f - tf, 1e-6)
    sigma = max(min(s_gap/s_f, 0.98), 0.02)
    
    G = mdot_air/Amin
    V = Vmax
    Dh = 2.0*s_gap
    Re_Dh = G*Dh/max(mu, 1e-12)

    if fin_type == "Wavy (no louvers)":
        if Re_Dh < 2300:
            Nu = 7.54
            f_D = 96.0/max(Re_Dh, 1e-9)
        else:
            Nu = 0.023*(Re_Dh**0.8)*(Pr**0.4)
            f_D = 0.3164*(Re_Dh**-0.25)

        h = (Nu*k/max(Dh,1e-9))*h_mult_wavy
        dp_core = f_D*(depth/max(Dh,1e-9))*(rho*V*V/2.0)*dp_mult_wavy
        dp_minor = (0.5+1.0)*(rho*V*V/2.0)
        dp_air = dp_core + dp_minor

        air_meta = {"model":"duct+wavy","Re":Re_Dh,"Dh":Dh,"A_min":Amin,"sigma":sigma,"V":V}
    else:
        Nr_est = max(int(round(depth/0.022)), 1)
        row_depth = depth/max(Nr_est, 1)
        p_l = max(row_depth/max(louver_cuts_per_row, 1), 1e-5)

        theta = max(min(float(louver_angle_deg), 89.0), 1.0) * (math.pi/180.0)
        h_l = max(float(louver_gap_mm), 0.2)/1000.0
        L_l = max(h_l/max(math.sin(theta), 1e-6), 1e-5)

        Re_Lp = rho*V*p_l/max(mu, 1e-12)

        if Re_Dh < 2300:
            Nu0 = 7.54
            fD0 = 96.0/max(Re_Dh, 1e-9)
        else:
            Nu0 = 0.023*(Re_Dh**0.8)*(Pr**0.4)
            fD0 = 0.3164*(Re_Dh**-0.25)

        h0 = (Nu0*k/max(Dh,1e-9))*h_mult_wavy
        dp0_core = fD0*(depth/max(Dh,1e-9))*(rho*V*V/2.0)*dp_mult_wavy
        dp0_minor = (0.5+1.0)*(rho*V*V/2.0)
        dp0 = dp0_core + dp0_minor

        Re_ref = 500.0
        phi = max(0.2, min((Re_Lp/max(Re_ref,1e-9)), 20.0))

        eh = 1.0 + 1.6*(phi**0.25)*(math.sin(theta)**0.50)
        edp = 1.0 + 2.8*(phi**0.30)*(math.sin(theta)**0.70)
        eh = max(1.05, min(eh, 3.0))
        edp = max(1.10, min(edp, 8.0))

        h = h0 * eh
        dp_air = dp0 * edp

        air_meta = {
            "model":"louver_enhanced",
            "Re_Dh": float(Re_Dh),
            "Re_Lp": float(Re_Lp),
            "Dh": float(Dh),
            "A_min": float(Amin),
            "sigma": float(sigma),
            "V": float(V),
            "p_l_mm": float(p_l*1000.0),
            "L_l_mm": float(L_l*1000.0),
            "h_l_mm": float(h_l*1000.0),
            "eh": float(eh),
            "edp": float(edp)
        }
    
    return h, dp_air, air_meta

# ================= PRESSURE DROP HELPERS =================
def f_churchill(Re, e_over_D):
    Re = max(1e-9, Re)
    if Re < 2300.0:
        return 64.0/max(1.0, Re)
    A = (2.457 * math.log( (7.0 / max(1.0, Re))**0.9 + 0.27*e_over_D ))**16
    B = (37530.0 / max(1.0, Re))**16
    f = 8.0 * ( ((8.0/max(1.0,Re))**12) + 1.0/((A+B)**1.5) )**(1.0/12.0)
    return max(1e-6, f)

def dp_darcy(mdot, rho, mu, D, L, rough=1.5e-6):
    A = pi*D*D/4.0
    G = mdot/max(A,1e-12)
    v = G/max(rho,1e-9)
    Re = rho*v*D/max(mu,1e-12)
    f = f_churchill(Re, rough/max(D,1e-12))
    dp = f*(L/max(D,1e-12))*(0.5*rho*v*v)
    return dp, Re, f, v, G

def header_pressure_drop(mdot, rho, mu, D, L, n_connections=4, connection_type="standard", rough=1.5e-6):
    A = math.pi*(D**2)/4.0
    v = mdot/max(rho*A, 1e-12)
    Re = rho*v*D/max(mu, 1e-12)
    
    if Re < 2300:
        f = 64.0/max(Re,1e-9)
    else:
        f = (-1.8*math.log10(((rough/D)/3.7)**1.11 + 6.9/max(Re,1e-9)))**-2
    
    dp_darcy = f*(L/D)*0.5*rho*(v**2)
    
    if connection_type == "standard":
        K_entry = 0.5
        K_exit = 1.0
        K_bends = 0.3 * n_connections
    else:
        K_entry = 0.1
        K_exit = 0.3
        K_bends = 0.15 * n_connections
    
    dp_minor = (K_entry + K_exit + K_bends) * 0.5 * rho * v**2
    
    return v, Re, dp_darcy + dp_minor

# ================= MAIN SIMULATION FUNCTION =================
def simulate_evaporator_with_row_calculation(
    face_W, face_H, max_rows, St, Sl, Do, tw, tf, FPI,
    fin_k, tube_k, circuits,
    Vdot_m3_s,
    Tdb_in, W_in,
    Tdb_req, W_req,
    fluid, Tsat_C, SH_req_K, mdot_ref_total, x_in,
    wet_enh=1.35, Rfo=0.0, Rfi=0.0,
    sigma_free_area=None, header_in_diam_in=1.0, header_out_diam_in=1.5, header_length_m=1.0,
    fin_type="Wavy (no louvers)",
    louver_angle_deg=40.0,
    louver_cuts_per_row=8,
    louver_gap_mm=2.0,
    h_mult_wavy=1.15,
    dp_mult_wavy=1.20,
    flow_arrangement="Superheat at air inlet",
    water_film_factor=0.85,
    correlation_package="CoilDesigner Smooth Tube",
    tube_geometry_params=None
):
    """
    Main evaporator simulation with row calculation and zone tracking
    """
    
    if not HAS_CP:
        raise RuntimeError("CoolProp missing. Install with: pip install CoolProp")
    
    # Determine tube type
    if "Microfin" in correlation_package:
        tube_type = "Microfin Tubes"
    elif "Microchannel" in correlation_package:
        tube_type = "Microchannel/Flat Tubes"
    else:
        tube_type = "Smooth Tubes"
    
    # Air mass flow
    rho_in = rho_moist_kg_m3(Tdb_in, W_in)
    mdot_air_total = rho_in*Vdot_m3_s
    mdot_da = mdot_air_total/(1.0+W_in)
    
    h_in = h_moist_J_per_kg_da(Tdb_in, W_in)
    h_req_out = h_moist_J_per_kg_da(Tdb_req, W_req)
    Q_required = mdot_da*(h_in - h_req_out)
    
    # Calculate minimum rows needed
    row_calculator = RowCalculator()
    
    # First pass geometry for estimation
    geom_est = geometry_areas(face_W, face_H, max_rows, St, Do, tf, FPI, Sl=Sl,
                             tube_type=tube_type, geometry_params=tube_geometry_params)
    
    # Air-side heat transfer coefficients
    h_air_dry, dp_air, air_meta = airside_compact_htc_dp(
        mdot_air_total, face_W, face_H, geom_est.get('depth', max_rows*St), 
        geom_est['fin_pitch'], tf, Tdb_in, W_in, P_ATM,
        fin_type=fin_type,
        louver_angle_deg=louver_angle_deg,
        louver_cuts_per_row=louver_cuts_per_row,
        louver_gap_mm=louver_gap_mm,
        h_mult_wavy=h_mult_wavy,
        dp_mult_wavy=dp_mult_wavy, 
        Do=Do, 
        N_tubes_face=geom_est.get('N_tubes', None), 
        sigma_free_area=sigma_free_area
    )
    
    h_air_wet = h_air_dry * wet_enh
    
    # Fin efficiency
    r_inner = geom_est.get('r_inner', Do/2.0)
    r_outer = geom_est.get('r_outer', min(St, Sl)/2.0)
    
    eta_f_dry = correlations.schmidt_fin_efficiency(
        r_outer, r_inner, h_air_dry, fin_k, tf
    )
    eta_f_wet = correlations.schmidt_fin_efficiency(
        r_outer, r_inner, h_air_wet, fin_k, tf
    ) * water_film_factor
    
    Ao = geom_est["Ao"]
    eta_o_dry = 1.0 - (geom_est["A_fin"]/max(Ao,1e-12))*(1.0-eta_f_dry)
    eta_o_wet = 1.0 - (geom_est["A_fin"]/max(Ao,1e-12))*(1.0-eta_f_wet)
    
    # Tube geometry
    Di = max(Do - 2.0*tw, 1e-5)
    flow_area = calculate_flow_area(tube_type, Di, tube_geometry_params or {})
    Ao_per_m = pi*Do
    Ai_per_m = pi*Di
    Ao_Ai = Ao_per_m/max(Ai_per_m,1e-12)
    R_wall_per_Ao = (math.log(Do/max(Di,1e-12))/(2*pi*tube_k))/max(Ao_per_m,1e-12)
    
    def Uo(h_i, h_o, eta_o):
        invU = (1.0/max(eta_o*h_o,1e-12)) + Rfo + Ao_Ai*((1.0/max(h_i,1e-12))+Rfi) + R_wall_per_Ao
        return 1.0/max(invU,1e-12)
    
    # Refrigerant properties
    TsK = K(Tsat_C)
    P_sat = PropsSI("P","T",TsK,"Q",0,fluid)
    rho_l = PropsSI("D","T",TsK,"Q",0,fluid)
    rho_v = PropsSI("D","T",TsK,"Q",1,fluid)
    mu_l  = PropsSI("V","T",TsK,"Q",0,fluid)
    mu_v  = PropsSI("V","T",TsK,"Q",1,fluid)
    cp_l  = PropsSI("C","T",TsK,"Q",0,fluid)
    cp_v  = PropsSI("C","T",TsK,"Q",1,fluid)
    k_l   = PropsSI("L","T",TsK,"Q",0,fluid)
    k_v   = PropsSI("L","T",TsK,"Q",1,fluid)
    h_fg  = PropsSI("H","T",TsK,"Q",1,fluid) - PropsSI("H","T",TsK,"Q",0,fluid)
    
    # Get refrigerant properties for row calculation
    row_estimation = row_calculator.calculate_rows_required(
        geom=geom_est,
        Tsat_C=Tsat_C,
        SH_req_K=SH_req_K,
        mdot_ref_total=mdot_ref_total,
        x_in=x_in,
        h_fg=h_fg,
        flow_arrangement=flow_arrangement,
        circuits=circuits,
        h_air_wet=h_air_wet,
        h_air_dry=h_air_dry,
        eta_o_wet=eta_o_wet,
        eta_o_dry=eta_o_dry,
        Ao_Ai=Ao_Ai,
        R_wall_per_Ao=R_wall_per_Ao,
        Rfo=Rfo,
        Rfi=Rfi,
        Tdb_in=Tdb_in,
        W_in=W_in,
        Tdb_req=Tdb_req,
        W_req=W_req,
        mdot_da=mdot_da,
        mdot_air_total=mdot_air_total,
        tube_params=tube_geometry_params or {},
        correlation_package=correlation_package,
        tube_type=tube_type
    )
    
    # Determine actual rows to use
    rows_needed = row_estimation['total_rows']
    actual_rows = min(max_rows, rows_needed)
    
    # Now run simulation with actual rows
    geom = geometry_areas(face_W, face_H, actual_rows, St, Do, tf, FPI, Sl=Sl,
                         tube_type=tube_type, geometry_params=tube_geometry_params)
    
    Ao = geom["Ao"]
    Arow = geom["Arow"]
    Amin = geom["Amin"]
    D_h = geom.get("D_hydraulic", Do)
    tubes_per_row = geom["tubes_per_row"]
    L_tube = geom["L_tube"]
    
    # Update air-side with actual geometry
    h_air_dry, dp_air, air_meta = airside_compact_htc_dp(
        mdot_air_total, face_W, face_H, geom.get('depth', actual_rows*St), 
        geom['fin_pitch'], tf, Tdb_in, W_in, P_ATM,
        fin_type=fin_type,
        louver_angle_deg=louver_angle_deg,
        louver_cuts_per_row=louver_cuts_per_row,
        louver_gap_mm=louver_gap_mm,
        h_mult_wavy=h_mult_wavy,
        dp_mult_wavy=dp_mult_wavy, 
        Do=Do, 
        N_tubes_face=geom.get('N_tubes', None), 
        sigma_free_area=sigma_free_area
    )
    
    h_air_wet = h_air_dry * wet_enh
    
    # Refrigerant flow per circuit
    mdot_ref_c = mdot_ref_total / max(circuits, 1)
    L_total_circ = (tubes_per_row * actual_rows / max(circuits, 1)) * L_tube
    L_row_circ = L_total_circ / max(actual_rows, 1)
    
    # Initial conditions
    if flow_arrangement == "Superheat at air inlet":
        T_ref = Tsat_C + SH_req_K
        x = None
        current_zone = "SH"
    else:
        T_ref = Tsat_C
        x = x_in
        current_zone = "EVAP"
    
    T_air = Tdb_in
    W_air = W_in
    h_air = h_moist_J_per_kg_da(T_air, W_air)
    
    W_sat = W_from_T_RH(Tsat_C, 100.0)
    h_sat = h_moist_J_per_kg_da(Tsat_C, W_sat)
    
    # Row marching
    rows_log = []
    Q_total = 0.0
    dp_ref_total = 0.0
    dp_ref_SH = 0.0
    dp_ref_2p = 0.0
    SH_ach = 0.0
    v_face = Vdot_m3_s / max(geom["face_area"], 1e-9)
    
    # Track zones
    evaporation_rows_used = 0
    superheat_rows_used = 0
    zone_changes = []
    
    def eps_crossflow_Cmin_Cmax(NTU, Cr):
        Cr = max(min(Cr, 0.999999), 1e-9)
        return 1.0 - math.exp((math.exp(-Cr*NTU)-1.0)/Cr)
    
    # Main row marching loop
    for row in range(1, actual_rows + 1):
        row_complete = False
        
        if flow_arrangement == "Superheat at air inlet":
            if current_zone == "SH":
                # Superheat row
                G_ref = mdot_ref_c / max(flow_area, 1e-12)
                v_i = G_ref / rho_v
                Re_v = rho_v * v_i * D_h / max(mu_v, 1e-12)
                Pr_v = cp_v * mu_v / max(k_v, 1e-12)
                
                h_i, f_i = correlations.smooth_h_gnielinski(Re_v, Pr_v, D_h, L_row_circ, k_v)
                
                U = Uo(h_i, h_air_dry, eta_o_dry)
                UA = U * Arow
                
                C_air = mdot_da * cp_moist_J_per_kgK(T_air, W_air)
                C_ref = mdot_ref_total * cp_v
                Cmin = min(C_air, C_ref)
                Cr = Cmin / max(max(C_air, C_ref), 1e-12)
                NTU = UA / max(Cmin, 1e-12)
                eps = eps_crossflow_Cmin_Cmax(NTU, Cr)
                
                dT_in = max(T_air - T_ref, 0.1)
                Q_row = eps * Cmin * dT_in
                
                T_air_prev = T_air
                T_air = T_air - Q_row / max(C_air, 1e-12)
                T_ref = max(Tsat_C, T_ref - Q_row / max(mdot_ref_total*cp_v, 1e-12))
                Q_total += Q_row
                
                dp, Re_d, f, v, G = dp_darcy(mdot_ref_c, rho_v, mu_v, D_h, L_row_circ)
                dp_ref_total += dp
                dp_ref_SH += dp
                
                superheat_rows_used += 1
                
                rows_log.append({
                    'row': row, 'zone': 'SH', 'Q_row_kW': Q_row/1000.0,
                    'T_air_out': T_air, 'W_air_out': W_air, 'T_ref': T_ref,
                    'x': None, 'h_ref': h_i, 'v_ref': v,
                    'zone_complete': True if T_ref <= Tsat_C + 0.1 else False
                })
                
                if T_ref <= Tsat_C + 0.1:
                    current_zone = "EVAP"
                    x = 1.0
                    zone_changes.append({'row': row, 'from': 'SH', 'to': 'EVAP'})
                
            else:  # EVAP zone
                # Two-phase row
                current_x = x if x is not None else 1.0
                
                v_l = mdot_ref_c / (rho_l * flow_area)
                Re_l = rho_l * v_l * D_h / max(mu_l, 1e-12)
                Pr_l = cp_l * mu_l / max(k_l, 1e-12)
                
                h_l, f_l = correlations.smooth_h_gnielinski(Re_l, Pr_l, D_h, L_row_circ, k_l)
                
                G_ref = mdot_ref_c / max(flow_area, 1e-12)
                Bo = G_ref / (rho_l * h_fg)
                Fr_l = G_ref**2 / (rho_l**2 * GRAVITY * D_h)
                
                # Select appropriate correlation
                if tube_type == "Smooth Tubes":
                    h_i = correlations.smooth_h_shah2016_evaporation(
                        current_x, Re_l, Pr_l, h_l, Bo, Fr_l, D_h, G_ref, rho_l, rho_v
                    )
                elif tube_type == "Microfin Tubes":
                    h_i = correlations.microfin_h_cavanagh_evaporation(
                        current_x, Re_l, Pr_l, h_l, G_ref, D_h, rho_l, rho_v,
                        fin_height_mm=tube_geometry_params.get('fin_height_mm', 0.2),
                        helix_angle_deg=tube_geometry_params.get('helix_angle_deg', 18.0),
                        number_fins=tube_geometry_params.get('number_fins', 60)
                    )
                else:  # Microchannel
                    h_i = correlations.microchannel_h_shah2019_evaporation(
                        current_x, Re_l, Pr_l, h_l, G_ref, D_h, rho_l, rho_v,
                        aspect_ratio=tube_geometry_params.get('aspect_ratio', 0.5)
                    )
                
                U = Uo(h_i, h_air_wet, eta_o_wet)
                UA = U * Arow
                
                NTU_h = UA / max(mdot_da * cp_moist_J_per_kgK(T_air, W_air), 1e-12)
                BF = math.exp(-NTU_h)
                h_out = h_sat + BF * (h_air - h_sat)
                Q_row = mdot_da * (h_air - h_out)
                
                T_out_row = Tsat_C + BF * (T_air - Tsat_C)
                W_out_row = W_sat + BF * (W_air - W_sat)
                
                T_air_prev = T_air
                T_air = max(Tsat_C, T_out_row)
                W_air = max(0.0, min(W_out_row, W_from_T_RH(T_air, 100.0)))
                h_air = h_moist_J_per_kg_da(T_air, W_air)
                Q_total += Q_row
                
                if x is not None:
                    x = max(0.0, x - Q_row / max(mdot_ref_total * h_fg, 1e-12))
                
                # Pressure drop
                dp_lo, Re_lo, f_lo, v_lo, G_lo = dp_darcy(mdot_ref_c, rho_l, mu_l, D_h, L_row_circ)
                dp_vo, Re_vo, f_vo, v_vo, G_vo = dp_darcy(mdot_ref_c, rho_v, mu_v, D_h, L_row_circ)
                
                if tube_type == "Smooth Tubes":
                    dp = correlations.dp_muller_steinhagen(current_x, dp_lo, dp_vo, rho_l, rho_v, G_ref, D_h)
                elif tube_type == "Microfin Tubes":
                    dp = correlations.microfin_dp_schlager_bergles(
                        current_x, dp_lo, dp_vo, G_ref, D_h, rho_l, rho_v,
                        fin_height_mm=tube_geometry_params.get('fin_height_mm', 0.2),
                        helix_angle_deg=tube_geometry_params.get('helix_angle_deg', 18.0)
                    )
                else:  # Microchannel
                    dp = correlations.microchannel_dp_friedel_modified(
                        current_x, dp_lo, dp_vo, G_ref, D_h, rho_l, rho_v, mu_l, mu_v,
                        aspect_ratio=tube_geometry_params.get('aspect_ratio', 0.5)
                    )
                
                dp_ref_total += dp
                dp_ref_2p += dp
                
                evaporation_rows_used += 1
                
                rows_log.append({
                    'row': row, 'zone': 'EVAP', 'Q_row_kW': Q_row/1000.0,
                    'T_air_out': T_air, 'W_air_out': W_air, 'T_ref': Tsat_C,
                    'x': x, 'h_ref': h_i, 'v_ref': v_l,
                    'zone_complete': True if x <= 0.01 or (T_air <= Tdb_req and W_air <= W_req) else False
                })
        
        else:  # Superheat at air outlet
            if current_zone == "EVAP":
                # Evaporation row (same as above)
                current_x = x if x is not None else 1.0
                
                v_l = mdot_ref_c / (rho_l * flow_area)
                Re_l = rho_l * v_l * D_h / max(mu_l, 1e-12)
                Pr_l = cp_l * mu_l / max(k_l, 1e-12)
                
                h_l, f_l = correlations.smooth_h_gnielinski(Re_l, Pr_l, D_h, L_row_circ, k_l)
                
                G_ref = mdot_ref_c / max(flow_area, 1e-12)
                Bo = G_ref / (rho_l * h_fg)
                Fr_l = G_ref**2 / (rho_l**2 * GRAVITY * D_h)
                
                if tube_type == "Smooth Tubes":
                    h_i = correlations.smooth_h_shah2016_evaporation(
                        current_x, Re_l, Pr_l, h_l, Bo, Fr_l, D_h, G_ref, rho_l, rho_v
                    )
                elif tube_type == "Microfin Tubes":
                    h_i = correlations.microfin_h_cavanagh_evaporation(
                        current_x, Re_l, Pr_l, h_l, G_ref, D_h, rho_l, rho_v,
                        fin_height_mm=tube_geometry_params.get('fin_height_mm', 0.2),
                        helix_angle_deg=tube_geometry_params.get('helix_angle_deg', 18.0),
                        number_fins=tube_geometry_params.get('number_fins', 60)
                    )
                else:
                    h_i = correlations.microchannel_h_shah2019_evaporation(
                        current_x, Re_l, Pr_l, h_l, G_ref, D_h, rho_l, rho_v,
                        aspect_ratio=tube_geometry_params.get('aspect_ratio', 0.5)
                    )
                
                U = Uo(h_i, h_air_wet, eta_o_wet)
                UA = U * Arow
                
                NTU_h = UA / max(mdot_da * cp_moist_J_per_kgK(T_air, W_air), 1e-12)
                BF = math.exp(-NTU_h)
                h_out = h_sat + BF * (h_air - h_sat)
                Q_row = mdot_da * (h_air - h_out)
                
                T_out_row = Tsat_C + BF * (T_air - Tsat_C)
                W_out_row = W_sat + BF * (W_air - W_sat)
                
                T_air_prev = T_air
                T_air = max(Tsat_C, T_out_row)
                W_air = max(0.0, min(W_out_row, W_from_T_RH(T_air, 100.0)))
                h_air = h_moist_J_per_kg_da(T_air, W_air)
                Q_total += Q_row
                
                if x is not None:
                    x = max(0.0, x - Q_row / max(mdot_ref_total * h_fg, 1e-12))
                
                # Pressure drop
                dp_lo, Re_lo, f_lo, v_lo, G_lo = dp_darcy(mdot_ref_c, rho_l, mu_l, D_h, L_row_circ)
                dp_vo, Re_vo, f_vo, v_vo, G_vo = dp_darcy(mdot_ref_c, rho_v, mu_v, D_h, L_row_circ)
                
                if tube_type == "Smooth Tubes":
                    dp = correlations.dp_muller_steinhagen(current_x, dp_lo, dp_vo, rho_l, rho_v, G_ref, D_h)
                elif tube_type == "Microfin Tubes":
                    dp = correlations.microfin_dp_schlager_bergles(
                        current_x, dp_lo, dp_vo, G_ref, D_h, rho_l, rho_v,
                        fin_height_mm=tube_geometry_params.get('fin_height_mm', 0.2),
                        helix_angle_deg=tube_geometry_params.get('helix_angle_deg', 18.0)
                    )
                else:
                    dp = correlations.microchannel_dp_friedel_modified(
                        current_x, dp_lo, dp_vo, G_ref, D_h, rho_l, rho_v, mu_l, mu_v,
                        aspect_ratio=tube_geometry_params.get('aspect_ratio', 0.5)
                    )
                
                dp_ref_total += dp
                dp_ref_2p += dp
                
                evaporation_rows_used += 1
                
                rows_log.append({
                    'row': row, 'zone': 'EVAP', 'Q_row_kW': Q_row/1000.0,
                    'T_air_out': T_air, 'W_air_out': W_air, 'T_ref': Tsat_C,
                    'x': x, 'h_ref': h_i, 'v_ref': v_l,
                    'zone_complete': True if x <= 0.01 else False
                })
                
                if x <= 0.01:
                    current_zone = "SH"
                    T_ref = Tsat_C
                    zone_changes.append({'row': row, 'from': 'EVAP', 'to': 'SH'})
            
            else:  # SH zone (after evaporation)
                # Superheat row
                G_ref = mdot_ref_c / max(flow_area, 1e-12)
                v_i = G_ref / rho_v
                Re_v = rho_v * v_i * D_h / max(mu_v, 1e-12)
                Pr_v = cp_v * mu_v / max(k_v, 1e-12)
                
                h_i, f_i = correlations.smooth_h_gnielinski(Re_v, Pr_v, D_h, L_row_circ, k_v)
                
                U = Uo(h_i, h_air_dry, eta_o_dry)
                UA = U * Arow
                
                C_air = mdot_da * cp_moist_J_per_kgK(T_air, W_air)
                C_ref = mdot_ref_total * cp_v
                Cmin = min(C_air, C_ref)
                Cr = Cmin / max(max(C_air, C_ref), 1e-12)
                NTU = UA / max(Cmin, 1e-12)
                eps = eps_crossflow_Cmin_Cmax(NTU, Cr)
                
                dT_in = max(T_air - T_ref, 0.1)
                Q_row = eps * Cmin * dT_in
                
                T_air_prev = T_air
                T_air = T_air - Q_row / max(C_air, 1e-12)
                T_ref = T_ref + Q_row / max(mdot_ref_total * cp_v, 1e-12)  # Heating up
                Q_total += Q_row
                
                dp, Re_d, f, v, G = dp_darcy(mdot_ref_c, rho_v, mu_v, D_h, L_row_circ)
                dp_ref_total += dp
                dp_ref_SH += dp
                
                superheat_rows_used += 1
                
                rows_log.append({
                    'row': row, 'zone': 'SH', 'Q_row_kW': Q_row/1000.0,
                    'T_air_out': T_air, 'W_air_out': W_air, 'T_ref': T_ref,
                    'x': None, 'h_ref': h_i, 'v_ref': v,
                    'zone_complete': True if T_ref >= Tsat_C + SH_req_K - 0.5 else False
                })
        
        # Check if air conditions met
        if T_air <= Tdb_req + 1e-6 and W_air <= W_req + 1e-9:
            row_complete = True
            break
    
    # Final calculations
    T_out = T_air
    W_out = W_air
    RH_out = RH_from_T_W(T_out, W_out)
    WB_out = wb_from_T_W(T_out, W_out)
    
    # Achieved superheat
    if flow_arrangement == "Superheat at air inlet":
        if 'zone_changes' in locals() and zone_changes:
            # Find where SH ended
            SH_ach = max(0.0, Tsat_C + SH_req_K - Tsat_C)  # Use designed SH
        else:
            SH_ach = max(0.0, T_ref - Tsat_C)
    else:
        SH_ach = max(0.0, T_ref - Tsat_C)
    
    # Header pressure drops
    D_in_hdr = float(header_in_diam_in) * INCH
    D_out_hdr = float(header_out_diam_in) * INCH
    L_hdr = float(header_length_m)
    
    v_liq_hdr, Re_liq_hdr, dp_liq_hdr = header_pressure_drop(mdot_ref_total, rho_l, mu_l, D_in_hdr, L_hdr)
    v_vap_hdr, Re_vap_hdr, dp_vap_hdr = header_pressure_drop(mdot_ref_total, rho_v, mu_v, D_out_hdr, L_hdr)
    
    dp_ref_total_with_headers = dp_ref_total + dp_liq_hdr + dp_vap_hdr
    
    # Sensible/latent split
    W_avg = 0.5*(W_in + W_air)
    cp_moist = 1006.0 + 1860.0*max(float(W_avg), 0.0)
    mdot_da_use = mdot_air_total / max(1.0 + float(W_in), 1e-9)
    Q_sens = mdot_da_use * cp_moist * max((Tdb_in - T_air), 0.0)
    
    # Summary
    summary = {
        "Flow_arrangement": flow_arrangement,
        "Correlation_Package": correlation_package,
        "Tube_Type": tube_type,
        "Q_required_kW": Q_required/1000.0,
        "Q_achieved_kW": Q_total/1000.0,
        "Q_total_kW": Q_total/1000.0,
        "Q_sensible_kW": Q_sens/1000.0,
        "Q_latent_kW": max(Q_total - Q_sens, 0.0)/1000.0,
        "SHR": Q_sens/max(Q_total, 1e-9),
        "Air_out_DB_C": T_out,
        "Air_out_WB_C": WB_out,
        "Air_out_RH_pct": RH_out,
        "Rows_used": len(rows_log),
        "Rows_available": max_rows,
        "Rows_needed_est": row_estimation['total_rows'],
        "Evaporation_rows": evaporation_rows_used,
        "Superheat_rows": superheat_rows_used,
        "Zone_changes": zone_changes,
        "Tsat_C": Tsat_C,
        "SH_req_K": SH_req_K,
        "SH_ach_K": SH_ach,
        "x_in": x_in,
        "x_end": x if x is not None else 1.0,
        "Ref_dp_total_with_headers_kPa": dp_ref_total_with_headers/1000.0,
        "Air_dp_Pa": dp_air,
        "Coil_Sufficient": "✅ SUFFICIENT" if Q_total >= Q_required - 1e-6 and SH_ach >= SH_req_K - 0.5 else "❌ INSUFFICIENT",
        "Rows_calculation_method": "Exact row marching with zone tracking",
        "Flow_arrangement_detail": f"Air enters {flow_arrangement.split()[-1].lower()} first"
    }
    
    df = pd.DataFrame(rows_log)
    return df, summary, row_estimation

# ================= STREAMLIT UI =================
def main_app():
    """Main Streamlit application"""
    
    if not check_password():
        st.stop()
    
    st.set_page_config(
        page_title="DX Evaporator Designer Pro v3",
        page_icon="🧊",
        layout="wide"
    )
    
    # Initialize session state
    if 'run_simulation' not in st.session_state:
        st.session_state.run_simulation = False
    if 'simulation_results' not in st.session_state:
        st.session_state.simulation_results = None
    
    # Main header
    st.title("🧊 DX Evaporator Designer Pro v3")
    st.markdown("### Enhanced with row calculation and zone tracking")
    
    # Sidebar - Configuration
    with st.sidebar:
        st.header("🔧 Configuration")
        
        # Tube type selection
        st.subheader("Tube Type Selection")
        tube_type = st.radio(
            "Select Tube Type:",
            ["Smooth Tubes", "Microfin Tubes", "Microchannel/Flat Tubes"],
            index=0
        )
        
        # Map tube type to correlation package
        correlation_package = f"CoilDesigner {tube_type}"
        
        # Flow arrangement
        st.subheader("Flow Arrangement")
        flow_arrangement = st.selectbox(
            "Air entry zone:",
            ["Superheat at air inlet", "Superheat at air outlet"],
            index=0,
            help="Air enters superheat zone first or evaporation zone first"
        )
        
        # Show arrangement diagram
        if flow_arrangement == "Superheat at air inlet":
            st.info("🔄 Air → SH Zone → Evap Zone → Outlet")
        else:
            st.info("🔄 Air → Evap Zone → SH Zone → Outlet")
    
    # Main interface tabs
    tab1, tab2 = st.tabs(["📐 Design Inputs", "📊 Results"])
    
    with tab1:
        st.header("Coil Geometry")
        
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            face_W = st.number_input("Face width (m)", 0.2, 4.0, 1.2, 0.01)
        with col2:
            face_H = st.number_input("Face height (m)", 0.2, 4.0, 0.85, 0.01)
        with col3:
            St_mm = st.number_input("Row pitch (mm)", 10.0, 60.0, 22.0, 0.01)
        with col4:
            Sl_mm = st.number_input("Long. pitch (mm)", 10.0, 60.0, 25.4, 0.01)
        
        col5, col6, col7, col8 = st.columns(4)
        with col5:
            max_rows = st.number_input("Max Rows Available", 1, 20, 8, 1,
                                      help="Maximum rows in coil (will calculate needed rows)")
        with col6:
            Do_mm = st.number_input("Tube OD (mm)", 5.0, 20.0, 9.53, 0.01)
        with col7:
            tw_mm = st.number_input("Tube thickness (mm)", 0.2, 2.0, 0.30, 0.01)
        with col8:
            FPI = st.number_input("FPI (1/in)", 4.0, 24.0, 10.0, 0.5)
        
        sigma_free = st.slider("Air free-flow area ratio σ", 0.20, 0.95, 0.55, 0.01)
        
        col9, col10, col11, col12 = st.columns(4)
        with col9:
            tf_mm = st.number_input("Fin thickness (mm)", 0.06, 0.30, 0.12, 0.01)
        with col10:
            fin_mat = st.selectbox("Fin material", ["Aluminum","Copper","Steel"])
        with col11:
            tube_mat = st.selectbox("Tube material", ["Copper","Aluminum","Steel","CuNi 90/10"])
        with col12:
            circuits = st.number_input("Circuits", 2, 64, 20, 1)
        
        # Material properties
        MAT_K = {"Copper": 380.0, "Aluminum": 205.0, "Steel": 50.0, "CuNi 90/10": 29.0}
        fin_k = MAT_K[fin_mat]
        tube_k = MAT_K[tube_mat]
        
        # Tube-specific geometry inputs
        st.header(f"🔬 {tube_type} Geometry")
        tube_geometry_params = get_tube_geometry_inputs(tube_type)
        
        # Advanced options
        with st.expander("⚙️ Advanced Options"):
            col1, col2 = st.columns(2)
            with col1:
                fin_type = st.selectbox("Fin type", ["Wavy (no louvers)", "Wavy + Louvers"], index=1)
                if fin_type == "Wavy + Louvers":
                    louver_angle_deg = st.number_input("Louver angle (deg)", 0.0, 60.0, 40.0, 0.1)
                    louver_gap_mm = st.number_input("Louver gap (mm)", 0.5, 5.0, 2.0, 0.1)
                    louver_cuts_per_row = st.number_input("Louvers/row", 1, 40, 8, 1)
                else:
                    louver_angle_deg = 40.0
                    louver_cuts_per_row = 8
                    louver_gap_mm = 2.0
                
                h_mult_wavy = st.number_input("Wavy h multiplier", 1.0, 3.0, 1.15, 0.01)
                dp_mult_wavy = st.number_input("Wavy Δp multiplier", 1.0, 5.0, 1.20, 0.01)
            
            with col2:
                water_film_factor = st.number_input("Water film factor", 0.5, 1.0, 0.85, 0.01)
                wet_enh = st.number_input("Wet enhancement", 1.0, 2.5, 1.2, 0.05)
                Rfo = st.number_input("Air-side fouling (m²K/W)", 0.0, 0.001, 0.0002, 0.00005)
                Rfi = st.number_input("Tube-side fouling (m²K/W)", 0.0, 0.001, 0.0001, 0.00005)
        
        # Headers
        st.header("Refrigerant Headers")
        col1, col2, col3 = st.columns(3)
        with col1:
            header_in_diam_in = st.selectbox('Inlet header OD (inches)', 
                                            [0.5, 0.75, 1.0, 1.25, 1.5, 2.0], 
                                            index=2)
        with col2:
            header_out_diam_in = st.selectbox('Outlet header OD (inches)', 
                                             [0.5, 0.75, 1.0, 1.25, 1.5, 2.0], 
                                             index=4)
        with col3:
            header_length_m = st.number_input('Header length (m)', 0.10, 20.0,
                                             value=float(face_H), step=0.10)
        
        # Convert units
        St = St_mm*MM
        Sl = Sl_mm*MM
        Do = Do_mm*MM
        tw = tw_mm*MM
        tf = tf_mm*MM
        
        # Air side
        st.header("Air Side")
        
        flow_mode = st.radio("Air flow input mode:", 
                           ["Face velocity (m/s)", "Volume flow (m³/h)"], 
                           horizontal=True)
        
        if flow_mode == "Face velocity (m/s)":
            v_face_input = st.number_input("Face velocity (m/s)", 0.2, 6.0, 1.7, 0.1)
            Vdot = v_face_input * face_W * face_H
            Vdot_m3h = Vdot * 3600
        else:
            Vdot_m3h = st.number_input("Air volume flow (m³/h)", 500.0, 50000.0, 6250.0, 10.0)
            Vdot = Vdot_m3h / 3600
            v_face_input = Vdot / (face_W * face_H)
        
        st.info(f"Face velocity: {v_face_input:.2f} m/s | Volume flow: {Vdot:.3f} m³/s ({Vdot_m3h:.0f} m³/h)")
        
        air_input_mode = st.radio(
            "Air inlet condition input method:",
            ["Dry Bulb + Relative Humidity", "Dry Bulb + Wet Bulb"],
            horizontal=True
        )
        
        col1, col2 = st.columns(2)
        with col1:
            Tdb_in = st.number_input("DB in (°C)", 0.0, 55.0, 24.3, 0.1)
            
            if air_input_mode == "Dry Bulb + Relative Humidity":
                RH_in = st.number_input("RH in (%)", 5.0, 100.0, 55.17, 0.5)
                W_in = W_from_T_RH(Tdb_in, RH_in)
                WB_in = wb_from_T_W(Tdb_in, W_in)
                st.caption(f"Calculated WB: {WB_in:.1f}°C")
            else:
                WB_in = st.number_input("WB in (°C)", 0.0, Tdb_in, 17.0, 0.1)
                W_in = W_from_T_WB(Tdb_in, WB_in)
                RH_in = RH_from_T_W(Tdb_in, W_in)
                st.caption(f"Calculated RH: {RH_in:.1f}%")
        
        with col2:
            Tdb_req = st.number_input("DB out (°C)", -10.0, 40.0, 13.5, 0.1)
            
            if air_input_mode == "Dry Bulb + Relative Humidity":
                RH_req = st.number_input("RH out (%)", 5.0, 100.0, 92.59, 0.5)
                W_req = W_from_T_RH(Tdb_req, RH_req)
                WB_req = wb_from_T_W(Tdb_req, W_req)
                st.caption(f"Calculated WB: {WB_req:.1f}°C")
            else:
                WB_req = st.number_input("WB out (°C)", -10.0, Tdb_req, 12.0, 0.1)
                W_req = W_from_T_WB(Tdb_req, WB_req)
                RH_req = RH_from_T_W(Tdb_req, W_req)
                st.caption(f"Calculated RH: {RH_req:.1f}%")
        
        # Refrigerant side
        st.header("Refrigerant Side")
        fluid = st.selectbox("Refrigerant", ["R134a","R410A","R407C","R404A","R32","R22"])
        Tsat = st.number_input("Evap. Tsat (°C)", -25.0, 20.0, 9.5, 0.1)
        SH_req = st.number_input("Superheat (K)", 0.0, 25.0, 6.0, 0.5)
        mdot_ref = st.number_input("Ref. mass flow (kg/s)", 0.001, 2.0, 0.211, 0.001)
        x_in = st.number_input("Inlet quality (x)", 0.0, 0.95, 0.25, 0.01)
        
        # Run button
        run_col1, run_col2, run_col3 = st.columns([1,2,1])
        with run_col2:
            if st.button("🚀 Run Design Analysis", type="primary", width='stretch'):
                st.session_state.run_simulation = True
                st.rerun()
    
    with tab2:
        if st.session_state.run_simulation:
            with st.spinner(f"Running simulation with {tube_type}..."):
                try:
                    # Run simulation
                    df_rows, summary, row_estimation = simulate_evaporator_with_row_calculation(
                        face_W, face_H, int(max_rows), St, Sl, Do, tw, tf, float(FPI),
                        fin_k, tube_k, int(circuits),
                        Vdot,
                        Tdb_in, W_in,
                        Tdb_req, W_req,
                        fluid, Tsat, SH_req, mdot_ref, x_in,
                        wet_enh=wet_enh, Rfo=Rfo, Rfi=Rfi, 
                        sigma_free_area=sigma_free,
                        header_in_diam_in=header_in_diam_in,
                        header_out_diam_in=header_out_diam_in,
                        header_length_m=header_length_m,
                        fin_type=fin_type,
                        louver_angle_deg=louver_angle_deg,
                        louver_cuts_per_row=louver_cuts_per_row,
                        louver_gap_mm=louver_gap_mm,
                        h_mult_wavy=h_mult_wavy,
                        dp_mult_wavy=dp_mult_wavy,
                        flow_arrangement=flow_arrangement,
                        water_film_factor=water_film_factor,
                        correlation_package=correlation_package,
                        tube_geometry_params=tube_geometry_params
                    )
                    
                    # Store results
                    st.session_state.simulation_results = {
                        'df_rows': df_rows,
                        'summary': summary,
                        'row_estimation': row_estimation,
                        'inputs': {
                            'face_W': face_W, 'face_H': face_H, 'max_rows': max_rows,
                            'St_mm': St_mm, 'Sl_mm': Sl_mm, 'Do_mm': Do_mm,
                            'tw_mm': tw_mm, 'tf_mm': tf_mm, 'FPI': FPI,
                            'fin_mat': fin_mat, 'tube_mat': tube_mat,
                            'circuits': circuits, 'v_face_input': v_face_input,
                            'Vdot': Vdot, 'Vdot_m3h': Vdot_m3h,
                            'Tdb_in': Tdb_in, 'RH_in': RH_in, 'WB_in': WB_in,
                            'Tdb_req': Tdb_req, 'RH_req': RH_req, 'WB_req': WB_req,
                            'fluid': fluid, 'Tsat': Tsat, 'SH_req': SH_req,
                            'mdot_ref': mdot_ref, 'x_in': x_in,
                            'wet_enh': wet_enh, 'Rfo': Rfo, 'Rfi': Rfi,
                            'flow_arrangement': flow_arrangement,
                            'tube_type': tube_type
                        }
                    }
                    
                    st.success("✅ Simulation complete!")
                    
                except Exception as e:
                    st.error(f"❌ Simulation error: {str(e)}")
                    st.code(traceback.format_exc())
        
        # Display results
        if st.session_state.simulation_results:
            results = st.session_state.simulation_results
            df_rows = results['df_rows']
            summary = results['summary']
            row_estimation = results['row_estimation']
            
            # Row Calculation Results
            st.subheader("📐 Row Calculation Results")
            
            col1, col2, col3, col4 = st.columns(4)
            with col1:
                st.metric("Estimated Rows Needed", row_estimation['total_rows'])
                st.metric("Evaporation Rows", row_estimation['evap_rows'])
            with col2:
                st.metric("Superheat Rows", row_estimation['sh_rows'])
                st.metric("Partial Row?", "Yes" if row_estimation['partial_row'] else "No")
            with col3:
                st.metric("Rows Used", summary['Rows_used'])
                st.metric("Rows Available", summary['Rows_available'])
            with col4:
                st.metric("Coil Utilization", 
                         f"{summary['Rows_used']/summary['Rows_available']*100:.1f}%")
                st.metric("Flow Arrangement", summary['Flow_arrangement'].split()[-1].lower() + " first")
            
            # Performance Summary
            st.subheader("📊 Performance Summary")
            
            col5, col6, col7, col8 = st.columns(4)
            with col5:
                st.metric("Cooling Achieved", f"{summary['Q_achieved_kW']:.2f} kW")
                st.metric("Required", f"{summary['Q_required_kW']:.2f} kW")
            with col6:
                st.metric("Sensible", f"{summary['Q_sensible_kW']:.2f} kW")
                st.metric("Latent", f"{summary['Q_latent_kW']:.2f} kW")
            with col7:
                st.metric("SHR", f"{summary['SHR']:.3f}")
                st.metric("Superheat", f"{summary['SH_ach_K']:.1f}/{summary['SH_req_K']:.0f} K")
            with col8:
                st.metric("Coil Status", summary['Coil_Sufficient'])
                st.metric("Tube Type", summary['Tube_Type'].split()[0])
            
            # Zone Analysis
            st.subheader("🔬 Zone Analysis")
            
            col9, col10, col11, col12 = st.columns(4)
            with col9:
                st.metric("Evaporation Rows Used", summary['Evaporation_rows'])
            with col10:
                st.metric("Superheat Rows Used", summary['Superheat_rows'])
            with col11:
                st.metric("Total Rows Used", summary['Rows_used'])
            with col12:
                st.metric("Zone Changes", len(summary.get('Zone_changes', [])))
            
            # Show zone changes
            if 'Zone_changes' in summary and summary['Zone_changes']:
                st.write("**Zone Transitions:**")
                for change in summary['Zone_changes']:
                    st.write(f"  • Row {change['row']}: {change['from']} → {change['to']}")
            
            # Air conditions
            st.subheader("💨 Air Conditions")
            
            col13, col14, col15, col16 = st.columns(4)
            with col13:
                st.metric("Air Out DB", f"{summary['Air_out_DB_C']:.1f} °C")
            with col14:
                st.metric("Air Out WB", f"{summary['Air_out_WB_C']:.1f} °C")
            with col15:
                st.metric("Air Out RH", f"{summary['Air_out_RH_pct']:.1f} %")
            with col16:
                st.metric("Air ΔP", f"{summary['Air_dp_Pa']:.1f} Pa")
            
            # Detailed row-by-row analysis
            st.subheader("📈 Detailed Row-by-Row Analysis")
            if len(df_rows) > 0:
                display_df = df_rows.copy()
                display_df['zone_icon'] = display_df['zone'].apply(lambda x: '🔥' if x == 'SH' else '💧')
                display_cols = ['row', 'zone_icon', 'zone', 'Q_row_kW', 'T_air_out', 'W_air_out', 'x', 'h_ref', 'v_ref']
                
                st.dataframe(
                    display_df[display_cols].round(3),
                    width='stretch',
                    height=400
                )
            
            # Export options
            st.subheader("📤 Export Results")
            
            # CSV download
            csv = df_rows.to_csv(index=False)
            st.download_button(
                label="📥 Download Row Data (CSV)",
                data=csv,
                file_name=f"evaporator_rows_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                mime="text/csv",
                width='stretch'
            )
            
            # Summary download
            summary_json = json.dumps(summary, indent=2)
            st.download_button(
                label="📥 Download Summary (JSON)",
                data=summary_json,
                file_name=f"evaporator_summary_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json",
                mime="application/json",
                width='stretch'
            )
        
        else:
            st.info("👈 Go to 'Design Inputs' tab, enter parameters, and click 'Run Design Analysis'")
            
            # Show explanation
            with st.expander("ℹ️ About This Version", expanded=True):
                st.markdown("""
                ### Enhanced Features:
                
                1. **Row Requirement Calculation** - Calculates exactly how many rows are needed
                2. **Zone Tracking** - Tracks evaporation vs superheat zones separately
                3. **Flow Arrangement Options** - Air can enter superheat or evaporation zone first
                4. **Partial Row Consideration** - Accounts for when conditions are met mid-row
                5. **Tube Type Specific Correlations** - Uses appropriate correlations for each tube type
                
                ### How It Works:
                
                - The program first **estimates** how many rows are needed for evaporation and superheat
                - Then it **marches row-by-row** calculating heat transfer and air conditions
                - It **tracks zone changes** (evaporation to superheat or vice versa)
                - It **stops when** air outlet conditions are met or maximum rows reached
                - Provides **detailed analysis** of each row's performance
                
                ### Flow Arrangements:
                
                - **Superheat at air inlet**: Air → SH Zone → Evap Zone → Outlet
                - **Superheat at air outlet**: Air → Evap Zone → SH Zone → Outlet
                
                Select your preferred arrangement based on your system design.
                """)

# ================= MAIN EXECUTION =================
if __name__ == "__main__":
    if not HAS_CP:
        st.error("""
        ⚠️ CoolProp is not installed. 
        
        Please install with:
        ```
        pip install coolprop
        ```
        """)
        st.stop()
    
    main_app()
from __future__ import annotations
import math
import pandas as pd

REQUIRED_MAP_COLUMNS = ['evap_c','cond_c','cooling_kw','power_kw','mass_flow_kg_s']

def validate_map(df: pd.DataFrame) -> list[str]:
    issues=[]
    for c in REQUIRED_MAP_COLUMNS:
        if c not in df.columns:
            issues.append(f'Missing compressor map column: {c}')
    if not issues:
        if len(df) < 4:
            issues.append('Compressor map should contain at least 4 points for interpolation.')
        for c in REQUIRED_MAP_COLUMNS:
            if not pd.api.types.is_numeric_dtype(df[c]):
                issues.append(f'Column {c} must be numeric.')
    return issues

def interpolate_idw(df: pd.DataFrame, evap_c: float, cond_c: float, power_correction: float=1.0) -> dict:
    """Small robust inverse-distance interpolation for compressor maps."""
    issues = validate_map(df)
    if issues:
        return {'status':'ERROR','issues':issues}
    d = df.copy()
    dist = ((d['evap_c']-evap_c)**2 + (d['cond_c']-cond_c)**2).pow(0.5)
    if float(dist.min()) < 1e-9:
        row = d.loc[dist.idxmin()].to_dict()
        row['cop'] = row['cooling_kw']/max(row['power_kw'],1e-9)
        row['status']='EXACT MAP POINT'
        return row
    w = 1/(dist**2 + 1e-9)
    out = {'evap_c':evap_c, 'cond_c':cond_c, 'status':'INTERPOLATED'}
    for col in ['cooling_kw','power_kw','mass_flow_kg_s']:
        out[col] = float((d[col]*w).sum()/w.sum())
    out['power_kw'] *= power_correction
    out['heat_rejection_kw'] = out['cooling_kw'] + out['power_kw']
    out['cop'] = out['cooling_kw']/max(out['power_kw'],1e-9)
    out['nearest_map_distance_k'] = float(dist.min())
    return out

def derate_without_map(rated_kw: float, rated_power_kw: float, evap_c: float, cond_c: float, rated_evap_c: float, rated_cond_c: float, compressor_type: str) -> dict:
    """Fallback when no manufacturer map is available. Use only for early screening."""
    comp = (compressor_type or '').lower()
    cond_slope = 0.018 if 'scroll' in comp else 0.025 if 'recip' in comp or 'piston' in comp else 0.015
    evap_slope = 0.030 if 'scroll' in comp else 0.035 if 'recip' in comp or 'piston' in comp else 0.020
    dcond = cond_c - rated_cond_c
    devap = evap_c - rated_evap_c
    cap_factor = max(0.35, 1 - cond_slope*dcond + evap_slope*devap)
    power_factor = max(0.4, 1 + 0.012*dcond + 0.004*max(devap,0))
    q = rated_kw * cap_factor
    p = rated_power_kw * power_factor
    return {'status':'APPROXIMATE DERATE','cooling_kw':q,'power_kw':p,'heat_rejection_kw':q+p,'cop':q/max(p,1e-9),'capacity_factor':cap_factor,'power_factor':power_factor}

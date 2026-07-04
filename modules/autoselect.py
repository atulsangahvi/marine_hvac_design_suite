from .condenser import auto_select_tubes

def select_best_condenser_tube(q_rej_kw, water_type, water_in_c, water_out_c, tube_od_filter, n_tubes, passes, length_m, allowed_materials=None):
    df = auto_select_tubes(q_rej_kw, water_type, water_in_c, water_out_c, n_tubes, passes, length_m, od_filter=tube_od_filter)
    if allowed_materials and not df.empty and "tube" in df.columns:
        pass
    return df

import re
try:
    import fitz
except Exception:
    fitz=None

def parse_pdf_text(uploaded_file):
    if uploaded_file is None or fitz is None: return ""
    data=uploaded_file.read(); uploaded_file.seek(0)
    doc=fitz.open(stream=data, filetype='pdf')
    return "\n".join(page.get_text() for page in doc)

def find_number(patterns, text, default=None):
    for p in patterns:
        m=re.search(p, text, flags=re.I|re.M)
        if m:
            try: return float(m.group(1).replace(',',''))
            except Exception: pass
    return default

def parse_compressor_text(text):
    return {
        'cooling_capacity_kw': find_number([r'Cooling capacity\s*:?\s*([\d,.]+)\s*kW', r'Capacity\s*:?\s*([\d,.]+)\s*kW'], text),
        'power_kw': find_number([r'Power input\s*:?\s*([\d,.]+)\s*kW', r'Input power\s*:?\s*([\d,.]+)\s*kW'], text),
        'mass_flow_kg_h': find_number([r'Mass flow.*?([\d,.]+)\s*kg/h'], text),
        'discharge_temp_c': find_number([r'Discharge.*?temp.*?([\d,.]+)\s*(?:°C|Deg|C)'], text),
        'evap_c': find_number([r'Evaporating.*?([\-\d,.]+)\s*(?:°C|Deg|C)'], text),
        'cond_c': find_number([r'Condensing.*?([\-\d,.]+)\s*(?:°C|Deg|C)'], text),
    }

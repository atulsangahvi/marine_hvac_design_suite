import pandas as pd

def design_status_tables(comp=None, condenser=None, evaporator=None, piping=None):
    rows=[]
    if comp: rows.append(["Compressor", comp.get("status","OK"), comp.get("note","")])
    if condenser: rows.append(["Condenser", condenser.get("status",""), f"Achieved {condenser.get('capacity_kw', condenser.get('q_possible_kw',''))} kW"])
    if evaporator: rows.append(["Evaporator", evaporator.get("status",""), f"Possible {evaporator.get('capacity_possible_kw','')} kW"])
    if piping: rows.append(["Piping", piping.get("status",""), piping.get("note","")])
    return pd.DataFrame(rows, columns=["Module","Status","Reason / note"])

from __future__ import annotations
import io, zipfile
import pandas as pd
from typing import Dict


def make_csv_zip(tables: Dict[str, pd.DataFrame], readme_text: str = "") -> bytes:
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        if readme_text:
            z.writestr("README_MANUFACTURING_PACKAGE.txt", readme_text)
        for name, df in tables.items():
            safe = ''.join(c if c.isalnum() or c in ('_','-') else '_' for c in name).strip('_') or 'table'
            if isinstance(df, pd.DataFrame):
                z.writestr(f"schedules/{safe}.csv", df.to_csv(index=False).encode('utf-8'))
    return out.getvalue()

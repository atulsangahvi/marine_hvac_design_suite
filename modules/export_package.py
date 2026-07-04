from __future__ import annotations
import io, zipfile
import pandas as pd

def make_package(files: dict[str, bytes|str]) -> bytes:
    out=io.BytesIO()
    with zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED) as z:
        for name,data in files.items():
            if isinstance(data,str): data=data.encode('utf-8')
            z.writestr(name,data)
    return out.getvalue()

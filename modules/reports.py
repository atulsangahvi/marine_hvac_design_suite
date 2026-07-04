from io import BytesIO
import pandas as pd

def make_excel_report(tables: dict) -> bytes:
    out=BytesIO()
    with pd.ExcelWriter(out, engine="xlsxwriter") as writer:
        for name, df in tables.items():
            if isinstance(df, pd.DataFrame):
                df.to_excel(writer, sheet_name=name[:31], index=False)
            else:
                pd.DataFrame(df).to_excel(writer, sheet_name=name[:31], index=False)
    return out.getvalue()

def make_pdf_report(title: str, tables: dict) -> bytes:
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib import colors
    out=BytesIO(); doc=SimpleDocTemplate(out, pagesize=landscape(A4))
    styles=getSampleStyleSheet(); story=[Paragraph(title, styles['Title']), Spacer(1,12)]
    for name, df in tables.items():
        story.append(Paragraph(name, styles['Heading2']))
        if isinstance(df, pd.DataFrame) and not df.empty:
            disp=df.head(25).astype(str)
            data=[list(disp.columns)]+disp.values.tolist()
            tbl=Table(data, repeatRows=1)
            tbl.setStyle(TableStyle([('GRID',(0,0),(-1,-1),0.25,colors.grey),('BACKGROUND',(0,0),(-1,0),colors.lightgrey),('FONTSIZE',(0,0),(-1,-1),7)]))
            story.append(tbl)
        else:
            story.append(Paragraph('No data', styles['Normal']))
        story.append(PageBreak())
    doc.build(story); return out.getvalue()

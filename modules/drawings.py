def refrigerant_mermaid(include_hgb=False, include_receiver=True):
    """Mermaid source for refrigerant circuit.

    Uses conservative Mermaid syntax with quoted node labels and pipe-style edge
    labels. This avoids Mermaid parser failures caused by slashes, spaces, or
    punctuation inside labels on some Streamlit/mermaid-js versions.
    """
    lines = [
        "flowchart LR",
        "COMP[\"Compressor\"] --> COND[\"Condenser\"]",
    ]
    if include_receiver:
        lines += [
            "COND --> LR[\"Liquid receiver\"]",
            "LR --> FD[\"Filter drier\"]",
        ]
    else:
        lines += [
            "COND --> LL[\"Liquid line\"]",
            "LL --> FD[\"Filter drier\"]",
        ]
    lines += [
        "FD --> SG[\"Sight glass\"]",
        "SG --> SOL[\"Liquid solenoid\"]",
        "SOL --> EEV[\"EEV or TXV\"]",
        "EEV --> EVAP[\"Evaporator\"]",
        "EVAP --> COMP",
        "COND -.->|Condenser water| WATER[\"Condenser water in/out\"]",
        "EVAP -.->|Chilled water or air| LOAD[\"Load\"]",
    ]
    if include_hgb:
        lines.append("COMP --> HGB[\"Hot gas bypass\"] --> EVAP")
    return "\n".join(lines)


def control_mermaid():
    """Mermaid source for chiller control sequence.

    Uses quote labels and pipe labels for branch text to avoid Mermaid syntax
    errors in Streamlit Cloud.
    """
    return """flowchart TD
START[\"Start command\"] --> FLOW{\"Water or air flow OK?\"}
FLOW -->|No| AL1[\"Alarm: no flow\"]
FLOW -->|Yes| SAFE{\"Safety chain OK?\"}
SAFE -->|No| AL2[\"Safety alarm\"]
SAFE -->|Yes| PUMP[\"Start pump or fan\"]
PUMP --> SOL[\"Open liquid solenoid\"]
SOL --> COMP[\"Start compressor after delay\"]
COMP --> EEV[\"Control EEV superheat\"]
EEV --> MON[\"Monitor HP, LP, discharge temperature and current\"]
MON --> LIM{\"Approaching limit?\"}
LIM -->|Yes| UNLOAD[\"Unload, reduce capacity, alarm\"]
LIM -->|No| RUN[\"Continue running\"]
UNLOAD --> MON
RUN --> MON
"""


def mermaid_html(diagram: str, title: str = "Mermaid diagram") -> str:
    """Return HTML that renders Mermaid in Streamlit components.

    Streamlit does not render Mermaid natively. The diagram is injected into an
    iframe via components.html. The source is HTML-escaped before insertion.
    """
    import html
    safe_diagram = html.escape(diagram or "")
    safe_title = html.escape(title or "Mermaid diagram")
    return f"""
    <div style=\"font-family: Arial, sans-serif; width:100%; min-height:260px;\">
      <pre class=\"mermaid\" style=\"background: transparent;\">{safe_diagram}</pre>
      <script src=\"https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.min.js\"></script>
      <script>
        mermaid.initialize({{ startOnLoad: true, securityLevel: 'loose', theme: 'default' }});
      </script>
      <noscript>{safe_title}: JavaScript is required to render this Mermaid diagram.</noscript>
    </div>
    """

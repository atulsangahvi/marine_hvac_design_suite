# Marine Chiller Design Suite v8

This build continues Milestone 1 (engineering calculation core) and Milestone 2 (engineering databases).

## What is new in v8

### Milestone 1 — Engineering core

Added a shared `modules/correlations.py` engine with:

- Gnielinski single-phase tube-side HTC support functions.
- Darcy/Swamee-Jain friction support.
- Nusselt horizontal-tube condensation base correlation.
- Cooper pool-boiling screening correlation for flooded evaporator work.
- Enhanced low-fin/GEWA area-ratio calculation.
- Bell-Delaware/Kern screening function with visible correction factors:
  - `Jc` baffle-window/crossflow correction
  - `Jl` leakage correction
  - `Jb` bundle-bypass correction
  - `Jr` laminar correction
  - `Js` end-spacing placeholder

### Condenser module improvements

- Condenser shell-side HTC no longer uses only a fixed guessed base value.
- Base shell-side condensation HTC is now estimated with Nusselt horizontal-tube condensation.
- GEWA/low-fin area ratio is calculated and reported.
- Bell/Kern shell-side water correction outputs are added for audit.
- Automatic condenser geometry optimizer added.
- HSTAR/Wieland GEWA-CLF benchmark validation table added.

### Evaporator module improvements

- Water/glycol shell-side calculation now uses the shared Bell-Delaware/Kern screening core.
- Flooded shell-side refrigerant mode now uses Cooper pool-boiling screening instead of a simple square-root placeholder.
- Correlation audit table updated to show v8 status.

### Milestone 2 — Engineering databases

Added:

- `data/materials.py`
  - tube material thermal conductivity
  - density
  - water-service suitability
  - seawater suitability
  - velocity guidance
- Expanded `data/tube_library.py`
  - generic plain tubes
  - Wieland GEWA-C/GEWA-CLF/GEWA-CPL tubes
  - Datang integral low-fin tubes
  - starter enhanced evaporator tube entries
- `data/compressor_library.py`
  - starter database schema for compressor families and future map entries

### Optimizer and validation

Added:

- `modules/design_optimizer.py`
  - grid-search condenser optimizer across tube library, tube count, passes and length
- `modules/validation_benchmarks.py`
  - benchmark comparison framework, starting with the HSTAR/Wieland GEWA-CLF condenser case

## How to run

```bash
pip install -r requirements.txt
streamlit run app.py
```

For Streamlit Cloud, add this secret:

```toml
APP_PASSWORD = "your-password"
```

If no password secret is found, the app runs in local engineering-development mode.

## How to test

```bash
pytest -q
```

## Important engineering note

This v8 package is a meaningful step toward Milestone 1 and 2, but it is not yet a fully validated manufacturing design package. Before manufacturing, benchmark the outputs against supplier software, test data, TEMA/ASME mechanical design, vibration checks and class-society requirements.

## Suggested next v9 work

1. Full Bell-Delaware geometry inputs for shell-side calculations:
   - actual shell-bundle clearance
   - tube-to-baffle clearance
   - baffle-to-shell clearance
   - seal strips
   - inlet/outlet baffle spacing
2. Row-by-row condenser zones:
   - desuperheating
   - condensation
   - subcooling
3. Full air-coil row-by-row refrigerant-side integration from the legacy air-coil app.
4. More validation benchmarks:
   - Bitzer condenser/evaporator selections
   - HSTAR evaporators
   - Wieland flooded/spray evaporator examples
5. True compressor map database import and interpolation.


## v9 update

- Fixed the Drawings tab so Mermaid diagrams render visually inside Streamlit instead of only showing Mermaid source code.
- Added expandable Mermaid source blocks and `.mmd` download buttons for the refrigerant circuit and control flow diagrams.

If the diagram still does not render, check whether your network/browser blocks `cdn.jsdelivr.net`, because the Streamlit component loads Mermaid JS from that CDN. The Mermaid source remains available in the expander and can be pasted into Mermaid Live Editor.

## v10 condenser update

The condenser module now exposes baffle spacing and baffle cut in the Streamlit input panel:

- `Condenser baffle spacing override (mm, 0 = auto)`
- `Condenser baffle cut (%)`

The condenser report now also includes a preliminary shell-side refrigerant/Freon pressure-drop estimate:

- `shell_ref_dp_kpa`
- `shell_ref_dp_status`
- `shell_ref_mdot_kg_s_est`
- `shell_ref_mass_velocity_kg_m2s`
- `shell_ref_velocity_m_s`
- `shell_ref_re`
- `shell_ref_baffle_spaces`

This is still a screening value and must be verified by detailed shell-side two-phase Bell-Delaware/nozzle pressure-drop design before manufacture.

## v11 evaporator module update

The evaporator tab now has expanded inputs and outputs for both shell-and-tube and air-cooled DX coil modes.

### Shell-and-tube evaporator
- User can enter CHW/water/glycol flow directly, or enter 0 to calculate flow from kW and water delta-T.
- User can select tube OD, wall, tube count, passes, length, shell ID, baffle spacing, baffle cut and pitch ratio.
- Output includes water/glycol flow, velocity, pressure drop and status.
- Output includes refrigerant pressure drop, effective evaporation temperature after refrigerant DP, evaporation temperature loss and superheat assessment.
- Output includes heat capacity rate, Cmin/Cmax ratio, limiting side, maximum heat transfer by Cmin and effectiveness.

### Air-cooled DX coil evaporator
- User can enter air by DB+WB or DB+RH.
- User can enter either air flow or face velocity.
- User can enter coil width and height, rows, FPI, tube OD, tube wall, transverse and longitudinal tube pitch and refrigerant circuits.
- Output includes face velocity, air pressure drop, refrigerant pressure drop, estimated refrigerant path length, effective evaporation temperature after DP and expected operating issue if DP is high.

These calculations are still screening calculations. For production coil manufacture, use the standalone detailed air-cooled evaporator engine and validate against manufacturer/test data.

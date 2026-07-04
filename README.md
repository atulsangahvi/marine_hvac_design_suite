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

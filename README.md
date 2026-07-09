# Marine Chiller Design Suite v21

This build continues Milestone 1 (engineering calculation core) and Milestone 2 (engineering databases).

## What is new in v17

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

This v17 package is a meaningful step toward Milestone 1 and 2, but it is not yet a fully validated manufacturing design package. Before manufacturing, benchmark the outputs against supplier software, test data, TEMA/ASME mechanical design, vibration checks and class-society requirements.

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

## v13 update — flooded evaporator, evaporative condenser, and condenser-type selector

This version adds two major modules.

### Flooded shell-and-tube evaporator

Use the **Evaporator** tab and select **Flooded shell-and-tube**.

The module assumes:
- Water/glycol inside tubes.
- Refrigerant boiling on the shell side.
- User-entered refrigerant liquid level as a percentage of shell diameter.
- Cooper pool-boiling as the base shell-side boiling HTC.
- User-visible enhanced boiling multiplier for GEWA-B/Turbo-B or other enhanced flooded evaporator tubes.

Main outputs include:
- Water/glycol flow rate.
- Water velocity and Reynolds number.
- Water-side pressure drop.
- Shell-side boiling HTC.
- Uo.
- LMTD and leaving approach.
- Q possible versus required capacity.
- Estimated refrigerant charge.
- Vapor disengagement space.
- Shell-side refrigerant pressure-drop allowance and equivalent evaporating-temperature loss.
- Oil-return strategy warning.

### Evaporative condenser / closed-circuit condenser

Use tab **14 Evap Condenser**.

This module is based on the cooling-tower and evaporative-fluid-cooler logic you provided. It uses:
- DB/WB psychrometrics.
- Merkel enthalpy driving force.
- Coil outside area.
- Spray-water rate.
- Fan static pressure.
- Makeup water, evaporation loss, drift and blowdown estimates.

Main outputs include:
- Required and possible heat rejection.
- Condensing-to-wet-bulb approach.
- Coil area.
- Air flow and face velocity.
- Spray-water flow.
- Evaporation loss, blowdown and make-up water.
- Fan and spray-pump power.
- Guidance for improving short designs.

### Engineering caution

Both new modules are **preliminary design/screening tools**. Before manufacturing, validate:
- Flooded evaporator tube boiling performance with tube supplier data or test data.
- Refrigerant charge and oil return.
- Evaporative condenser Merkel K and U values against a vendor selection.
- Fan, spray nozzles, drift eliminator, casing and water-treatment design.


## v14 update — engineering accuracy overhaul

This version corrects several correlation-level errors and replaces guessed values
with solved ones. Expect materially different (more accurate) numbers vs v13.

### Corrections (bugs in previous correlations)

1. **Kern shell-side exponent bug.** The shell-side Colburn factor used
   `jh = 0.36 Re^-0.55`, producing `Nu ∝ Re^0.45` instead of the standard Kern
   `Nu = 0.36 Re^0.55 Pr^(1/3)`. This under-predicted shell-side water/glycol HTC
   by roughly 2-2.5x at typical Reynolds numbers. Fixed with a continuous blend
   into a laminar crossflow floor below Re = 2000.
2. **Air-coil velocity basis.** Compact-fin j/f data are defined at the velocity
   through the minimum free-flow area; the code used face velocity, under-stating
   both air-side HTC and pressure drop by (1/σ) and (1/σ²) class factors.
3. **Shah multiplier basis.** The two-phase evaporation multiplier now uses the
   liquid-fraction Reynolds number G(1-x)·d/μ as Shah defines it, instead of
   total flow treated as liquid.
4. **Flooded-charge geometry.** Liquid level as % of shell diameter is now
   converted to wetted cross-section by the circular-segment formula, and only
   submerged tubes displace liquid. Vapor-space mass is included.

### Replaced assumptions with solved physics

5. **Condensation film ΔT is iterated.** Nusselt/Beatty-Katz condensation h scales
   with ΔT_film^(-1/4); the film ΔT is now solved from the resistance split rather
   than guessed as half the total ΔT.
6. **Beatty-Katz low-fin condensation.** Integral low-fin tubes (GEWA-C/CLF/CPL,
   Datang) now use the Beatty-Katz area-weighted model on the envelope-area basis,
   including fin efficiency and Kern N^(-1/6) inundation. The user multiplier now
   calibrates surface-tension enhancement above Beatty-Katz (typically 1.0-1.6 for
   GEWA-CLF class) instead of scaling bare plain-tube Nusselt.
7. **Cooper pool boiling fixed point.** Flooded evaporator boiling h depends on
   heat flux, and flux depends on U. The module now solves q'' = U(q'')·LMTD
   instead of assuming the required duty is transferred, so oversized and
   undersized bundles are no longer mis-rated.
8. **Evaporative condenser two-resistance model.** The spray-film temperature is
   solved by balancing refrigerant→film UA against an NTU-effectiveness Merkel
   air side (ε = 1 - exp(-K·A/ṁ_air)). Predicted duty can no longer exceed the
   air stream's enthalpy absorption capacity, and the fabricated "condensing minus
   3 K" film temperature and 4 K spray-water rise are gone. Merkel K defaults to a
   Parker-Treybal style estimate from air mass velocity (capped 0.02-0.16 kg/s·m²)
   when no vendor-calibrated value is entered (enter 0 in the UI for auto).

### Property and data improvements

9. **Temperature-dependent water/seawater properties** (Kell density, Vogel
   viscosity, quadratic conductivity, quartic cp, Sharqawy-style seawater
   corrections) replace fixed constants throughout the condenser and improved
   the water/glycol baseline in the evaporator modules.
10. **Gnielinski tube-side HTC in the condenser** replaces Dittus-Boelter with a
    hard laminar jump at Re = 3000, handling the transition region properly.
11. **Tube library internal enhancement.** GEWA-C/CLF entries carry
    `id_enhancement = 1.9` for the ribbed bore (typical published range 1.7-2.2x)
    plus fpi/fin-thickness for Beatty-Katz. These are engineering estimates —
    confirm against the supplier datasheet before manufacture.
12. **Tube ΔP** uses Swamee-Jain friction with drawn-tube roughness instead of
    smooth-tube Blasius.

### Benchmark basis fix

The HSTAR/Wieland GEWA-CLF benchmark now runs at the vendor RATING fouling basis
(near-clean) instead of design fouling, and reports the implied LMTD needed for
the published targets so internal inconsistencies in the target set are visible.
Uo agreement improved from about -65% to about -18% with a conservative 1.4x
enhancement over Beatty-Katz; the residual is consistent with GEWA-CLF exceeding
Beatty-Katz by more than the conservative calibration applied.

### Still required before manufacture

All modules remain screening tools. Validate enhanced-tube performance, fouling
plan, refrigerant charge/oil return, vibration, TEMA/ASME mechanical design and
class-society requirements against supplier data and test results.


## v15 update — compressor cycle model, three-zone condenser, piping states

### Compressor: thermodynamic cycle model replaces linear derating

`modules/compressor.py` now has `cycle_operating_point()`: a real single-stage
vapor-compression model. Capacity comes from suction density x volumetric
efficiency x refrigeration effect (CoolProp properties), power from the
isentropic enthalpy rise divided by an eta_is(pressure-ratio) curve typical of
each machine class (scroll / recip / screw). Swept volume is calibrated from the
entered design point. `estimate_operating_point()` (the condenser balance sweep)
and `compressor_map.derate_without_map()` both use it automatically, keeping the
old linear %/K slopes only as a CoolProp-less fallback. Discharge temperature,
eta_is, eta_v and pressure ratio are reported for audit.

### Condenser: three-zone (desuperheat / condense / subcool) analysis

`evaluate_condenser()` now splits the duty into desuperheating, condensing and
subcooling zones from real enthalpies (blend-safe for R407C/R404A), allocates the
counterflow water temperature rise per zone, applies zone HTCs (gas and liquid
single-phase zones are far weaker than film condensation) and reports the area
each zone needs. `q_possible_kw` is the stricter of the zoned and single-zone
results; both are reported, plus a full zone breakdown. New optional inputs:
`discharge_temp_c` (default condensing + 25 K) and `subcool_k` (default 3 K).
Also fixed a latent bug in the LMTD helper that returned huge negative values
when the two ΔTs were passed in descending order.

### Refrigerant piping

- EN 12735-style copper wall-thickness table replaces the guessed ID formula
  (up to ~1.3 mm error on large sizes).
- `line_conditions()` computes density and viscosity at the true line state
  (suction with superheat, discharge gas, subcooled liquid). Previously one
  vapor viscosity (1.2e-5 Pa.s) was applied to every line, understating
  liquid-line friction ~15x. The app auto-fills these (enter 0 for auto).
- Suction/discharge tables now include the equivalent saturation-temperature
  loss of the line pressure drop, so pipe sizing can be judged in kelvin of
  lost SST/SCT rather than only kPa.

All v14 accuracy notes still apply; these remain screening tools requiring
supplier/test validation before manufacture.


## v17 update — merged and corrected Claude v15 improvements

This build keeps the useful v15 engineering additions but fixes integration issues found during testing.

Retained and corrected:
- compressor operating-point cycle model with approximate fallback when CoolProp is unavailable;
- condenser three-zone desuperheat / condense / subcool reporting, with conservative fallback split if CoolProp fails;
- refrigerant piping state-property improvements;
- flooded evaporator and evaporative condenser modules retained;
- condenser type selector retained in the condenser tab.

Validation status: repository tests pass in the build environment. This remains an engineering design/screening suite and still needs supplier/manufacturer validation before production release.


## v21 update — system balance solver, vibration screening and nozzle sizing (on the v18 base)

Applied directly onto the user's v18 build (all v17/v18 corrections retained,
including the no-CoolProp fallback paths in the compressor cycle model and the
condenser three-zone split, the drawing render fix and the flooded-evaporator
warning display). New tab **15 System Balance + Mech** plus three modules:

### System balance-point solver (`modules/system_balance.py`)

The component tabs size each exchanger at ASSUMED evaporating/condensing
temperatures, but the assembled machine settles wherever the compressor,
evaporator and condenser are simultaneously satisfied — that is what the FAT
bench measures. `solve_balance_point()` balances the calibrated compressor
cycle model against effectiveness models of both exchangers
(eps = 1 - exp(-UA/C) on the phase-change side) by nested bisection on Te and
Tc. Outputs balanced Te/Tc, actual capacity vs design, power, COP, discharge
temperature, water leaving temperatures/approaches, and a diagnostic naming the
bottleneck component when the plant cannot reach design. Feed it
UA = Uo x Ao from the condenser/evaporator tabs (pre-filled from the condenser
result), then re-run those tabs at the solved temperatures to confirm, since U
varies with conditions. Works with the v18 no-CoolProp compressor fallback.

### Tube vibration screening (`modules/vibration.py`)

TEMA-style pre-manufacture checks on the mid-span between baffles: first-mode
natural frequency (pinned-pinned; metal + bore fluid + hydrodynamic added
mass), vortex-shedding lock-in ratio, and Connors fluid-elastic-instability
critical velocity with margin. Material E/density covers Cu, CuNi 90/10 and
70/30, Ti, Al-brass, SS316L and carbon steel. Not an HTRI analysis: inlet
nozzle local velocity, end spans and U-bends need separate review.

### Nozzle sizing (`modules/nozzles.py`)

Selects standard DN sizes for hot-gas inlet, liquid outlet and water nozzles
against TEMA RCB-4.6 momentum limits (rho*v^2 <= 2232 single phase, <= 744 for
saturated/condensing vapor without an impingement plate); liquid outlet held
<= 1.0 m/s, water nozzles 1-3 m/s. Flags when an impingement plate is
required. Reinforcement pads, projections and nozzle loads remain ASME/TEMA
mechanical design work.

### App wiring in v21

- Condenser tab passes the ACTUAL discharge temperature from the Compressor tab
  (plus the entered subcooling) into the three-zone model instead of the +25 K
  default.
- Tab 15 pre-fills condenser UA and water flow from the Condenser tab result.
- APP_VERSION bumped to marine-chiller-suite-v21-balance-vibration-nozzles.
- New tests: tests/test_v21_balance_vibration_nozzles.py.

These remain screening tools; validate against supplier software, test data,
TEMA/ASME mechanical design and class-society requirements before manufacture.


## v21 update
- Replaced Mermaid diagrams with SVG drawing engine.
- Retained v19 vibration/nozzle/system-balance improvements after review.
- Added preliminary condenser and evaporator tubesheet thickness screening.
- Added evaporator vibration screening in the mechanical tab.


## v21 update
- CoolProp is now mandatory for refrigerant cycle, line sizing and three-zone condenser thermodynamics. Approximate no-CoolProp refrigerant fallbacks were removed from production calculations.
- Added formatted Oil Management / Oil Return screening module.
- Raw JSON/dictionary oil-return display was replaced with engineering tables and recommendations.
- Three-zone condenser now reports unavailable zone allocation rather than silently using approximate fallback when CoolProp calls fail.

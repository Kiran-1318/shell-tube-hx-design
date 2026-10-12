---
name: shell-tube-hx-design
description: Design, size, optimise and rate single-phase shell-and-tube heat exchangers (TEMA) with the open-source Python `ht` library - Bell-Delaware shell side, Gnielinski tube side, zone-by-zone sizing, exhaustive cost optimisation, flow-induced vibration and mechanical checks - and produce fabrication-oriented TEMA drawings as SVG (general arrangement, tubesheet drilling layout, baffle/BOM details, TEMA datasheet), result plots, CNC hole coordinates and a technical design report. Use this skill whenever someone wants to design, size, select, check or rate a shell-and-tube exchanger, recuperator, gas-gas or gas-air heat exchanger, flue-gas heat recovery unit, air preheater, process cooler/heater, water-water or oil cooler, or asks for TEMA drawings/datasheets, Bell-Delaware calculations, heat-exchanger optimisation or "use the ht library", even if they only hand over a spreadsheet of process data or say "design the heat exchanger for this plant".
---

# Shell-and-tube heat exchanger design

This skill turns a process duty into a complete, reviewable shell-and-tube design: a geometry chosen by searching hundreds of thousands of candidates, every candidate sized with `ht` correlations, the cheapest feasible one developed into drawings, a datasheet and a report. The heavy lifting is done by the bundled package in `scripts/hxdesign/` driven by one CLI, so your job is mostly to **get the basis right, run it, read the results critically, and explain them**.

Scope: single-phase streams (gas or liquid, any mixture `thermo` knows), TEMA E shell, AEL construction (fixed tubesheets, removable channel covers, optional shell bellows), counter-flow orientation. Condensers, reboilers, two-phase flow, U-tubes and floating heads are outside the model; say so if asked and offer the closest single-phase approximation only if it is clearly labelled.

## Workflow

### 1. Establish the design basis

You need, for each stream: name, phase, composition (thermo names, e.g. `"water"`, `"nitrogen"`, `"carbon dioxide"`, or a combustion recipe), inlet temperature, and - across both streams - all but one of {hot flow, hot outlet T, cold flow, cold outlet T}; operating pressure; fouling resistance; allowable pressure drop. Also which stream goes in the tubes, the area safety factor, and a project name/tag.

- If the user gives a spreadsheet, read it with `openpyxl` (`data_only=True` for values, also read the formulas to understand them) and record which cell each input came from. Use only the sheets that matter for the exchanger; ask before pulling in unrelated equipment (e.g. downstream dryers) - in the original project the user explicitly wanted those excluded.
- Fuel/flue gas: use the `from_combustion` block (fuel composition in vol fractions, flow, excess air) rather than hand-computing the flue gas.
- Missing values: pick sensible defaults from `references/design_guidance.md` (fouling, velocities, allowable dP), state each assumption, and keep going rather than stalling. Ask only for things that change the answer materially and cannot be defaulted (e.g. which outlet temperature is the real requirement).
- Fluid allocation, when not given, follows `references/design_guidance.md` (dirty/fouling, corrosive, high-pressure and hot fluids in the tubes; large-volume clean gas on the shell side).

### 2. Write the spec JSON

Schema and every option: `references/spec_schema.md`. A worked example that reproduces a real, reviewed design (flue gas -> air, 110.8 kW) is `examples/flue_gas_air_preheater.json`; a liquid example (hot water on the shell side) is `examples/water_cooler.json`. Copy the closest one and edit it. Put the spec next to the user's project, not inside the skill folder.

### 3. Run

Dependencies (once): `pip install ht fluids thermo CoolProp openpyxl pandas matplotlib numpy scipy`.

```bash
python <skill>/scripts/run_hx_design.py spec.json --out results            # full search + design
python <skill>/scripts/run_hx_design.py spec.json --out results --quick    # small grid, ~1-2 min
python <skill>/scripts/run_hx_design.py spec.json --out results --stage design   # reuse candidates
python <skill>/scripts/run_hx_design.py spec.json --out results --stage design --params '{"baffle":"NTIW","tube":"1in","pitch_ratio":1.33,"angle":45,"Ntp":1,"Ds":0.5334,"cut":0.3,"B_ratio":3.0}'
```

A full grid is ~300k candidates and takes 5-10 minutes on a multi-core PC: run it in the background and do something useful meanwhile (e.g. hand-check the duty). Property tables are cached in `<out>/data/`.

Outputs in `<out>/`: `REPORT.md` (technical report), `drawings/*.svg` (GA, tubesheet, details+BOM, datasheet), `plots/*.svg`, `data/design_results.json|.xlsx`, `data/candidates.csv.gz` (every candidate with its rejection reasons), `data/tube_hole_coordinates.csv`.

### 4. Review before presenting - this is where judgment matters

Read `REPORT.md` section 5 (automatic findings) and check, at minimum:

- **Duty sanity**: Q ~ m*cp*dT by hand. U against typical ranges in `references/design_guidance.md` (gas-gas 10-50, liquid-liquid 300-1500 W/m2K). A spreadsheet's assumed U is often optimistic for gas service; say so with numbers.
- **Flow regime**: tube Re along the whole length (min is at the end where viscosity is highest - the hot end for gases, the cold end for liquids). Below 2,300 is a red flag. Do not reflexively force Re > 10,000: at fixed flow it means fewer/larger tubes per pass and usually lowers h and raises cost (see the case study in `references/design_guidance.md`). Offer it as a variant, not a default.
- **Over-surface consequences**: the safety factor makes the as-built unit over-perform, so outlets overshoot the design values (e.g. flue gas leaving below a dew-point-motivated limit). Recommend bypass control where an outlet limit exists.
- **Metal temperatures**: condensation/acid risk is governed by the coldest tube METAL temperature, not the bulk gas outlet. Use `limits.min_metal_temp_C` when the user has a dew-point concern.
- **Expansion joint**, vibration (Connors <= 0.8, vortex amplitude, acoustic coincidence for gas shells), nozzle rho*v^2, and any `violations` listed for the final design.
- **Look at the drawings.** SVG text can collide. If `resvg_py` or a browser is available, rasterise and eyeball the GA and tubesheet sheets before handing them over.

If no feasible design exists, the CLI prints the most common rejection reasons. Relax the binding limit (or widen the grid) deliberately and tell the user which limit moved and why.

### 5. Variants and comparisons

When the user asks "what if" (fully turbulent tubes, different allocation, other material, tighter dP), run it as a **separate variant into its own output folder** (e.g. `results_turbulent/`) by editing a copy of the spec; never overwrite the base results - users keep the baseline for comparison and for their records. Present a side-by-side table of the decision metrics (Re, h, U, area, dP, weight, cost, metal temperatures) and give a clear recommendation.

### 6. Present

Lead with the selected design in one table (TEMA type, shell, tubes, passes, baffles, area provided/required, U, dP both sides, Re ranges, weight, cost), then the issues the user must act on (control, dew point, expansion joint, indicative mechanical sizes), then the file list. If the user wants a formal document for others, build it from `REPORT.md` - it already follows basis -> models -> method -> results -> discussion -> limitations -> deliverables.

## Things learned the hard way (keep these)

- **Capital cost must see shell size.** An area-only cost correlation (Hall et al.) makes the optimiser pick huge shells holding few tubes. The bundled objective is fixed cost + USD/kg x fabricated weight + USD/tube + PV of pumping power; tune the rates in `costs`, but keep it weight-based.
- **Gas with a small mass flow vs a large one** (e.g. flue gas -> combustion/drying air): few tubes to keep the tube side turbulent, long baffle spacing to keep shell dP low, and **no-tubes-in-window (NTIW)** baffles so every tube is supported at every baffle - otherwise TEMA's unsupported-span limit kills the long spacing. Expect U ~ 20-30 W/m2K.
- **Zone sizing matters** when properties vary strongly (gas cooled from 500 to 150 C changes viscosity by 40%+); the package always sizes over 24 equal-duty zones.
- **Hot gas inlet > 400 C**: stainless front channel, ceramic tube-inlet ferrules + refractory on the hot tubesheet face, seal-welded joints; the drawings add these automatically.
- **Leak direction**: put the cleaner/safer stream at the higher pressure so tube-joint leaks go the harmless way; the GA notes state the direction.
- **Windows**: write files with `encoding="utf-8"` (Python's default there is cp1252 and a `°` or `Δ` will crash a write and can leave a file truncated).

## Reference files

- `references/spec_schema.md` - every spec field, defaults, and how the energy balance is closed. Read when writing a spec.
- `references/methodology.md` - models, equations, constraints, cost objective, outputs; the basis for the "Models"/"Methodology" sections of any report.
- `references/design_guidance.md` - typical U values, fouling factors, velocities, allowable dP, fluid allocation rules, TEMA type choice, and the turbulent-variant case study.

# Spec schema (JSON)

Temperatures in degC, flows in kg/h, pressures in kPa absolute unless the key says otherwise. Anything omitted takes the default shown. Deep keys are merged, so you only write what differs.

```json
{
  "project": {"name": "...", "tag": "E-101", "rev": "0", "date": "YYYY-MM-DD"},
  "tube_side": "hot",                      // which stream flows in the tubes: "hot" | "cold"

  "hot":  { STREAM },
  "cold": { STREAM },

  "limits": {
    "area_safety_factor": 1.25,            // A_provided >= SF x A_required (fouled)
    "L_max_m": 6.096, "L_min_m": 1.5,      // tube length (TEMA standard 20 ft max)
    "LD_min": 3.0, "LD_max": 15.0,         // tube length / shell ID
    "FEI_max": 0.8,                        // Connors V/Vcrit limit
    "T_metal_max_C": 400,                  // carbon-steel tubes; raise only with an alloy
    "min_metal_temp_C": null,              // e.g. water dew point + 10 K for wet flue gas
    "Re_tube_min": 0                       // e.g. 10000 for a "fully turbulent" variant
  },
  "mechanical": {"design_pressure_barg": null, "corrosion_allowance_mm": 3.0, "tema_class": "C"},
  "costs": {"per_kg_usd": 6.0, "per_tube_usd": 25.0, "fixed_usd": 5000.0,
            "electricity_usd_kWh": 0.12, "hours_per_year": 8000, "years": 10, "rate": 0.10,
            "fan_pump_efficiency": 0.70},
  "grid": {
    "baffle": ["SEG", "NTIW"],             // single segmental / no-tubes-in-window
    "tube": ["0.75in", "1in", "1.25in", "1.5in", "2in"],   // 16/14/14/14/12 BWG
    "pitch_ratio": [1.25, 1.33, 1.5],
    "angle": [30, 45, 90],                 // triangular, rotated square, square
    "Ntp": [1, 2, 4],                      // tube passes (F >= 0.8 enforced)
    "Ds_range_m": [0.15, 1.25],            // standard shell IDs inside this range
    "cut": [0.2, 0.25, 0.3, 0.35, 0.45],
    "B_ratio": [0.3, 0.4, 0.6, 0.8, 1.0, 1.5, 2.0, 3.0]    // central baffle spacing / shell ID
  },
  "rating_cases": [ {"label": "...", "hot": {OVERRIDES}, "cold": {OVERRIDES}, "fouled": true} ],
  "load_fractions": [0.75, 0.5],           // both flows scaled together; lowest also rated clean
  "sweep": {"stream": "hot", "var": "T_in", "from": 300, "to": 700, "step": 25}   // or var "flow_factor"
}
```

## STREAM

```json
{
  "name": "Flue gas",
  "phase": "gas",                          // "gas" | "liquid" - properties must exist in that phase over the stream's T range
  "components": {"nitrogen": 0.78, "oxygen": 0.21, "argon": 0.01},
  "basis": "mole",                         // "mole" | "mass"
  "T_in": 500, "T_out": 150,               // T_out may be null (see energy balance)
  "flow_kg_h": 1008,                       // may be null (see energy balance)
  "P_kPa_abs": 101.3,
  "fouling_m2K_W": 0.00176,
  "allowable_dp_kPa": 1.5,                 // default 1.5 gas, 70 liquid
  "tube_velocity_m_s": [8, 25],            // used if this stream is on the tube side; default gas [8,25], liquid [0.8,3]
  "nozzle_velocity_in_m_s": 12, "nozzle_velocity_out_m_s": 12   // or "nozzle_velocity_m_s"
}
```

Component names are anything `thermo` resolves (common name, formula-like name, or CAS): `water`, `nitrogen`, `oxygen`, `argon`, `carbon dioxide`, `carbon monoxide`, `methane`, `ethylene glycol`, `toluene`, ... Petroleum fractions are not in `thermo`; approximate them with a representative alkane and say so.

### Combustion helper (instead of `components` / `flow_kg_h`)

```json
"from_combustion": {"fuel_flow_Nm3_h": 400,
                    "fuel": {"N2": 0.51, "CO": 0.17, "H2": 0.15, "CO2": 0.15, "CH4": 0.02},
                    "excess_air": 0.10, "O2_in_air": 0.21}
```
Supported fuel species: CO, H2, CH4, C2H6, C3H8 (combustible), CO2, N2, H2O (inert). Produces the wet flue-gas mole fractions and mass flow (integer molecular weights, Nm3 at 0 C, 22.414 Nm3/kmol).

## Energy balance

Both inlet temperatures are required. Of {hot flow, hot T_out, cold flow, cold T_out} exactly one must be missing (null); it is solved from mixture enthalpies. A temperature cross at either terminal is rejected.

## Rating-case overrides

`{"T_in": ..., "flow_kg_h": ..., "flow_factor": ...}` per stream. Example: a second burner temperature with the air flow that case would need: `{"label": "Flue gas in at 300 C", "hot": {"T_in": 300}, "cold": {"flow_kg_h": 1829}}`.

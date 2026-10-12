# Design guidance and defaults

## Typical overall U (fouled, W/m2K) - for sanity checks
| Service | U |
| --- | --- |
| Gas (~1 bar) to gas / air | 10-50 |
| Flue gas to air (air preheater) | 15-35 |
| Gas (~1 bar) to water | 20-200 |
| High-pressure gas to water | 150-500 |
| Water to water | 800-1,500 |
| Light oil to water | 350-900 |
| Heavy oil to water | 60-300 |
| Organic solvent to water | 250-750 |

## Fouling resistances (m2K/W, TEMA RGP-T-2.4 guide values)
| Fluid | Rf |
| --- | --- |
| Clean ambient air, compressed air | 0.00035 |
| Natural-gas flue gas | 0.00088-0.00176 |
| Sooty/tarry flue gas (biomass, producer gas, oil) | 0.00176-0.0035 |
| Treated cooling-tower water | 0.00018-0.00035 |
| River / untreated water | 0.00035-0.0007 |
| Boiler feedwater, steam condensate | 0.00009 |
| Light hydrocarbons, solvents | 0.00018-0.00035 |
| Heavy oils | 0.0005-0.0009 |

## Velocities and pressure drop
| | Gas (~1 bar) | Liquid |
| --- | --- | --- |
| Tube velocity | 8-25 m/s (dirty gas >= 8 to keep particles moving) | 1-2.5 m/s water (CS), 0.8-3 general |
| Shell crossflow | 3-15 m/s | 0.3-1.5 m/s |
| Nozzle | 10-20 m/s | 1.5-3 m/s |
| Allowable dP per side | 0.5-2.5 kPa (fan budget) | 35-100 kPa |

## Fluid allocation (tube side gets the first that applies)
1. Fouling / dirty / sooty fluid - straight tubes behind A-type channel covers can be cleaned mechanically.
2. Corrosive fluid - only the tubes and channels need the alloy.
3. Higher-pressure fluid - thin tubes contain pressure cheaply.
4. Hotter fluid at very high temperature - keeps the shell cool and safe (but check expansion).
5. Lower-flow / higher-h-needed stream - tube passes raise velocity.
Large volumetric gas flows that are clean (air) go to the shell: baffle spacing is the cheap knob for shell dP.

## Construction choice
- AEL (fixed tubesheets, removable channel covers): cheapest; shell side cannot be mechanically cleaned -> clean shell fluid only. Add shell bellows when the tube/shell mean metal dT exceeds ~30-50 K (the code checks stresses).
- If the shell fluid fouls or dT is very large, an AES/AET (floating head) or AEU (U-tube) is the next step; these are outside this skill's model - say so.
- TEMA class: C for general/utility service, B for chemical, R for refinery.

## Baffles
- Single segmental, 20-35% cut, spacing 0.2-1.0 Ds: the usual choice for liquids.
- NTIW (no tubes in window): every tube supported by every baffle, so spacing can approach the TEMA maximum unsupported span (1" CS tube: 1.88 m). Best for low-dP gas service and vibration-prone duties.
- Spacing below 0.2 Ds or 51 mm is not allowed by TEMA.

## Case study - is "fully turbulent" worth forcing? (flue gas -> air, 110.8 kW)
Base optimum: 76 x 1" tubes, 1 pass, Re 6,230-9,670, h_t 55.1, U 24.8, A 24.9 m2, dP 668/295 Pa, USD 20,300.
Re_tube_min = 10,000 variant: 58 x 1.5" tubes, 2 passes, Re 10,200-15,800, h_t 51.1, U 23.3, A 30.0 m2, dP 926/376 Pa, USD 23,700.
Why: at fixed flow Re = 4 m_dot / (pi N_per_pass Di mu), so higher Re means fewer, larger tubes per pass; h ~ G^0.8 Di^-0.2, so larger tubes at similar velocity give LOWER h, and the second pass costs counter-flow driving force (F ~ 0.88). Turbulent-forcing helps only for fouling control or correlation certainty (it did raise the coldest metal temperature by 10 K). Present it as an option with numbers, not as a default.

## Cost objective
Rates are deliberately simple and editable (fabricated CS ~USD 6/kg, USD 25 per tube for two expanded+seal-welded joints, USD 5,000 fixed for nozzles/bellows/testing). They rank designs; they are not a quotation. Never use an area-only correlation as the sole capital cost - it ignores shell, tubesheet and cover mass and drives the optimiser to oversized shells.

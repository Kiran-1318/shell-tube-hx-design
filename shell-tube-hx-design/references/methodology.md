# Methodology and models

Use this text (adapted) for the "Models" and "Methodology" sections of reports.

## Contents
1. Properties
2. Tube side
3. Shell side (Bell-Delaware)
4. Overall coefficient and zone sizing
5. Rating
6. Mechanical
7. Flow-induced vibration
8. Optimisation (grid, constraints, objective)
9. Outputs

## 1. Properties
`thermo.Mixture` tabulated every 10 K (gas) or 5 K (liquid) at the stream pressure, cached as JSON; linear interpolation in T. Enthalpy = integral of cp. Gas density = ideal gas at local pressure; liquid density from the table. Water dew point of a gas = saturation T at the H2O partial pressure (CoolProp).

## 2. Tube side
Gnielinski (2,300 < Re < 5e6) with Gnielinski's entry factor:

Nu = (f/8)(Re-1000)Pr / [1 + 12.7 sqrt(f/8)(Pr^(2/3)-1)] x [1 + (Di/L)^(2/3)],  h = Nu k / Di

Below Re 2,300: laminar thermal entry (Baehr-Stephan). Darcy f from `fluids.friction_factor` (Clamond, roughness 45 um). Pressure drop = friction (local density, area-weighted over zones) + per-pass sharp entrance (K 0.57) and exit (K 1.0) + (Ntp-1) return heads + acceleration G^2(1/rho_out - 1/rho_in) + nozzles (1.0 velocity head in, 0.5 out).

## 3. Shell side (Bell-Delaware, Taborek form)
h_s = h_ideal Jc Jl Jb Js Jr, with h_ideal from `ht.Nu_ESDU_73031` at Re = Do m/(Sm mu) and J factors from `ht` (`baffle_correction_Bell`, `baffle_leakage_Bell`, `bundle_bypassing_Bell`, `unequal_baffle_spacing_Bell`, `laminar_correction_Bell`). NTIW baffles: Jc = 1, no window tubes, span = B. Geometry: Sm = B[Lbb + (Dctl/Ltp,eff)(Pt - Do)], window areas from theta_ds and theta_ctl, leakage areas from TEMA clearances (baffle-shell via `ht.shell_clearance`, tube-baffle hole via `ht.D_baffle_holes`), bundle-shell clearance 12 mm + 0.005 Ds (fixed tubesheet), sealing-strip pairs ~ Ntcc/6 when Fsbp > 0.05.

dP_shell = (Nb-1) dP_bi Rb Rl + Nb dP_wi Rl + end zones dP_bi(1 + Ntcw/Ntcc) Rb (at Bin, Bout) + nozzles; dP_bi from `ht.dP_Zukauskas`, dP_wi = (2 + 0.6 Ntcw) G_w^2/(2 rho); Rl = exp[-1.33(1+rs) rlm^p], Rb = exp[-Cbp Fsbp (1-(2 rss)^(1/3))].

## 4. Overall coefficient and zone sizing
1/U = 1/h_s + Rf_s + Do ln(Do/Di)/(2 k_w) + Rf_t Do/Di + Do/(Di h_t)   (outside area, k_w 45 W/mK)

The duty is split into 24 equal-duty zones from the cold end; each zone has its own properties, h, U and log-mean dT:

A_required = sum dQ_i / (U_i dT_lm,i F)

F = 1 for one tube pass (counter-flow); `ht.F_LMTD_Fakheri` for multi-pass (F >= 0.8 required). Tube length = the shortest (50 mm steps) giving A_provided >= SF x A_required(fouled). Baffles: Nb = floor((L_eff - Bin_min - Bout_min)/B) + 1, end spaces sized to clear the shell nozzles (nozzle OD + 100 mm) and absorb the remainder.

Metal temperatures from the resistance network at each zone (inner and outer tube surfaces, fouled and clean); the min and max over all zones and rating cases are reported and constrained.

## 5. Rating
For given inlet flows and temperatures, guess the outlets -> zone model gives U_eff = Q/(A_req LMTD) -> `ht.effectiveness_NTU_method` (counter-flow, or 'S&T' for multi-pass) with UA = U_eff A_provided -> new outlets; damped iteration to 0.01 K. Used for clean/fouled design point, user rating cases, part loads and sweeps.

## 6. Mechanical (preliminary)
Shell/channels: max(ASME VIII-1 UG-27, TEMA CB-3.13 minimum) + CA, rounded to standard plate. Tubesheet: max(TEMA RCB-7.11 minimum, F G/3 sqrt(P/(eta S))) + CA (+ pass groove). Flat covers UG-34 (C = 0.3, min 16 mm). Tie rods TEMA CB-4.71; baffle thickness and holes TEMA via `ht`; tube holes RCB-7.21. Channels in SA-240 304 when the tube fluid at that end exceeds 400 C. Expansion joint required if the fixed-tubesheet tube stress E alpha dT A_s/(A_s+A_t) exceeds half the tube allowable or free growth > 3 mm. Nozzles: smallest ASME B36.10 size meeting the stream's nozzle velocity (reduced to <= 0.8 Ds with a reducer if needed, rho v^2 <= 2232). Weights from component volumes; hydrotest 1.3 x design (stress-ratio corrected). Flanges, UHX tubesheets, bellows and saddles are indicative - the fabricator's code calculation governs.

## 7. Flow-induced vibration (TEMA Section 6 screening)
Spans: NTIW - central B (pinned), ends Bin/Bout (fixed-pinned); segmental - window tubes 2B and Bin+B. fn = C/(2 pi) sqrt(EI/(m l^4)) with added mass 1.5 rho_s. Connors V_crit = 3.3 fn Do sqrt(m delta/(rho Do^2)), delta from TEMA V-8 (gas) or 0.03 (liquid); limit V/V_crit <= FEI_max. Vortex shedding St = 1/(1.73 P/D) staggered, 0.33 in-line; amplitude per TEMA V-11.2 (C_L 0.05) <= 0.02 Do. Gas shells: acoustic modes n c_eff/(2 Ds), n = 1..4, flagged if f_v within +/-20%.

## 8. Optimisation
Exhaustive grid (spec `grid`), parallel over all cores; a mean-velocity pre-filter skips hopeless candidates. Constraints: tube velocity window, dP both sides, L and L/D, TEMA min/max baffle spacing and unsupported span, area margin, metal temperature min/max, Connors ratio, optional tube Re minimum, F >= 0.8. Objective (minimise):

C_total = fixed + c_kg W_fab + c_tube N_t + sum_{k=1..n} P_pump H c_e / (1+i)^k

Selection prefers designs without an acoustic flag. The winner is regenerated with an exact hole-by-hole layout (tie rods replace peripheral tubes inside the band common to all baffles) and re-sized with the exact tube count.

## 9. Outputs
SVG sheets: GA (sectional elevation, end view, nozzle schedule, design data, notes, title block), tubesheet drilling layout (every hole, tie rods, sealing strips, baffle cuts, pass groove, pitch detail, tubes per row), baffles + tube-joint + bellows details + BOM + weights, TEMA datasheet (A3). Plots: temperature profile, local h/U, Re profile, resistance shares, J factors, dP breakdown, off-design, sensitivity, area-vs-power Pareto, cost vs shell, rejection reasons. Data: design_results.json/.xlsx, candidates.csv.gz, tube_hole_coordinates.csv, REPORT.md.

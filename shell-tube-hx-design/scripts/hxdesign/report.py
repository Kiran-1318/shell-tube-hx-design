"""Markdown technical design report generated from a finalised design record."""
from __future__ import annotations

from datetime import date

from .drawings import tema_designation, tag, dwg_prefix, nozzle_list


def _f(v, n=1):
    return f"{v:,.{n}f}"


def _findings(d) -> list[str]:
    """Engineering observations that the reviewer should see (auto-generated)."""
    r, m, D, g = d["result"], d["mech"], d["design"], d["geom"]
    out = []
    if r["Re_t_min"] < 2300:
        out.append(f"Tube-side flow is laminar in part of the tube (min Re {r['Re_t_min']:.0f}); h is low and "
                   "fouling-prone. Consider fewer tubes per pass or more passes.")
    elif r["Re_t_min"] < 10000:
        out.append(f"Tube-side Re is {r['Re_t_min']:.0f}-{r['Re_t_max']:.0f}: transitional/turbulent, covered by "
                   "Gnielinski. Forcing Re > 10,000 needs fewer, larger tubes per pass and usually LOWERS h at fixed "
                   "flow (h ~ G^0.8 D^-0.2); only do it if fouling or correlation certainty demands it.")
    rp = r["R_parts"]
    tot = sum(rp.values())
    big = max(rp, key=rp.get)
    out.append(f"Largest thermal resistance: {big} ({rp[big] / tot * 100:.0f}% of total).")
    rf = d["ratings"]["Design, fouled"]
    rc = d["ratings"]["Design, clean"]
    if r["overdesign"] > 0.1:
        out.append(f"With {r['overdesign'] * 100:.0f}% over-surface the as-built unit over-performs: hot outlet "
                   f"{rf['T_hot_out']:.1f} C fouled / {rc['T_hot_out']:.1f} C clean vs {D.hot.T_out:.1f} C design; "
                   f"cold outlet {rf['T_cold_out']:.1f} / {rc['T_cold_out']:.1f} C vs {D.cold.T_out:.1f} C. "
                   "Provide outlet-temperature control (bypass) if either outlet has a limit.")
    if d.get("T_dew") is not None:
        tmin = min(v["result"]["T_metal_min"] for v in d["ratings"].values())
        out.append(f"Water dew point of the wet gas is {d['T_dew']:.1f} C; the coldest tube metal over all rated "
                   f"cases is {tmin:.1f} C. Acid dew points (S, Cl) are higher and depend on the fuel - risk is set "
                   "by METAL temperature, not bulk gas temperature.")
    ex = m["expansion"]
    out.append(f"Mean tube metal vs shell: dT = {ex['dT']:.0f} K, free growth {ex['delta'] * 1e3:.1f} mm, fixed-tubesheet "
               f"tube stress {ex['sigma_tube'] / 1e6:.0f} MPa -> expansion joint "
               f"{'REQUIRED (bellows on shell)' if m['expansion_joint'] else 'not required'}.")
    v = d["vib"]
    out.append(f"Vibration screening: Connors V/Vcrit {v['FEI_ratio_max']:.2f}, vortex amplitude ratio "
               f"{v['y_vs_ratio_max']:.2f}, acoustic coincidence: {'YES - add detuning baffles' if v['acoustic_risk'] else 'none'}.")
    if d["violations"]:
        out.append("CONSTRAINT VIOLATIONS on the final design: " + ", ".join(d["violations"]))
    return out


def write_report(d, df, path, files: dict):
    D, g, r, m, s, vib = d["design"], d["geom"], d["result"], d["mech"], d["settings"], d["vib"]
    tb, sh = D.tube, D.shell
    pj = D.spec["project"]
    nfeas = int(df.feasible.astype(bool).sum())
    L = []
    a = L.append
    a(f"# {tag(d)} Shell & Tube Heat Exchanger - Technical Design Report\n")
    a(f"*{pj.get('name', '')}* - generated {date.today().isoformat()} by the shell-tube-hx-design skill\n")
    a("## Summary\n")
    a(f"{tag(d)} is a TEMA **{tema_designation(d)}** (Class {D.spec['mechanical'].get('tema_class', 'C')}) exchanger "
      f"transferring **{_f(D.Q / 1e3)} kW** from {D.hot.name} ({_f(D.hot.T_in, 0)} -> {_f(D.hot.T_out, 0)} C) to "
      f"{D.cold.name} ({_f(D.cold.T_in, 0)} -> {_f(D.cold.T_out, 0)} C). It is the lowest-total-cost of "
      f"{nfeas:,} feasible designs out of {len(df):,} candidates searched.\n")
    a("| Item | Value |\n| --- | --- |")
    rows = [("Shell", f"{g.Ds * 1e3:.0f} mm ID x {m['shell']['t'] * 1e3:.0f} mm, SA-516-70" + (", SS321 bellows" if m["expansion_joint"] else "")),
            ("Tubes", f"{g.Nt} x {g.Do * 1e3:.2f} mm OD x {g.tw * 1e3:.3f} mm, {g.L * 1e3:.0f} mm long, {g.Ntp} pass(es)"),
            ("Layout", f"{g.angle} deg, pitch {g.Pt * 1e3:.2f} mm ({g.pitch_ratio} x OD)"),
            ("Baffles", f"{g.Nb} x {'NTIW' if g.baffle == 'NTIW' else 'single segmental'}, {g.cut * 100:.0f}% cut, {g.B * 1e3:.0f} mm spacing"),
            ("Tube side / shell side", f"{tb.name} / {sh.name}"),
            ("Area", f"{r['A_prov']:.2f} m2 provided vs {r['A_req_f']:.2f} m2 required fouled (+{r['overdesign'] * 100:.0f}%)"),
            ("U fouled / clean", f"{r['U_f']:.1f} / {r['U_c']:.1f} W/m2K"),
            ("Pressure drop tube / shell", f"{r['dP_tube']:.0f} / {r['dP_shell']:.0f} Pa (allowed {s.dP_tube_max:.0f} / {s.dP_shell_max:.0f})"),
            ("Reynolds tube / shell", f"{r['Re_t_min']:.0f}-{r['Re_t_max']:.0f} / {r['Re_s_min']:.0f}-{r['Re_s_max']:.0f}"),
            ("Weight", f"{m['W_empty']:.0f} kg empty, {m['W_flooded']:.0f} kg flooded; overall length {m['overall_length'] * 1e3:.0f} mm"),
            ("Total cost (objective)", f"USD {r['TAC']:,.0f} (capital {r['C_cap']:,.0f} + PV pumping {r['C_op']:,.0f})")]
    for k, v in rows:
        a(f"| {k} | {v} |")
    a("\n## 1. Design basis\n")
    a("| Stream | Hot | Cold |\n| --- | --- | --- |")
    for k, fh, fc in [("Name", D.hot.name, D.cold.name), ("Phase", D.hot.phase, D.cold.phase),
                      ("Flow (kg/h)", _f(D.hot.m * 3600), _f(D.cold.m * 3600)),
                      ("T in / out (C)", f"{D.hot.T_in:.1f} / {D.hot.T_out:.1f}", f"{D.cold.T_in:.1f} / {D.cold.T_out:.1f}"),
                      ("Pressure (kPa abs)", _f(D.hot.P / 1e3), _f(D.cold.P / 1e3)),
                      ("Fouling (m2K/W)", f"{D.hot.fouling:.5f}", f"{D.cold.fouling:.5f}"),
                      ("Allowable dP (kPa)", _f(D.hot.dp_allow / 1e3, 2), _f(D.cold.dp_allow / 1e3, 2)),
                      ("Composition (mole frac.)", ", ".join(f"{c} {v:.4f}" for c, v in D.hot.fluid.comp.items()),
                       ", ".join(f"{c} {v:.4f}" for c, v in D.cold.fluid.comp.items()))]:
        a(f"| {k} | {fh} | {fc} |")
    comb = D.hot.meta.get("_combustion") or D.cold.meta.get("_combustion")
    if comb:
        a(f"\nThe flue gas was computed from complete combustion: {comb['flue_Nm3_h']:.0f} Nm3/h, "
          f"{comb['flue_kg_h']:.1f} kg/h, combustion air {comb['air_Nm3_h']:.0f} Nm3/h.")
    a(f"\nDuty from mixture enthalpies: **{D.Q / 1e3:.2f} kW**. Area safety factor {s.SF}. "
      f"Design pressure {s.P_design / 1e5:.1f} barg; corrosion allowance {s.CA * 1e3:.1f} mm.\n")
    a("## 2. Models\n")
    a("All correlations come from the `ht` and `fluids` libraries; properties from `thermo`.\n")
    a("| Quantity | Model |\n| --- | --- |")
    for k, v in [("Properties", "thermo Mixture, tabulated in T; ideal-gas density for gases"),
                 ("Tube-side h", "Gnielinski + (Di/L)^(2/3) entry term; Baehr-Stephan laminar entry below Re 2300"),
                 ("Tube-side dP", "Clamond/Colebrook friction, sharp entrance + exit per pass, return losses, acceleration, nozzles"),
                 ("Shell-side h", "Bell-Delaware: ESDU 73031 ideal bank x Jc Jl Jb Js Jr (ht)"),
                 ("Shell-side dP", "Zukauskas ideal bank, Taborek windows/end zones, Rl and Rb factors, nozzles"),
                 ("Sizing", "24 equal-duty zones, A = sum dQ/(U LMTD F)"),
                 ("Rating", "ht.effectiveness_NTU_method with U_eff from the zone model"),
                 ("Mechanical", "ASME VIII-1 UG-27/UG-34, TEMA minimum thicknesses, tie rods, tube holes"),
                 ("Vibration", "TEMA Sec. 6 screening: Connors (beta 3.3), vortex amplitude, acoustic modes"),
                 ("Objective", "capital (fixed + USD/kg x fabricated weight + USD/tube) + PV of pumping power")]:
        a(f"| {k} | {v} |")
    a("\n## 3. Methodology\n")
    gr = D.spec["grid"]
    a(f"Exhaustive search over baffle type {gr['baffle']}, tubes {gr['tube']}, pitch ratio {gr['pitch_ratio']}, "
      f"layout {gr['angle']} deg, passes {gr['Ntp']}, standard shells {gr['Ds_range_m'][0]}-{gr['Ds_range_m'][1]} m, "
      f"cut {gr['cut']}, spacing/Ds {gr['B_ratio']}. Each candidate's tube length is the shortest (50 mm steps) giving "
      f"{s.SF} x the fouled area; candidates failing any limit are rejected; the cheapest remaining one is finalised "
      "with an exact hole-by-hole layout, rated off-design and given a mechanical design.\n")
    a(f"Limits: tube velocity {s.v_tube[0]}-{s.v_tube[1]} m/s; dP tube <= {s.dP_tube_max:.0f} Pa, shell <= "
      f"{s.dP_shell_max:.0f} Pa; L {s.L_min}-{s.L_max} m and L/D {s.LD_min}-{s.LD_max}; TEMA max unsupported span; "
      f"Connors ratio <= {s.FEI_max}; tube metal <= {s.T_metal_max} C"
      + (f"; min metal >= {s.min_metal_temp} C" if s.min_metal_temp is not None else "")
      + (f"; tube Re >= {s.Re_t_min:.0f}" if s.Re_t_min else "") + ".\n")
    a("## 4. Results\n")
    a("### 4.1 Thermal-hydraulic\n")
    a("| Quantity | Tube side | Shell side |\n| --- | --- | --- |")
    a(f"| Fluid | {tb.name} | {sh.name} |")
    a(f"| Velocity (m/s) | {r['v_t']:.2f} | {r['v_s']:.2f} |")
    a(f"| Re min / mean / max | {r['Re_t_min']:.0f} / {r['Re_t']:.0f} / {r['Re_t_max']:.0f} | {r['Re_s_min']:.0f} / {r['Re_s']:.0f} / {r['Re_s_max']:.0f} |")
    a(f"| h (W/m2K) | {r['h_t']:.1f} | {r['h_s']:.1f} |")
    a(f"| dP (Pa) | {r['dP_tube']:.0f} | {r['dP_shell']:.0f} |")
    a(f"| dP breakdown | {', '.join(f'{k} {v:.0f}' for k, v in r['dP_tube_parts'].items())} | "
      f"{', '.join(f'{k} {v:.0f}' for k, v in r['dP_shell_parts'].items())} |")
    a(f"\nLMTD {r['LMTD']:.1f} K, F {r['F']:.3f}; Bell-Delaware J: "
      + ", ".join(f"{k} {v:.3f}" for k, v in r["J"].items()) + ".\n")
    a("### 4.2 Nozzles\n")
    a("| Mark | Service | NPS | Velocity (m/s) | rho v2 |\n| --- | --- | --- | --- | --- |")
    for n in nozzle_list(d)[:4]:
        a(f"| {n['mark']} | {n['service']} | {n['noz']['NPS']}\" | {n['noz']['v']:.1f} | {n['noz'].get('rho_v2', 0):.0f} |")
    a("\n### 4.3 Mechanical\n")
    a("| Item | Value |\n| --- | --- |")
    for k, v in [("Design T shell / tube front / rear (C)", f"{m['T_design_shell']:.0f} / {m['T_design_tube_front']:.0f} / {m['T_design_tube_rear']:.0f}"),
                 ("Hydrotest shell / tube (barg)", f"{m['P_test_shell_barg']:.2f} / {m['P_test_tube_barg']:.2f}"),
                 ("Tubesheets", f"{g.t_ts * 1e3:.0f} mm (TEMA min {m['tubesheet']['t_tema_min'] * 1e3:.1f} mm + CA)"),
                 ("Channels front / rear", f"{m['front_material']} / {m['rear_material']}"),
                 ("Flanges (indicative)", f"OD {m['flange']['OD'] * 1e3:.0f} mm, {m['flange']['n_bolts']} x {m['flange']['bolt']}"),
                 ("Expansion joint", "required" if m["expansion_joint"] else "not required"),
                 ("Weights", f"{m['W_empty']:.0f} kg empty / {m['W_flooded']:.0f} kg flooded")]:
        a(f"| {k} | {v} |")
    a("\n### 4.4 Vibration\n")
    a("| Span | fn (Hz) | V/Vcrit | vortex y/0.02Do |\n| --- | --- | --- | --- |")
    for sp in vib["spans"]:
        a(f"| {sp['span']} | {sp['fn']:.1f} | {sp['FEI_ratio']:.2f} | {sp['y_vs_ratio']:.2f} |")
    a("\n### 4.5 Off-design rating\n")
    a("| Case | Duty (kW) | Hot out (C) | Cold out (C) | Min / max metal (C) | dP tube / shell (Pa) |\n| --- | --- | --- | --- | --- | --- |")
    for k, v in d["ratings"].items():
        rr = v["result"]
        a(f"| {k} | {v['Q'] / 1e3:.1f} | {v['T_hot_out']:.1f} | {v['T_cold_out']:.1f} | {rr['T_metal_min']:.1f} / "
          f"{rr['T_metal_max']:.1f} | {rr['dP_tube']:.0f} / {rr['dP_shell']:.0f} |")
    a("\n### 4.6 Optimisation statistics\n")
    counts = {}
    for vv in df.loc[~df.feasible.astype(bool), "violations"].fillna(""):
        for it in str(vv).split(";"):
            if it:
                kk = it.replace("geometry:", "")
                counts[kk] = counts.get(kk, 0) + 1
    a("| Rejection reason | Count |\n| --- | --- |")
    for kk, vv in sorted(counts.items(), key=lambda t: -t[1]):
        a(f"| {kk} | {vv:,} |")
    a("\n## 5. Discussion - automatic findings\n")
    for fnd in _findings(d):
        a(f"- {fnd}")
    a("\n## 6. Limitations\n")
    a("- Single-phase only (no condensation/boiling). Gas radiation neglected (conservative for hot gases).")
    a("- Flange, tubesheet (UHX) and saddle sizes are indicative; the fabricator's code calculation governs.")
    a("- Allowable stresses are approximate ASME II-D values; costs are relative, for ranking designs.")
    a("- Vibration checks are TEMA screening level (Weaver Strouhal fit, TEMA damping).")
    a("\n## 7. Deliverables\n")
    a("| File | Content |\n| --- | --- |")
    for k, v in files.items():
        a(f"| `{k}` | {v} |")
    a("\n## References\n")
    a("- C. Bell, ht / fluids / thermo libraries (pypi.org/project/ht).")
    a("- TEMA Standards, 10th ed.; ASME BPVC VIII-1 and II-D.")
    a("- Taborek, Bell-Delaware method, Heat Exchanger Design Handbook; Gnielinski (1976); ESDU 73031; Zukauskas (1972); Connors (1970).")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(L) + "\n")

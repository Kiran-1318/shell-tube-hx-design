"""Design a shell-and-tube heat exchanger end-to-end from a JSON spec.

    python run_hx_design.py SPEC.json --out OUTDIR [--stage all|optimize|design] [--workers N] [--quick]

Stages
  optimize : exhaustive design-space search  -> OUTDIR/data/candidates.csv.gz
  design   : select optimum, finalise, rate, plots, TEMA drawings, datasheet, report
  all      : both (default). `design` reuses an existing candidates file.

--quick shrinks the grid (for a first look or a smoke test). --params JSON forces a geometry
instead of the optimum, e.g. --params '{"baffle":"NTIW","tube":"1in","pitch_ratio":1.33,
"angle":45,"Ntp":1,"Ds":0.5334,"cut":0.3,"B_ratio":3.0}'.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from hxdesign.optimize import Ctx, run_grid, select            # noqa: E402
from hxdesign.final import finalize, PARAM_KEYS                 # noqa: E402
from hxdesign import plots, drawings                            # noqa: E402
from hxdesign.report import write_report                        # noqa: E402

warnings.filterwarnings("ignore")


def _jsonable(o):
    if isinstance(o, dict):
        return {str(k): _jsonable(v) for k, v in o.items() if k not in ("zones", "profile", "fluid")}
    if isinstance(o, (list, tuple)):
        return [_jsonable(v) for v in o]
    if isinstance(o, (np.floating, np.integer, np.bool_)):
        return o.item()
    if isinstance(o, np.ndarray):
        return o.tolist()
    if hasattr(o, "to_dict"):
        return _jsonable(o.to_dict())
    return o


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("spec")
    ap.add_argument("--out", default="hx_results")
    ap.add_argument("--stage", choices=["all", "optimize", "design"], default="all")
    ap.add_argument("--workers", type=int, default=None)
    ap.add_argument("--quick", action="store_true", help="smaller grid for a fast first pass")
    ap.add_argument("--params", default=None, help="JSON geometry to use instead of the optimum")
    a = ap.parse_args(argv)

    out = Path(a.out)
    DATA, PLOTS, DWG = out / "data", out / "plots", out / "drawings"
    for p in (DATA, PLOTS, DWG):
        p.mkdir(parents=True, exist_ok=True)
    spec = json.loads(Path(a.spec).read_text(encoding="utf-8"))
    if a.quick:
        spec.setdefault("grid", {})
        spec["grid"].update({"pitch_ratio": [1.25, 1.33], "angle": [30, 45], "cut": [0.25, 0.3],
                             "B_ratio": [0.5, 1.0, 2.0, 3.0]})
    (DATA / "spec_used.json").write_text(json.dumps(spec, indent=2))
    cand = DATA / "candidates.csv.gz"

    if a.stage in ("all", "optimize"):
        t = time.time()
        df = run_grid(spec, DATA, a.workers)
        df.to_csv(cand, index=False)
        print(f"[optimize] {len(df):,} candidates, {int(df.feasible.sum()):,} feasible, {time.time() - t:.0f} s", flush=True)
    if a.stage == "optimize":
        return

    df = pd.read_csv(cand) if cand.exists() else pd.DataFrame()
    ctx = Ctx(spec, DATA)
    if a.params:
        p = json.loads(a.params)
    else:
        best = select(df) if len(df) else None
        if best is None:
            msg = df.violations.str.split(";").explode().value_counts().head(8).to_string() if len(df) else "no candidates"
            print("[design] NO FEASIBLE DESIGN. Most common rejection reasons:\n" + msg)
            print("Relax the binding limits (allowable dP, velocity window, L_max, grid ranges) and rerun.")
            sys.exit(2)
        p = {k: (best[k].item() if hasattr(best[k], "item") else best[k]) for k in PARAM_KEYS}
    d = finalize(p, ctx)
    pre = drawings.dwg_prefix(d)

    files = {}
    def add(path, desc):
        files[str(path.relative_to(out)).replace("\\", "/")] = desc
    plots.temperature_profile(d, PLOTS / "01_temperature_profile.svg"); add(PLOTS / "01_temperature_profile.svg", "Temperature profile, metal temperatures")
    plots.local_coefficients(d, PLOTS / "02_local_coefficients.svg"); add(PLOTS / "02_local_coefficients.svg", "Local h and U")
    plots.reynolds_profile(d, PLOTS / "03_reynolds_profile.svg"); add(PLOTS / "03_reynolds_profile.svg", "Reynolds numbers along the exchanger")
    plots.resistance_breakdown(d, PLOTS / "04_resistance_breakdown.svg"); add(PLOTS / "04_resistance_breakdown.svg", "Thermal resistance shares")
    plots.bell_delaware(d, PLOTS / "05_bell_delaware_factors.svg"); add(PLOTS / "05_bell_delaware_factors.svg", "Bell-Delaware J factors")
    plots.pressure_drop_breakdown(d, PLOTS / "06_pressure_drop_breakdown.svg"); add(PLOTS / "06_pressure_drop_breakdown.svg", "Pressure-drop breakdown")
    plots.offdesign(d, PLOTS / "07_off_design_rating.svg"); add(PLOTS / "07_off_design_rating.svg", "Off-design ratings")
    if plots.sensitivity(d, PLOTS / "08_sensitivity.svg"):
        add(PLOTS / "08_sensitivity.svg", "Sensitivity sweep")
    if len(df) and df.feasible.any():
        sel = df[df.feasible.astype(bool)].nsmallest(1, "TAC").iloc[0] if a.params else select(df)
        plots.optimization_tradeoff(df, sel, PLOTS / "09_optimization_tradeoff.svg"); add(PLOTS / "09_optimization_tradeoff.svg", "Area vs pumping power, Pareto front")
        plots.tac_vs_shell(df, sel, PLOTS / "10_cost_vs_shell.svg"); add(PLOTS / "10_cost_vs_shell.svg", "Total cost vs shell size")
        plots.constraint_summary(df, PLOTS / "11_rejections.svg"); add(PLOTS / "11_rejections.svg", "Rejection reasons")
    drawings.ga_drawing(d, DWG / f"{pre}-GA-001_general_arrangement.svg"); add(DWG / f"{pre}-GA-001_general_arrangement.svg", "General arrangement (A1)")
    drawings.tubesheet_drawing(d, DWG / f"{pre}-TS-002_tubesheet_layout.svg"); add(DWG / f"{pre}-TS-002_tubesheet_layout.svg", "Tubesheet drilling layout (A1)")
    drawings.details_drawing(d, DWG / f"{pre}-DT-003_details_BOM.svg"); add(DWG / f"{pre}-DT-003_details_BOM.svg", "Baffles, joint/bellows details, BOM, weights (A1)")
    drawings.datasheet(d, DWG / f"{pre}-DS-004_TEMA_datasheet.svg"); add(DWG / f"{pre}-DS-004_TEMA_datasheet.svg", "TEMA specification sheet (A3)")

    pd.DataFrame(d["layout"]["tubes"], columns=["x_m", "y_m"]).assign(
        x_mm=lambda t: t.x_m * 1e3, y_mm=lambda t: t.y_m * 1e3)[["x_mm", "y_mm"]].round(3).to_csv(
        DATA / "tube_hole_coordinates.csv", index_label="hole")
    add(DATA / "tube_hole_coordinates.csv", "Tube-hole centres for CNC drilling (mm)")
    summary = {"params": p, "TEMA": drawings.tema_designation(d), "geometry": d["geom"].to_dict(), "thermal": d["result"],
               "vibration": d["vib"], "violations": d["violations"], "mechanical": d["mech"], "T_dew": d["T_dew"],
               "ratings": {k: {kk: vv for kk, vv in v.items() if kk != "zones"} for k, v in d["ratings"].items()},
               "sweep": d["sweep"], "duty_W": d["design"].Q,
               "streams": {s_.role: {"name": s_.name, "phase": s_.phase, "m_kg_s": s_.m, "T_in": s_.T_in, "T_out": s_.T_out,
                                    "P_Pa": s_.P} for s_ in (d["design"].hot, d["design"].cold)}}
    (DATA / "design_results.json").write_text(json.dumps(_jsonable(summary), indent=2, default=str))
    add(DATA / "design_results.json", "Every computed value of the final design")
    if len(df):
        with pd.ExcelWriter(DATA / "design_results.xlsx") as xw:
            pd.DataFrame([{"case": k, "Q_kW": v["Q"] / 1e3, "T_hot_out": v["T_hot_out"], "T_cold_out": v["T_cold_out"],
                           "T_metal_min": v["result"]["T_metal_min"], "T_metal_max": v["result"]["T_metal_max"],
                           "dP_tube": v["result"]["dP_tube"], "dP_shell": v["result"]["dP_shell"]}
                          for k, v in d["ratings"].items()]).to_excel(xw, sheet_name="Ratings", index=False)
            if d["sweep"]:
                pd.DataFrame(d["sweep"]).to_excel(xw, sheet_name="Sensitivity", index=False)
            df[df.feasible.astype(bool)].sort_values("TAC").head(200).to_excel(xw, sheet_name="Top200", index=False)
        add(DATA / "design_results.xlsx", "Ratings, sensitivity, top-200 candidates")
    write_report(d, df if len(df) else pd.DataFrame({"feasible": [], "violations": []}), out / "REPORT.md", files)

    r, g = d["result"], d["geom"]
    print(f"[design] {drawings.tema_designation(d)}  {g.Nt} x {g.tube} tubes, {g.Ntp} pass, Ds {g.Ds * 1e3:.0f} mm, "
          f"L {g.L:.2f} m, {g.Nb} {g.baffle} baffles @ {g.B * 1e3:.0f} mm")
    print(f"[design] Q {d['design'].Q / 1e3:.1f} kW  A {r['A_prov']:.2f}/{r['A_req_f']:.2f} m2  U {r['U_f']:.1f}  "
          f"dP t/s {r['dP_tube']:.0f}/{r['dP_shell']:.0f} Pa  Re_t {r['Re_t_min']:.0f}-{r['Re_t_max']:.0f}  "
          f"violations {d['violations'] or 'none'}")
    print(f"[design] outputs in {out.resolve()}  (REPORT.md, drawings/, plots/, data/)")


if __name__ == "__main__":
    main()

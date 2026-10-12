"""Design context and exhaustive design-space search (minimum total cost)."""
from __future__ import annotations

import itertools
import math
import os
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool
from pathlib import Path

import pandas as pd
from ht.hx import HEDH_shells

from . import spec as specmod
from .thermal import Settings, make_zones, size_for_case, check_constraints, vibration, Infeasible, K


class Ctx:
    """Everything needed to size a geometry: the closed design, settings and zone sets."""

    def __init__(self, spec_src, cache_dir: Path, n_zones: int = 24):
        self.design = specmod.load(spec_src, Path(cache_dir))
        self.settings = Settings.from_design(self.design, n_zones)
        d = self.design
        self.zsets = {}
        for ntp in sorted(set(d.spec["grid"]["Ntp"]) | {1}):
            try:
                self.zsets[ntp] = make_zones(d, d.hot.m, d.cold.m, d.hot.T_in + K, d.hot.T_out + K,
                                             d.cold.T_in + K, d.cold.T_out + K, n_zones, ntp)
            except Infeasible:
                pass
        self.zones = self.zsets[1]


def grid_points(spec: dict) -> list[dict]:
    gr = spec["grid"]
    lo, hi = gr["Ds_range_m"]
    shells = [d for d in HEDH_shells if lo <= d <= hi]
    small = [0.1541, 0.2027, 0.2545] if lo < 0.30 else []          # 6, 8, 10 in pipe shells
    shells = sorted(set([s for s in small if s >= lo] + shells))
    axes = {"baffle": gr["baffle"], "tube": gr["tube"], "pitch_ratio": gr["pitch_ratio"], "angle": gr["angle"],
            "Ntp": gr["Ntp"], "Ds": shells, "cut": gr["cut"], "B_ratio": gr["B_ratio"]}
    keys = list(axes)
    return [dict(zip(keys, v)) for v in itertools.product(*axes.values())]


_CTX = None


def _init(spec_src, cache_dir):
    global _CTX
    _CTX = Ctx(spec_src, cache_dir)


def evaluate_point(p: dict, ctx: Ctx | None = None) -> dict:
    ctx = ctx or _CTX
    row = dict(p)
    if p["Ntp"] not in ctx.zsets:
        row.update(feasible=False, violations="geometry:temperature cross for this pass count")
        return row
    try:
        g, r = size_for_case(p, ctx)
        vib = vibration(g, ctx.zones, ctx.design)
        bad = check_constraints(g, r, ctx.settings, vib)
        row.update(Nt=g.Nt, L=g.L, Nb=g.Nb, B=g.B, A_prov=r["A_prov"], A_req_f=r["A_req_f"], U_f=r["U_f"],
                   Re_t_min=r["Re_t_min"], Re_s_min=r["Re_s_min"], h_t=r["h_t"], h_s=r["h_s"], v_t=r["v_t"],
                   dP_tube=r["dP_tube"], dP_shell=r["dP_shell"], P_fan=r["P_fan"], W_est=r["W_est"],
                   C_cap=r["C_cap"], C_hall=r["C_hall"], C_op=r["C_op"], TAC=r["TAC"],
                   T_metal_min=r["T_metal_min"], T_metal_max=r["T_metal_max"], FEI=vib["FEI_ratio_max"],
                   acoustic_risk=vib["acoustic_risk"], feasible=not bad, violations=";".join(bad))
    except Infeasible as e:
        row.update(feasible=False, violations=f"geometry:{e}")
    except Exception as e:                         # correlation out of range etc.
        row.update(feasible=False, violations=f"error:{type(e).__name__}")
    return row


def run_grid(spec_src, cache_dir: Path, workers: int | None = None) -> pd.DataFrame:
    ctx = Ctx(spec_src, cache_dir)                 # builds/caches property tables once
    points = grid_points(ctx.design.spec)
    workers = workers or max(1, min(8, (os.cpu_count() or 2) - 1))
    while True:
        if workers == 1:
            rows = [evaluate_point(p, ctx) for p in points]
            break
        try:
            with ProcessPoolExecutor(max_workers=workers, initializer=_init, initargs=(spec_src, cache_dir)) as ex:
                rows = list(ex.map(evaluate_point, points, chunksize=64))
            break
        except BrokenProcessPool:                  # usually memory pressure: retry with fewer workers
            workers = max(1, workers // 2)
            print(f"[optimize] worker pool crashed - retrying with {workers} worker(s)", flush=True)
    return pd.DataFrame(rows)


def select(df: pd.DataFrame) -> pd.Series | None:
    feas = df[df.feasible.astype(bool)]
    if not len(feas):
        return None
    quiet = feas[~feas.acoustic_risk.astype(bool)]
    return (quiet if len(quiet) else feas).nsmallest(1, "TAC").iloc[0]


def pareto_front(df: pd.DataFrame, x: str, y: str) -> pd.DataFrame:
    d = df.sort_values([x, y])
    best, keep = math.inf, []
    for idx, v in zip(d.index, d[y]):
        if v < best:
            keep.append(idx)
            best = v
    return d.loc[keep]

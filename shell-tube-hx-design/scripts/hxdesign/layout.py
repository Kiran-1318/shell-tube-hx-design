"""Exact tube-field layout (tube centres) for the tubesheet drilling drawing.

Shell-side crossflow is vertical (baffle cuts top/bottom), so tube rows are horizontal.
"""
from __future__ import annotations

import math

import numpy as np


def lattice(Pt: float, angle: int):
    """Return (dx, dy, row_offset) for the layout angle (TEMA convention, flow vertical)."""
    if angle == 30:
        return Pt, Pt * math.sin(math.radians(60)), Pt / 2
    if angle == 60:
        return Pt * math.sqrt(3), Pt / 2, Pt * math.sqrt(3) / 2
    if angle == 45:
        return Pt * math.sqrt(2), Pt / math.sqrt(2), Pt * math.sqrt(2) / 2
    return Pt, Pt, 0.0


def tube_layout(Do, Pt, angle, Dotl, Ntp, Ds, cut, n_tie, d_tie, lane=None, band=None):
    """Generate tube centres inside the OTL; tie rods replace peripheral tubes in the
    band common to all baffles. Returns dict with tubes, tie rods and row data."""
    dx, dy, off = lattice(Pt, angle)
    r_max = (Dotl - Do) / 2
    lane = lane if lane is not None else (Do / 2 + 8e-3)      # half-width of pass-partition lane
    best = None
    for x0 in (0.0, dx / 2):
        for y0 in (0.0, dy / 2):
            pts = []
            nrow = int(r_max / dy) + 2
            for j in range(-nrow, nrow + 1):
                y = y0 + j * dy
                xo = x0 + (off if (j % 2) else 0.0)
                ncol = int(r_max / dx) + 2
                for i in range(-ncol, ncol + 1):
                    x = xo + i * dx
                    if x * x + y * y <= r_max ** 2 + 1e-12:
                        if Ntp >= 2 and abs(y) < lane:
                            continue
                        if band is not None and abs(y) > band:     # no-tubes-in-window
                            continue
                        pts.append((x, y))
            if best is None or len(pts) > len(best[0]):
                best = (pts, x0, y0)
    pts = best[0]
    # Tie rods: outermost positions inside the overlap band |y| <= Ds/2 - cut*Ds
    band = Ds / 2 - cut * Ds - Do
    cand = [p for p in pts if abs(p[1]) <= band]
    targets = []
    k = n_tie // 2
    for side in (-1, 1):
        for i in range(k):
            ang_y = band * (-1 + 2 * (i + 0.5) / k) if k > 1 else 0.0
            targets.append((side, ang_y))
    ties = []
    for side, yt in targets:
        pool = [p for p in cand if p not in ties and p[0] * side > 0]
        if not pool:
            continue
        # outermost tube near the requested height
        p = max(pool, key=lambda q: abs(q[0]) - 3 * abs(q[1] - yt))
        ties.append(p)
    tubes = [p for p in pts if p not in ties]
    ys = sorted({round(p[1], 6) for p in tubes})
    rows = [(y, sum(1 for p in tubes if abs(p[1] - y) < 1e-6)) for y in ys]
    return {"tubes": tubes, "tie_rods": ties, "rows": rows, "Nt": len(tubes),
            "dx": dx, "dy": dy, "r_max": r_max, "lane": lane if Ntp >= 2 else 0.0}

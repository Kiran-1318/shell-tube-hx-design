"""Single-phase property tables built with `thermo` and interpolated in temperature.

A thermo Mixture costs ~0.3 s to build, so each fluid is tabulated once (every 5-10 K)
and cached as JSON. Gas density = ideal gas at local pressure; liquid density = table.
"""
from __future__ import annotations

import hashlib
import json
import warnings
from pathlib import Path

import numpy as np

R_U = 8.314462618


class Fluid:
    def __init__(self, name, phase, T, cp, mu, k, rho, MW, comp, basis, P):
        self.name, self.phase, self.MW, self.comp, self.basis, self.P_ref = name, phase, MW, comp, basis, P
        self.T = np.asarray(T, float)
        self._cp, self._mu, self._k, self._rho = (np.asarray(a, float) for a in (cp, mu, k, rho))
        self._h = np.concatenate(([0.0], np.cumsum(0.5 * (self._cp[1:] + self._cp[:-1]) * np.diff(self.T))))

    def cp(self, T): return np.interp(T, self.T, self._cp)
    def mu(self, T): return np.interp(T, self.T, self._mu)
    def k(self, T): return np.interp(T, self.T, self._k)
    def h(self, T): return np.interp(T, self.T, self._h)
    def T_from_h(self, h): return np.interp(h, self._h, self.T)
    def Pr(self, T): return self.cp(T) * self.mu(T) / self.k(T)

    def rho(self, T, P=None):
        if self.phase == "gas":
            return (P or self.P_ref) * self.MW * 1e-3 / (R_U * np.asarray(T))
        return np.interp(T, self.T, self._rho)

    def cp_mean(self, T1, T2):
        return (self.h(T1) - self.h(T2)) / (T1 - T2) if abs(T1 - T2) > 1e-6 else float(self.cp(T1))

    def sound_speed(self, T):
        if self.phase != "gas":
            return 1400.0
        cpm = self.cp(T) * self.MW * 1e-3
        return float(np.sqrt(cpm / (cpm - R_U) * R_U * T / (self.MW * 1e-3)))

    def mole_fraction(self, thermo_name: str) -> float:
        if self.basis == "mole":
            return float(self.comp.get(thermo_name, 0.0))
        return 0.0

    def water_dew_point_C(self, P=None):
        """Water dew point of a gas mixture (degC) or None if no water vapour."""
        y = self.mole_fraction("water")
        if self.phase != "gas" or y <= 0:
            return None
        import CoolProp.CoolProp as CP
        return CP.PropsSI("T", "P", y * (P or self.P_ref), "Q", 1, "Water") - 273.15


def _tabulate(comp, basis, P, Tmin, Tmax, phase, dT):
    from thermo import Mixture
    ids, fr = list(comp), list(comp.values())
    s = sum(fr)
    fr = [v / s for v in fr]
    rows = []
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        for Ti in np.arange(Tmin, Tmax + 0.01, dT):
            try:
                m = Mixture(ids, zs=fr, T=float(Ti), P=P) if basis == "mole" else Mixture(ids, ws=fr, T=float(Ti), P=P)
                if (phase == "gas" and m.phase != "g") or (phase == "liquid" and m.phase != "l"):
                    continue
                rows.append((float(Ti), m.Cp, m.mu, m.k, m.rho, m.MW, m.zs))
            except Exception:
                continue
    if len(rows) < 4:
        raise ValueError(f"thermo could not give {phase} properties for {comp} between {Tmin:.0f} and {Tmax:.0f} K "
                         "- check component names, phase and pressure.")
    return rows


def build_fluid(name, comp, basis, phase, P, T_lo_C, T_hi_C, cache_dir: Path, need=None) -> Fluid:
    """comp: {thermo/CAS name: fraction}; basis 'mole' or 'mass'; phase 'gas' or 'liquid'."""
    Tmin, Tmax = T_lo_C + 273.15, T_hi_C + 273.15
    dT = 10.0 if phase == "gas" else 5.0
    key = hashlib.md5(json.dumps([sorted(comp.items()), basis, phase, round(P), Tmin, Tmax]).encode()).hexdigest()[:10]
    cache = Path(cache_dir) / f"props_{key}.json"
    if cache.exists():
        d = json.loads(cache.read_text())
    else:
        rows = _tabulate(comp, basis, P, Tmin, Tmax, phase, dT)
        zs = rows[0][6]
        d = {"name": name, "comp": comp, "basis": basis, "phase": phase, "P": P,
             "T": [r[0] for r in rows], "cp": [r[1] for r in rows], "mu": [r[2] for r in rows],
             "k": [r[3] for r in rows], "rho": [r[4] for r in rows], "MW": rows[0][5],
             "zs": dict(zip(comp, zs))}
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(d))
    cover = (d["T"][0] - 273.15, d["T"][-1] - 273.15)
    lo, hi = need if need else (T_lo_C + 15, T_hi_C - 40)
    if cover[0] > lo + 0.5 or cover[1] < hi - 0.5:
        raise ValueError(f"{name}: {phase}-phase properties exist only for {cover[0]:.0f}-{cover[1]:.0f} C but the "
                         f"stream runs {lo:.0f}-{hi:.0f} C (phase change? wrong pressure or phase?)")
    comp_mole = d.get("zs", comp)
    return Fluid(d["name"], d["phase"], d["T"], d["cp"], d["mu"], d["k"], d["rho"], d["MW"], comp_mole, "mole", d["P"])

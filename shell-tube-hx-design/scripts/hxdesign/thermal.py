"""Thermal-hydraulic model of a TEMA E-shell exchanger (single-phase, counter-flow basis).

* Tube side  : Gnielinski (ht.conv_internal) + entry correction; laminar entry below Re 2300;
               Darcy friction (fluids.friction_factor); entrance/exit losses (fluids).
* Shell side : Bell-Delaware. Ideal bank Nu = ht.Nu_ESDU_73031, ideal bank dP = ht.dP_Zukauskas,
               J factors from ht (baffle_correction_Bell, baffle_leakage_Bell, bundle_bypassing_Bell,
               unequal_baffle_spacing_Bell, laminar_correction_Bell); Rl, Rb per Taborek.
* Sizing     : zone (incremental) method, A = sum dQ / (U_i * LMTD_i * F).
* Rating     : ht.effectiveness_NTU_method with an effective U from the zone model.
Either stream may be on either side; the hot stream is not assumed to be in the tubes.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field, asdict
from functools import lru_cache

import numpy as np
import fluids
from ht import (Ntubes, Nu_ESDU_73031, dP_Zukauskas, baffle_correction_Bell, baffle_leakage_Bell,
                bundle_bypassing_Bell, unequal_baffle_spacing_Bell, laminar_correction_Bell,
                F_LMTD_Fakheri, effectiveness_NTU_method)
from ht.hx import get_tube_TEMA
from ht.conv_internal import turbulent_Gnielinski, laminar_entry_Baehr_Stephan

from . import mechanical as mech
from .layout import tube_layout

INCH = 0.0254
K = 273.15
TUBES = {"0.75in": (0.75, 16), "1in": (1.0, 14), "1.25in": (1.25, 14), "1.5in": (1.5, 14), "2in": (2.0, 12)}
BWG_MM = {12: 2.769, 14: 2.108, 16: 1.651}


def tube_dims(name: str):
    nps, bwg = TUBES[name]
    try:
        _, _, Do, Di, t = get_tube_TEMA(NPS=nps, BWG=bwg)
    except ValueError:                       # e.g. 1.5" is not in ht's TEMA table -> BWG wall
        Do, t = nps * INCH, BWG_MM[bwg] / 1e3
        Di = Do - 2 * t
    return Do, Di, t


class Infeasible(Exception):
    pass


@dataclass
class Settings:
    SF: float
    L_max: float
    L_min: float
    LD_min: float
    LD_max: float
    FEI_max: float
    T_metal_max: float
    min_metal_temp: float | None
    Re_t_min: float
    v_tube: tuple
    dP_tube_max: float
    dP_shell_max: float
    Rf_tube: float
    Rf_shell: float
    P_design: float              # Pa(g)
    CA: float
    roughness: float = 4.5e-5
    eta: float = 0.70
    elec: float = 0.12
    hours: float = 8000.0
    years: int = 10
    rate: float = 0.10
    cost_per_kg: float = 6.0
    cost_per_tube: float = 25.0
    cost_fixed: float = 5000.0
    n_zones: int = 24

    @classmethod
    def from_design(cls, d, n_zones=24):
        lim, cst, mec = d.spec["limits"], d.spec["costs"], d.spec["mechanical"]
        return cls(SF=lim["area_safety_factor"], L_max=lim["L_max_m"], L_min=lim["L_min_m"],
                   LD_min=lim["LD_min"], LD_max=lim["LD_max"], FEI_max=lim["FEI_max"],
                   T_metal_max=lim["T_metal_max_C"], min_metal_temp=lim["min_metal_temp_C"],
                   Re_t_min=lim["Re_tube_min"], v_tube=d.tube.v_tube, dP_tube_max=d.tube.dp_allow,
                   dP_shell_max=d.shell.dp_allow, Rf_tube=d.tube.fouling, Rf_shell=d.shell.fouling,
                   P_design=mec["design_pressure_barg"] * 1e5, CA=mec["corrosion_allowance_mm"] / 1e3,
                   eta=cst["fan_pump_efficiency"], elec=cst["electricity_usd_kWh"], hours=cst["hours_per_year"],
                   years=cst["years"], rate=cst["rate"], cost_per_kg=cst["per_kg_usd"],
                   cost_per_tube=cst["per_tube_usd"], cost_fixed=cst["fixed_usd"], n_zones=n_zones)


# ---------------------------------------------------------------------------------------------
@dataclass
class Zones:
    Q: float
    dQ: np.ndarray
    Th: np.ndarray            # K, zone mid
    Tc: np.ndarray
    lmtd: np.ndarray
    Th_e: np.ndarray          # K edges, index 0 = cold end (hot outlet / cold inlet)
    Tc_e: np.ndarray
    F: float
    m_tube: float
    m_shell: float
    tube_is_hot: bool
    tube: dict = field(default_factory=dict)     # property arrays of the tube-side fluid
    shell: dict = field(default_factory=dict)

    @property
    def Tt(self): return self.Th if self.tube_is_hot else self.Tc
    @property
    def Ts(self): return self.Tc if self.tube_is_hot else self.Th
    @property
    def i_tube_in(self): return -1 if self.tube_is_hot else 0
    @property
    def i_tube_out(self): return 0 if self.tube_is_hot else -1
    @property
    def i_shell_in(self): return 0 if self.tube_is_hot else -1
    @property
    def i_shell_out(self): return -1 if self.tube_is_hot else 0


def _props(fl, T, P):
    return {"mu": fl.mu(T), "k": fl.k(T), "cp": fl.cp(T), "Pr": fl.Pr(T), "rho": fl.rho(T, P)}


def make_zones(d, mh, mc, Thi, Tho, Tci, Tco, n, Ntp=1) -> Zones:
    """Equal-duty zones. Temperatures in K."""
    fh, fc = d.hot.fluid, d.cold.fluid
    Q = mh * (fh.h(Thi) - fh.h(Tho))
    Qe = np.linspace(0.0, Q, n + 1)
    Th_e = fh.T_from_h(fh.h(Tho) + Qe / mh)
    Tc_e = fc.T_from_h(fc.h(Tci) + Qe / mc)
    d1, d2 = Th_e[:-1] - Tc_e[:-1], Th_e[1:] - Tc_e[1:]
    with np.errstate(divide="ignore", invalid="ignore"):
        lm = np.where(np.abs(d1 - d2) < 1e-9, d1, (d2 - d1) / np.log(d2 / d1))
    if np.any(~np.isfinite(lm)) or np.any(lm <= 0):
        raise Infeasible("temperature cross inside the exchanger")
    Th, Tc = 0.5 * (Th_e[:-1] + Th_e[1:]), 0.5 * (Tc_e[:-1] + Tc_e[1:])
    F = 1.0
    if Ntp > 1:
        try:
            F = F_LMTD_Fakheri(Thi=Th_e[-1], Tho=Th_e[0], Tci=Tc_e[0], Tco=Tc_e[-1], shells=1)
        except Exception:
            F = float("nan")
        if not np.isfinite(F) or F < 0.8:
            raise Infeasible("LMTD correction F < 0.8 for multi-pass (temperature cross)")
    hot = _props(fh, Th, d.hot.P)
    cold = _props(fc, Tc, d.cold.P)
    tih = d.tube_side == "hot"
    return Zones(Q, np.diff(Qe), Th, Tc, lm, Th_e, Tc_e, F, mh if tih else mc, mc if tih else mh, tih,
                 hot if tih else cold, cold if tih else hot)


@dataclass
class Geometry:
    baffle: str
    tube: str
    Do: float
    Di: float
    tw: float
    pitch_ratio: float
    Pt: float
    angle: int
    Ntp: int
    Ds: float
    cut: float
    B_ratio: float
    L: float
    Nt: int
    t_ts: float
    L_eff: float
    B: float
    Bin: float        # end space at the shell-fluid INLET (rear end)
    Bout: float       # end space at the shell-fluid OUTLET (front end)
    Nb: int
    Lbb: float
    Dotl: float
    Dctl: float
    Lsb: float
    Ltb: float
    t_baffle: float
    n_tie: int
    d_tie: float
    Nss: int
    Lpp: float
    ST: float
    SL: float
    Sm: float
    Sm_in: float
    Sm_out: float
    Sw: float
    Swg: float
    Fw: float
    Fc: float
    Ssb: float
    Stb: float
    Fsbp: float
    Ntcc: float
    Ntcw: float
    theta_ds: float
    noz: dict

    def to_dict(self):
        return asdict(self)


def _pitches(Pt, angle):
    """(Lpp row spacing along flow, Ltp_eff, ST transverse, SL longitudinal)."""
    if angle == 30:
        return 0.866 * Pt, Pt, Pt, 0.866 * Pt
    if angle == 45:
        return 0.707 * Pt, 0.707 * Pt, 1.414 * Pt, 0.707 * Pt
    if angle == 60:
        return 0.5 * Pt, 0.866 * Pt, 1.732 * Pt, 0.5 * Pt
    return Pt, Pt, Pt, Pt


def ntiw_band(Ds, cut, Do):
    """Max |y| of tube centres for no-tubes-in-window baffles (hole edge 6 mm from baffle edge)."""
    return Ds / 2 - cut * Ds - Do / 2 - 6e-3


@lru_cache(maxsize=8192)
def _ntiw_count(Do, Pt, angle, Dotl, Ntp, Ds, cut, n_tie, d_tie):
    return tube_layout(Do, Pt, angle, Dotl, Ntp, Ds, cut, n_tie, d_tie, band=ntiw_band(Ds, cut, Do))["Nt"]


def build_geometry(p: dict, L: float, ctx, Nt_override: int | None = None, prefilter: bool = True) -> Geometry:
    s: Settings = ctx.settings
    d, z = ctx.design, ctx.zones
    Do, Di, tw = tube_dims(p["tube"])
    Pt, angle, Ntp, Ds, cut = p["pitch_ratio"] * Do, p["angle"], p["Ntp"], p["Ds"], p["cut"]
    ntiw = p.get("baffle", "SEG") == "NTIW"
    Lbb = mech.bundle_shell_clearance(Ds)
    Dotl = Ds - Lbb
    Dctl = Dotl - Do
    n_tie, d_tie = mech.tie_rods(Ds)
    if Nt_override:
        Nt = Nt_override
    elif ntiw:
        Nt = _ntiw_count(Do, Pt, angle, Dotl, Ntp, Ds, cut, n_tie, d_tie)
    else:
        Nt = Ntubes(DBundle=Dotl, Do=Do, pitch=Pt, Ntp=Ntp, angle=angle) - n_tie
    if Nt < 4 * Ntp:
        raise Infeasible("too few tubes")
    v_est = z.m_tube / (float(np.mean(z.tube["rho"])) * Nt / Ntp * math.pi / 4 * Di ** 2)
    if prefilter and not (0.85 * s.v_tube[0] <= v_est <= 1.15 * s.v_tube[1]):
        raise Infeasible("tube velocity out of range")
    t_ts = mech.tubesheet_thickness(Do, Pt, angle, Ds, s.P_design, CA_t=s.CA,
                                    pass_groove=5e-3 if Ntp > 1 else 0.0)["t"]
    L_eff = L - 2 * t_ts
    B = p["B_ratio"] * Ds
    if B < max(0.2 * Ds, 0.0508):
        raise Infeasible("baffle spacing below TEMA minimum")
    span = B if ntiw else 2 * B
    if span > mech.max_unsupported_span(Do):
        raise Infeasible("unsupported span > TEMA maximum")

    ti, to, si, so = z.i_tube_in, z.i_tube_out, z.i_shell_in, z.i_shell_out
    tb, sh = ctx.design.tube, ctx.design.shell
    rsi, rso = z.shell["rho"][si], z.shell["rho"][so]
    rti, rto = z.tube["rho"][ti], z.tube["rho"][to]
    noz_si = mech.select_nozzle(z.m_shell / rsi, rsi, sh.v_nozzle_in, 0.8 * Ds)
    noz_so = mech.select_nozzle(z.m_shell / rso, rso, sh.v_nozzle_out, 0.8 * Ds)
    hot_in = tb.T_in > 400
    noz_ti = mech.select_nozzle(z.m_tube / rti, rti, tb.v_nozzle_in, 0.9 * Ds, material="SS" if hot_in else "CS")
    noz_to = mech.select_nozzle(z.m_tube / rto, rto, tb.v_nozzle_out, 0.9 * Ds,
                                material="SS" if tb.T_out > 400 else "CS")
    Bin_min, Bout_min = noz_si["OD"] + 0.1, noz_so["OD"] + 0.1
    if L_eff - Bin_min - Bout_min < 0:
        raise Infeasible("tube too short for nozzles")
    Nb = int(math.floor((L_eff - Bin_min - Bout_min) / B)) + 1
    extra = L_eff - Bin_min - Bout_min - (Nb - 1) * B
    Bin, Bout = Bin_min + extra / 2, Bout_min + extra / 2

    t_baf = mech.baffle_thk(Ds, span)
    Ltb = mech.baffle_hole(Do, span) - Do
    Lsb = mech.baffle_shell_clearance(Ds)
    Lpp, Ltp_eff, ST, SL = _pitches(Pt, angle)
    arg = Ds * (1 - 2 * cut) / Dctl
    if abs(arg) >= 1:
        raise Infeasible("baffle cut outside bundle")
    th_ds = 2 * math.acos(1 - 2 * cut)
    th_ctl = 2 * math.acos(arg)
    Fw = 0.0 if ntiw else (th_ctl - math.sin(th_ctl)) / (2 * math.pi)
    Fc = 1 - 2 * Fw
    Swg = Ds ** 2 / 8 * (th_ds - math.sin(th_ds))
    Swt = Nt * Fw * math.pi * Do ** 2 / 4
    Sw = Swg - Swt
    if Sw <= 0:
        raise Infeasible("window flow area <= 0")
    per_len = Lbb + Dctl / Ltp_eff * (Pt - Do)
    Sm, Sm_in, Sm_out = B * per_len, Bin * per_len, Bout * per_len
    Ssb = math.pi * Ds * Lsb / 2 * (1 - th_ds / (2 * math.pi))
    Stb = math.pi / 4 * ((Do + Ltb) ** 2 - Do ** 2) * Nt * (1 - Fw)
    Fsbp = (Ds - Dotl) / per_len
    Ntcc = Ds * (1 - 2 * cut) / Lpp
    Ntcw = 0.0 if ntiw else 0.8 / Lpp * (Ds * cut - (Ds - Dctl) / 2)
    Nss = int(math.ceil(Ntcc / 6)) if Fsbp > 0.05 else 0
    return Geometry(p.get("baffle", "SEG"), p["tube"], Do, Di, tw, p["pitch_ratio"], Pt, angle, Ntp, Ds, cut,
                    p["B_ratio"], L, Nt, t_ts, L_eff, B, Bin, Bout, Nb, Lbb, Dotl, Dctl, Lsb, Ltb, t_baf,
                    n_tie, d_tie, Nss, Lpp, ST, SL, Sm, Sm_in, Sm_out, Sw, Swg, Fw, Fc, Ssb, Stb, Fsbp,
                    Ntcc, Ntcw, th_ds,
                    {"shell_in": noz_si, "shell_out": noz_so, "tube_in": noz_ti, "tube_out": noz_to})


# ---------------------------------------------------------------------------------------------
def _shell_J(g: Geometry, Re: float):
    lam = Re < 100
    Jc = 1.0 if g.baffle == "NTIW" else baffle_correction_Bell(g.Fc)
    Jl = baffle_leakage_Bell(g.Ssb, g.Stb, g.Sm)
    Jb = bundle_bypassing_Bell(min(g.Fsbp, 0.69), g.Nss, max(int(round(g.Ntcc)), 1), laminar=lam)
    Js = unequal_baffle_spacing_Bell(g.Nb, g.B, g.Bin, g.Bout, laminar=lam) if g.Nb > 1 else 1.0
    Jr = laminar_correction_Bell(Re, int((g.Ntcc + g.Ntcw) * (g.Nb + 1))) if lam else 1.0
    return {"Jc": Jc, "Jl": Jl, "Jb": Jb, "Js": Js, "Jr": Jr}


def _R_factors(g: Geometry, Re: float):
    rs = g.Ssb / (g.Ssb + g.Stb)
    rlm = (g.Ssb + g.Stb) / g.Sm
    p = -0.15 * (1 + rs) + 0.8
    Rl = math.exp(-1.33 * (1 + rs) * rlm ** p)
    rss = g.Nss / max(g.Ntcc, 1)
    Cbp = 4.5 if Re < 100 else 3.7
    Rb = math.exp(-Cbp * g.Fsbp * (1 - (2 * rss) ** (1 / 3))) if rss < 0.5 else 1.0
    return Rl, Rb


def _lmtd_total(z: Zones) -> float:
    d1 = z.Th_e[-1] - z.Tc_e[-1]
    d2 = z.Th_e[0] - z.Tc_e[0]
    return d1 if abs(d1 - d2) < 1e-9 else (d1 - d2) / math.log(d1 / d2)


def fabricated_weight(g: Geometry, s: Settings) -> float:
    """Quick fabricated-weight estimate (kg) used in the capital-cost objective."""
    rho = 7850.0
    t_sh = mech.shell_thickness(g.Ds, s.P_design)["t"]
    D_fl = g.Ds + 0.17
    w = math.pi * (g.Ds + t_sh) * t_sh * g.L * rho
    w += 2 * math.pi / 4 * D_fl ** 2 * g.t_ts * rho
    w += g.Nt * math.pi / 4 * (g.Do ** 2 - g.Di ** 2) * g.L * rho
    w += g.Nb * 0.8 * math.pi / 4 * g.Ds ** 2 * g.t_baffle * rho
    w += 2 * math.pi * (g.Ds + t_sh) * t_sh * 0.5 * rho
    w += 4 * math.pi / 4 * (D_fl ** 2 - g.Ds ** 2) * 0.03 * rho
    w += 2 * math.pi / 4 * D_fl ** 2 * mech.flat_cover_thk(D_fl - 0.05, s.P_design) * rho
    return 1.1 * w


def evaluate(g: Geometry, z: Zones, s: Settings, want_profile: bool = False) -> dict:
    n = len(z.dQ)
    T, S = z.tube, z.shell
    # ---- tube side ----
    At = g.Nt / g.Ntp * math.pi / 4 * g.Di ** 2
    Gt = z.m_tube / At
    eD = s.roughness / g.Di
    Lpath = g.L_eff * g.Ntp
    ht_, fdt, Ret = np.empty(n), np.empty(n), np.empty(n)
    for i in range(n):
        Re = Gt * g.Di / T["mu"][i]
        fd = fluids.friction_factor(Re=Re, eD=eD)
        if Re >= 2300:
            Nu = turbulent_Gnielinski(Re=Re, Pr=T["Pr"][i], fd=fd) * (1 + (g.Di / Lpath) ** (2 / 3))
        else:
            Nu = laminar_entry_Baehr_Stephan(Re=Re, Pr=T["Pr"][i], L=Lpath, Di=g.Di)
            fd = 64.0 / Re
        ht_[i], fdt[i], Ret[i] = Nu * T["k"][i] / g.Di, fd, Re
    # ---- shell side (Bell-Delaware) ----
    Gs = z.m_shell / g.Sm
    rows = max(int(round(g.Ntcc)), 1)
    hs, Res, dpbi, dpwi = np.empty(n), np.empty(n), np.empty(n), np.empty(n)
    Gw = z.m_shell / math.sqrt(g.Sm * g.Sw)
    J = _shell_J(g, float(Gs * g.Do / np.mean(S["mu"])))
    for i in range(n):
        Re = Gs * g.Do / S["mu"][i]
        Nu = Nu_ESDU_73031(Re=Re, Pr=S["Pr"][i], tube_rows=rows, pitch_parallel=g.SL, pitch_normal=g.ST)
        Jt = J["Jc"] * J["Jl"] * J["Jb"] * J["Js"] * (J["Jr"] if Re < 100 else 1.0)
        hs[i], Res[i] = Nu * S["k"][i] / g.Do * Jt, Re
        rho = S["rho"][i]
        dpbi[i] = dP_Zukauskas(Re=Re, n=rows, ST=g.ST, SL=g.SL, D=g.Do, rho=rho, Vmax=Gs / rho)
        dpwi[i] = (2 + 0.6 * g.Ntcw) * Gw ** 2 / (2 * rho)
    # ---- overall ----
    Rw = g.Do * math.log(g.Do / g.Di) / (2 * mech.K_WALL_CS)
    R_ti = g.Do / (g.Di * ht_)
    R_ft = s.Rf_tube * g.Do / g.Di
    R_so = 1 / hs
    Uc = 1 / (R_so + Rw + R_ti)
    Uf = 1 / (R_so + s.Rf_shell + Rw + R_ft + R_ti)
    dAf = z.dQ / (Uf * z.lmtd * z.F)
    dAc = z.dQ / (Uc * z.lmtd * z.F)
    A_req_f, A_req_c = dAf.sum(), dAc.sum()
    A_prov = g.Nt * math.pi * g.Do * g.L_eff
    w = dAf / A_req_f
    lm = _lmtd_total(z)
    # ---- tube dP ----
    rho_t = T["rho"]
    dp_fric = float(np.sum(w * fdt * Lpath / g.Di * Gt ** 2 / (2 * rho_t)))
    rho_tm = float(np.sum(w * rho_t))
    dp_ends = g.Ntp * (fluids.entrance_sharp() + fluids.exit_normal()) * Gt ** 2 / (2 * rho_tm)
    dp_ret = (g.Ntp - 1) * 1.0 * Gt ** 2 / (2 * rho_tm)
    dp_acc = Gt ** 2 * (1 / rho_t[z.i_tube_out] - 1 / rho_t[z.i_tube_in])
    nti, nto = g.noz["tube_in"], g.noz["tube_out"]
    dp_noz_t = 1.0 * rho_t[z.i_tube_in] * nti["v"] ** 2 / 2 + 0.5 * rho_t[z.i_tube_out] * nto["v"] ** 2 / 2
    dP_tube = dp_fric + dp_ends + dp_ret + dp_acc + dp_noz_t
    # ---- shell dP ----
    Rl, Rb = _R_factors(g, float(np.mean(Res)))
    dp_cross = max(g.Nb - 1, 0) * float(np.sum(w * dpbi)) * Rb * Rl
    dp_win = g.Nb * float(np.sum(w * dpwi)) * Rl

    def dp_end(Sm_end, i):
        G = z.m_shell / Sm_end
        rho = S["rho"][i]
        Re = G * g.Do / S["mu"][i]
        return dP_Zukauskas(Re=Re, n=rows, ST=g.ST, SL=g.SL, D=g.Do, rho=rho, Vmax=G / rho) * \
            (1 + g.Ntcw / g.Ntcc) * Rb
    dp_ends_s = dp_end(g.Sm_in, z.i_shell_in) + dp_end(g.Sm_out, z.i_shell_out)
    nsi, nso = g.noz["shell_in"], g.noz["shell_out"]
    rho_s = S["rho"]
    dp_noz_s = 1.0 * rho_s[z.i_shell_in] * nsi["v"] ** 2 / 2 + 0.5 * rho_s[z.i_shell_out] * nso["v"] ** 2 / 2
    dP_shell = dp_cross + dp_win + dp_ends_s + dp_noz_s
    # ---- metal temperatures (tube inner and outer surfaces), fouled and clean ----
    Tt, Ts = z.Tt, z.Ts
    dT = Tt - Ts
    in_f = Tt - dT * (R_ti + R_ft) * Uf
    in_c = Tt - dT * R_ti * Uc
    out_f = in_f - dT * Uf * Rw
    out_c = in_c - dT * Uc * Rw
    T_metal_max = float(max(in_f.max(), in_c.max(), out_f.max(), out_c.max())) - K
    T_metal_min = float(min(in_f.min(), in_c.min(), out_f.min(), out_c.min())) - K
    T_tube_mean = float(np.sum(w * 0.5 * (in_f + out_f))) - K
    # ---- costs ----
    V_t = z.m_tube / rho_tm
    V_s = z.m_shell / float(np.mean(rho_s))
    P_fan = (dP_tube * V_t + dP_shell * V_s) / s.eta
    W_est = fabricated_weight(g, s)
    C_cap = s.cost_fixed + s.cost_per_kg * W_est + s.cost_per_tube * g.Nt
    C_op_yr = P_fan / 1e3 * s.hours * s.elec
    C_op = sum(C_op_yr / (1 + s.rate) ** k for k in range(1, s.years + 1))
    out = {
        "Q": z.Q, "A_req_f": A_req_f, "A_req_c": A_req_c, "A_prov": A_prov, "overdesign": A_prov / A_req_f - 1,
        "U_f": z.Q / (A_req_f * lm * z.F), "U_c": z.Q / (A_req_c * lm * z.F), "U_f_prov": z.Q / (A_prov * lm * z.F),
        "LMTD": lm, "F": z.F, "h_t": float(np.sum(w * ht_)), "h_s": float(np.sum(w * hs)),
        "Re_t": float(np.sum(w * Ret)), "Re_s": float(np.sum(w * Res)),
        "Re_t_min": float(Ret.min()), "Re_t_max": float(Ret.max()),
        "Re_s_min": float(Res.min()), "Re_s_max": float(Res.max()),
        "v_t": Gt / rho_tm, "v_t_in": Gt / rho_t[z.i_tube_in], "v_s": Gs / float(np.mean(rho_s)),
        "dP_tube": dP_tube, "dP_shell": dP_shell,
        "dP_tube_parts": {"friction": dp_fric, "entry/exit": dp_ends, "pass returns": dp_ret,
                          "acceleration": dp_acc, "nozzles": dp_noz_t},
        "dP_shell_parts": {"crossflow": dp_cross, "windows": dp_win, "end zones": dp_ends_s, "nozzles": dp_noz_s},
        "J": J, "Rl": Rl, "Rb": Rb, "T_metal_max": T_metal_max, "T_metal_min": T_metal_min,
        "T_tube_mean": T_tube_mean,
        "R_parts": {"shell film": float(np.sum(w * R_so)), "shell fouling": s.Rf_shell, "wall": Rw,
                    "tube fouling": R_ft, "tube film": float(np.sum(w * R_ti))},
        "P_fan": P_fan, "P_fan_tube": dP_tube * V_t / s.eta, "P_fan_shell": dP_shell * V_s / s.eta,
        "W_est": W_est, "C_cap": C_cap, "C_hall": 8000 + 259.2 * A_prov ** 0.91, "C_op_yr": C_op_yr,
        "C_op": C_op, "TAC": C_cap + C_op,
    }
    if want_profile:
        x = np.concatenate(([0.0], np.cumsum(dAf))) / A_req_f            # 0 at cold end
        out["profile"] = {"x_frac": x, "Th_e": z.Th_e - K, "Tc_e": z.Tc_e - K, "x_mid": 0.5 * (x[:-1] + x[1:]),
                          "T_metal_f": np.minimum(in_f, out_f) - K, "T_metal_c": np.minimum(in_c, out_c) - K,
                          "h_t": ht_, "h_s": hs, "U_f": Uf, "U_c": Uc, "Re_t": Ret, "Re_s": Res}
    return out


def vibration(g: Geometry, z: Zones, design) -> dict:
    S = z.shell
    rho_s = float(np.mean(S["rho"]))
    V_c = z.m_shell / (g.Sm * rho_s)
    V_in = z.m_shell / (g.Sm_in * S["rho"][z.i_shell_in])
    V_out = z.m_shell / (g.Sm_out * S["rho"][z.i_shell_out])
    if g.baffle == "NTIW":
        spans = [("central span (B, pinned-pinned)", g.B, math.pi ** 2, V_c),
                 ("inlet end span (Bin, fixed-pinned)", g.Bin, 15.42, V_in),
                 ("outlet end span (Bout, fixed-pinned)", g.Bout, 15.42, V_out)]
    else:
        spans = [("central window tube (2B, pinned-pinned)", 2 * g.B, math.pi ** 2, V_c),
                 ("inlet end window tube (Bin+B, fixed-pinned)", g.Bin + g.B, 15.42, V_in),
                 ("outlet end window tube (Bout+B, fixed-pinned)", g.Bout + g.B, 15.42, V_out)]
    if g.angle in (30, 60):
        solidity = math.pi / 4 * g.Do ** 2 / (g.Pt ** 2 * math.sin(math.radians(60)))
    else:
        solidity = math.pi / 4 * g.Do ** 2 / g.Pt ** 2
    sh = design.shell
    Ts_mean = float(np.mean(z.Ts))
    return mech.tube_vibration(g.Do, g.Di, mech.MATERIALS["CS_tube"]["rho"], float(np.mean(z.tube["rho"])), rho_s,
                               spans, g.t_baffle, g.Nb + 1, g.pitch_ratio, g.angle, sh.fluid.sound_speed(Ts_mean),
                               g.Ds, solidity, shell_phase=sh.phase)


def check_constraints(g: Geometry, r: dict, s: Settings, vib: dict) -> list[str]:
    bad = []
    if r["dP_tube"] > s.dP_tube_max: bad.append("dP_tube")
    if r["dP_shell"] > s.dP_shell_max: bad.append("dP_shell")
    if not (s.v_tube[0] <= r["v_t"] <= s.v_tube[1]): bad.append("v_tube")
    if r["Re_t_min"] < s.Re_t_min: bad.append("Re_tube")
    if g.L > s.L_max + 1e-9: bad.append("L_max")
    if g.L < s.L_min: bad.append("L_min")
    if not (s.LD_min <= g.L / g.Ds <= s.LD_max): bad.append("L/D")
    if s.min_metal_temp is not None and r["T_metal_min"] < s.min_metal_temp: bad.append("min_metal_temp")
    if r["T_metal_max"] > s.T_metal_max: bad.append("T_metal_max")
    if vib["FEI_ratio_max"] > s.FEI_max: bad.append("FEI")
    if r["overdesign"] < s.SF - 1 - 1e-6: bad.append("area")
    return bad


def size_for_case(p: dict, ctx, Nt_override=None, max_iter=10):
    """Shortest tube length (50 mm steps) giving A_prov >= SF * A_req (fouled)."""
    s = ctx.settings
    ctx.zones = ctx.zsets[p["Ntp"]]
    Do = tube_dims(p["tube"])[0]
    g0 = build_geometry(p, 3.0, ctx, Nt_override)
    r0 = evaluate(g0, ctx.zones, s)
    L = math.ceil((s.SF * r0["A_req_f"] / (g0.Nt * math.pi * Do) + 2 * g0.t_ts) / 0.05) * 0.05
    g, r = g0, r0
    for _ in range(max_iter):
        if L > 3 * s.L_max:
            raise Infeasible("excessive length")
        g = build_geometry(p, L, ctx, Nt_override)
        r = evaluate(g, ctx.zones, s)
        need = s.SF * r["A_req_f"]
        if r["A_prov"] >= need - 1e-9:
            try:
                g2 = build_geometry(p, L - 0.05, ctx, Nt_override)
                r2 = evaluate(g2, ctx.zones, s)
                if r2["A_prov"] >= s.SF * r2["A_req_f"]:
                    L -= 0.05
                    continue
            except Infeasible:
                pass
            return g, r
        L = math.ceil((need / (g.Nt * math.pi * g.Do) + 2 * g.t_ts) / 0.05) * 0.05
        if L <= g.L:
            L = g.L + 0.05
    return g, r


def rate(g: Geometry, ctx, mh, Thi_C, mc, Tci_C, fouled=True, n_iter=60):
    """Off-design rating: outlets for given inlet flows/temperatures."""
    d, s = ctx.design, ctx.settings
    fh, fc = d.hot.fluid, d.cold.fluid
    Thi, Tci = Thi_C + K, Tci_C + K
    subtype = "counterflow" if g.Ntp == 1 else "S&T"
    s_eval = Settings(**{**s.__dict__, "Rf_tube": s.Rf_tube if fouled else 0.0,
                         "Rf_shell": s.Rf_shell if fouled else 0.0})
    A = g.Nt * math.pi * g.Do * g.L_eff
    Cmin = min(mh * float(fh.cp(Thi)), mc * float(fc.cp(Tci)))
    Tho = Thi - 0.6 * Cmin / (mh * float(fh.cp(Thi))) * (Thi - Tci)
    res = None
    for _ in range(n_iter):
        Q = mh * (fh.h(Thi) - fh.h(Tho))
        Tco = float(fc.T_from_h(fc.h(Tci) + Q / mc))
        z = make_zones(d, mh, mc, Thi, Tho, Tci, Tco, s.n_zones, 1)
        r = evaluate(g, z, s_eval)
        U_eff = z.Q / (r["A_req_f"] * _lmtd_total(z) * z.F)
        res = effectiveness_NTU_method(mh=mh, mc=mc, Cph=fh.cp_mean(Thi, Tho), Cpc=fc.cp_mean(Tco, Tci),
                                       subtype=subtype, Thi=Thi, Tci=Tci, UA=U_eff * A, n_shell_tube=1)
        if abs(res["Tho"] - Tho) < 0.01:
            Tho = res["Tho"]
            break
        Tho = 0.5 * Tho + 0.5 * res["Tho"]
    Q = mh * (fh.h(Thi) - fh.h(Tho))
    Tco = float(fc.T_from_h(fc.h(Tci) + Q / mc))
    z = make_zones(d, mh, mc, Thi, Tho, Tci, Tco, s.n_zones, 1)
    r = evaluate(g, z, s_eval, want_profile=True)
    return {"T_hot_out": Tho - K, "T_cold_out": Tco - K, "Q": float(Q), "NTU": res["NTU"],
            "effectiveness": res["effectiveness"], "U_eff": U_eff, "result": r, "zones": z,
            "m_hot": mh, "m_cold": mc, "T_hot_in": Thi_C, "T_cold_in": Tci_C}

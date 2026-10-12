"""Mechanical sizing per TEMA (Class C, 9th/10th ed. tables) and ASME VIII-1 rules.

These are preliminary sizing values for the GA, datasheet and fabrication drawings.
The fabricator's code calculation (ASME VIII-1, incl. App. 2 flanges and UHX
tubesheets) governs.
"""
from __future__ import annotations

import math

import numpy as np
from ht import L_unsupported_max, baffle_thickness, D_baffle_holes, shell_clearance

INCH = 0.0254
G = 9.80665

# --- Materials (allowable stresses approximate, ASME II-D; verify at final design) ------
MATERIALS = {
    "CS_plate": {"spec": "SA-516 Gr.70", "S": 138e6, "rho": 7850.0, "Tmax": 425.0},
    "SS_plate": {"spec": "SA-240 Tp.304", "S": 84e6, "rho": 8000.0, "Tmax": 815.0},  # S at ~550 degC
    "CS_tube": {"spec": "SA-214 (ERW CS)", "S": 92e6 * 0.85, "rho": 7850.0, "Tmax": 425.0},
    "CS_pipe": {"spec": "SA-106 Gr.B", "S": 118e6, "rho": 7850.0, "Tmax": 425.0},
    "SS_pipe": {"spec": "SA-312 TP304", "S": 84e6, "rho": 8000.0, "Tmax": 815.0},
    "CS_forging": {"spec": "SA-105", "S": 138e6, "rho": 7850.0, "Tmax": 425.0},
}
E_STEEL = 195e9          # Pa at ~250 degC
ALPHA_CS = 12.8e-6       # 1/K mean 20-300 degC
K_WALL_CS = 45.0         # W/m.K

STD_PLATES_MM = [5, 6, 8, 10, 12, 14, 16, 18, 20, 22, 25, 28, 30, 32, 36, 40, 45, 50, 56, 60]

# ASME B36.10/B36.19 pipe: NPS -> (OD mm, STD wall mm, 10S wall mm)
PIPE = {1: (33.4, 3.38, 2.77), 1.5: (48.3, 3.68, 2.77), 2: (60.3, 3.91, 2.77), 3: (88.9, 5.49, 3.05), 4: (114.3, 6.02, 3.05),
        6: (168.3, 7.11, 3.40), 8: (219.1, 8.18, 3.76), 10: (273.0, 9.27, 4.19),
        12: (323.8, 9.53, 4.57), 14: (355.6, 9.53, 4.78), 16: (406.4, 9.53, 4.78),
        18: (457.0, 9.53, 4.78), 20: (508.0, 9.53, 5.54), 24: (610.0, 9.53, 6.35),
        30: (762.0, 9.53, 7.92)}


def std_plate(t_m: float) -> float:
    t_mm = t_m * 1e3
    for p in STD_PLATES_MM:
        if p >= t_mm - 1e-9:
            return p / 1e3
    return math.ceil(t_mm) / 1e3


def tema_min_shell_thk(Ds: float) -> float:
    """TEMA CB-3.13 minimum shell thickness, carbon steel (Class C)."""
    d_in = Ds / INCH
    if d_in <= 12.5:
        return 7.0e-3        # ~ Sch.30 pipe
    if d_in <= 29.5:
        return 7.9e-3        # 5/16"
    if d_in <= 39.5:
        return 9.5e-3        # 3/8"
    if d_in <= 60.5:
        return 11.1e-3       # 7/16"
    return 12.7e-3


def cylinder_thk(D_in: float, P: float, S: float, E: float = 0.85, CA: float = 3e-3) -> float:
    """ASME VIII-1 UG-27(c)(1) circumferential stress, inside radius."""
    R = D_in / 2
    return P * R / (S * E - 0.6 * P) + CA


def shell_thickness(Ds, P, mat="CS_plate", CA=3e-3, E=0.85):
    S = MATERIALS[mat]["S"]
    t_calc = cylinder_thk(Ds, P, S, E, CA)
    t_sel = std_plate(max(t_calc, tema_min_shell_thk(Ds)))
    return {"t_calc": t_calc, "t_tema_min": tema_min_shell_thk(Ds), "t": t_sel}


def tema_min_tubesheet(Do: float) -> float:
    """TEMA RCB-7.11 minimum tubesheet thickness for expanded tube joints."""
    d_in = Do / INCH
    if d_in <= 1.0 + 1e-6:
        return 0.75 * Do
    if d_in <= 1.25 + 1e-6:
        return 22.2e-3
    if d_in <= 1.5 + 1e-6:
        return 25.4e-3
    return 31.8e-3


def tubesheet_thickness(Do, Pt, angle, Ds, P, S=MATERIALS["CS_plate"]["S"], CA_t=3e-3, CA_s=1.5e-3,
                        F=1.25, pass_groove=0.0):
    """Max of TEMA minimum and the TEMA RCB-7.132 bending formula T = F*G/3*sqrt(P/(eta*S))."""
    eta = 1 - (0.907 if angle in (30, 60) else 0.785) / (Pt / Do) ** 2
    t_bend = F * Ds / 3.0 * math.sqrt(P / (eta * S))
    t = max(t_bend, tema_min_tubesheet(Do)) + CA_t + CA_s + pass_groove
    return {"t_bend": t_bend, "t_tema_min": tema_min_tubesheet(Do), "eta": eta, "t": std_plate(t)}


def flat_cover_thk(d, P, S=MATERIALS["CS_plate"]["S"], C=0.3, CA=3e-3, t_min=16e-3):
    """ASME UG-34 bolted flat cover (gasket moment term neglected at this pressure) + CA."""
    return std_plate(max(d * math.sqrt(C * P / S) + CA, t_min))


def tie_rods(Ds: float):
    """TEMA CB-4.71 tie rods (Class C): returns (count, diameter m)."""
    d_in = Ds / INCH
    if d_in <= 15.5:
        return 4, 9.5e-3
    if d_in <= 27.5:
        return 6, 9.5e-3
    if d_in <= 33.5:
        return 6, 12.7e-3
    if d_in <= 48.5:
        return 8, 12.7e-3
    if d_in <= 60.5:
        return 10, 12.7e-3
    return 12, 15.9e-3


def tube_hole_dia(Do: float) -> float:
    """TEMA RCB-7.21 standard-fit tubesheet hole diameter."""
    extra = {0.75: 0.20e-3, 1.0: 0.25e-3, 1.25: 0.28e-3, 1.5: 0.36e-3, 2.0: 0.38e-3}
    key = min(extra, key=lambda k: abs(k - Do / INCH))
    return Do + extra[key]


def baffle_shell_clearance(Ds: float) -> float:
    """Diametral shell-to-baffle clearance (TEMA RCB-4.3), via ht.shell_clearance."""
    return shell_clearance(DShell=Ds)


def bundle_shell_clearance(Ds: float) -> float:
    """Diametral shell-ID-to-OTL clearance for a fixed tubesheet bundle (Taborek/HEDH)."""
    return 12e-3 + 0.005 * Ds


def max_unsupported_span(Do: float) -> float:
    return L_unsupported_max(Do=Do, material="CS")


def baffle_thk(Ds: float, L_unsupported: float) -> float:
    return baffle_thickness(Dshell=Ds, L_unsupported=L_unsupported, service="C")


def baffle_hole(Do: float, L_unsupported: float) -> float:
    return D_baffle_holes(Do=Do, L_unsupported=L_unsupported)


def select_nozzle(Vdot: float, rho: float, v_target: float, Ds_limit: float | None = None,
                  material: str = "CS", rho_v2_max: float = 2232.0) -> dict:
    """Smallest NPS with velocity <= v_target. If that exceeds the shell-limited size,
    use the largest allowed size that still meets the TEMA rho*v^2 limit (duct reducer)."""
    wall_idx = 2 if material == "SS" else 1
    sizes = sorted(PIPE)

    def info(nps):
        od, *_ = PIPE[nps]
        t = PIPE[nps][wall_idx]
        di = (od - 2 * t) / 1e3
        v = Vdot / (math.pi / 4 * di ** 2)
        return {"NPS": nps, "OD": od / 1e3, "t": t / 1e3, "ID": di, "v": v, "rho_v2": rho * v * v}

    chosen = next((info(n) for n in sizes if info(n)["v"] <= v_target), info(sizes[-1]))
    if Ds_limit is not None and chosen["OD"] > Ds_limit:
        allowed = [info(n) for n in sizes if PIPE[n][0] / 1e3 <= Ds_limit]
        ok = [a for a in allowed if a["rho_v2"] <= rho_v2_max]
        chosen = ok[-1] if ok else (allowed[-1] if allowed else info(sizes[0]))
        chosen["reduced"] = True
    return chosen


# --- Flow-induced vibration screening (TEMA Section 6 approach, simplified) ---------------
def strouhal(pitch_ratio: float, angle: int) -> float:
    """Screening Strouhal number: Weaver et al. fit for staggered arrays; 0.33 for in-line."""
    return 1.0 / (1.73 * pitch_ratio) if angle in (30, 45, 60) else 0.33


def tube_vibration(Do, Di, rho_metal, rho_tube_fluid, rho_shell_fluid, spans, baffle_t,
                   n_spans, pitch_ratio, angle, c_shell, Ds, solidity, beta=3.3, shell_phase="gas"):
    """spans: list of (label, length, end-constant C, crossflow velocity).
    Returns per-span natural frequency, Connors critical velocity, vortex shedding and
    shell acoustic frequencies (ratios used as screening criteria)."""
    I = math.pi / 64 * (Do ** 4 - Di ** 4)
    m = (rho_metal * math.pi / 4 * (Do ** 2 - Di ** 2) + rho_tube_fluid * math.pi / 4 * Di ** 2
         + 1.5 * rho_shell_fluid * math.pi / 4 * Do ** 2)
    St = strouhal(pitch_ratio, angle)
    c_eff = c_shell / math.sqrt(1 + solidity)
    fa = [n * c_eff / (2 * Ds) for n in (1, 2, 3, 4)]
    out = []
    for label, l, C, V in spans:
        fn = C / (2 * math.pi) * math.sqrt(E_STEEL * I / (m * l ** 4))
        if shell_phase == "gas":
            delta = 0.314 * (n_spans - 1) / n_spans * math.sqrt(baffle_t / l)  # TEMA V-8 (gas)
        else:
            delta = 0.03                                                       # typical liquid, screening
        V_crit = beta * fn * Do * math.sqrt(m * delta / (rho_shell_fluid * Do ** 2))
        fv = St * V / Do
        acoustic = [f for f in fa if 0.8 * f <= fv <= 1.2 * f] if shell_phase == "gas" else []
        # TEMA V-11.2 vortex-shedding peak amplitude (C_L = 0.05 conservative), limit 0.02*Do
        y_vs = 0.05 * rho_shell_fluid * Do * V ** 2 / (2 * math.pi ** 2 * delta * fn ** 2 * m)
        out.append({"span": label, "l": l, "fn": fn, "delta": delta, "V": V, "V_crit": V_crit,
                    "FEI_ratio": V / V_crit, "fv": fv, "fv_fn": fv / fn, "y_vs": y_vs,
                    "y_vs_ratio": y_vs / (0.02 * Do),
                    "acoustic_coincidence": acoustic})
    return {"m_per_m": m, "St": St, "fa": fa, "c_eff": c_eff, "spans": out,
            "FEI_ratio_max": max(o["FEI_ratio"] for o in out),
            "fv_fn_max": max(o["fv_fn"] for o in out),
            "y_vs_ratio_max": max(o["y_vs_ratio"] for o in out),
            "acoustic_risk": any(o["acoustic_coincidence"] for o in out)}


def differential_expansion(L, T_tube_metal, T_shell_metal, A_tubes_metal, A_shell_metal,
                           S_allow=MATERIALS["CS_tube"]["S"]):
    """Fixed-tubesheet axial differential expansion & tube stress without an expansion joint."""
    dT = T_tube_metal - T_shell_metal
    delta = ALPHA_CS * L * dT
    sigma_t = E_STEEL * ALPHA_CS * dT * A_shell_metal / (A_shell_metal + A_tubes_metal)
    return {"dT": dT, "delta": delta, "sigma_tube": sigma_t, "S_allow": S_allow,
            "expansion_joint_required": abs(sigma_t) > 0.5 * S_allow or abs(delta) > 3e-3,
            "bellows_axial_capacity": 1.5 * abs(delta)}

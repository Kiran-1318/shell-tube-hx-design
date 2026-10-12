"""Turn an optimised parameter set into a complete, fabrication-oriented design record."""
from __future__ import annotations

import math

import numpy as np

from . import mechanical as mech
from .layout import tube_layout
from .spec import override
from .thermal import size_for_case, vibration, check_constraints, rate, ntiw_band, tube_dims

PARAM_KEYS = ["baffle", "tube", "pitch_ratio", "angle", "Ntp", "Ds", "cut", "B_ratio"]


def _round_up(x, step):
    return math.ceil(x / step - 1e-9) * step


def body_flange(Ds, t_shell):
    """Indicative girth flange (final design per ASME VIII-1 Appendix 2)."""
    db = 0.016 if Ds <= 0.35 else (0.020 if Ds <= 0.65 else 0.024)
    BC = Ds + 2 * t_shell + 2 * (db + 0.025)
    OD = BC + 2 * (db + 0.018)
    n = max(8, int(math.ceil(math.pi * BC / 0.12 / 4)) * 4)
    t = mech.std_plate(max(0.025, 0.04 * Ds))
    return {"bolt": f"M{int(db * 1e3)}", "db": db, "hole": db + 0.003, "BC": BC, "OD": OD, "n_bolts": n, "t": t}


def finalize(p: dict, ctx) -> dict:
    d, s = ctx.design, ctx.settings
    ctx.zones = ctx.zsets[p["Ntp"]]
    Do, Di, tw = tube_dims(p["tube"])
    Pt = p["pitch_ratio"] * Do
    Dotl = p["Ds"] - mech.bundle_shell_clearance(p["Ds"])
    n_tie, d_tie = mech.tie_rods(p["Ds"])
    band = ntiw_band(p["Ds"], p["cut"], Do) if p.get("baffle") == "NTIW" else None
    lay = tube_layout(Do, Pt, p["angle"], Dotl, p["Ntp"], p["Ds"], p["cut"], n_tie, d_tie, band=band)
    g, r = size_for_case(p, ctx, Nt_override=lay["Nt"])
    vib = vibration(g, ctx.zones, d)
    viol = check_constraints(g, r, s, vib)

    # ---------------- ratings ----------------
    rt = {"Design, fouled": rate(g, ctx, d.hot.m, d.hot.T_in, d.cold.m, d.cold.T_in, fouled=True),
          "Design, clean": rate(g, ctx, d.hot.m, d.hot.T_in, d.cold.m, d.cold.T_in, fouled=False)}
    for case in d.spec.get("rating_cases", []):
        mh, Thi, mc, Tci = override(d, case.get("hot"), case.get("cold"))
        rt[case.get("label", "Case")] = rate(g, ctx, mh, Thi, mc, Tci, fouled=case.get("fouled", True))
    fr = d.spec.get("load_fractions", [])
    for f in fr:
        rt[f"{f * 100:.0f}% load, fouled"] = rate(g, ctx, f * d.hot.m, d.hot.T_in, f * d.cold.m, d.cold.T_in)
    if fr:
        f = min(fr)
        rt[f"{f * 100:.0f}% load, clean"] = rate(g, ctx, f * d.hot.m, d.hot.T_in, f * d.cold.m, d.cold.T_in,
                                                 fouled=False)
    sweep = []
    sw = d.spec.get("sweep")
    if sw:
        stream, var = sw.get("stream", "hot"), sw.get("var", "T_in")
        v = sw["from"]
        while v <= sw["to"] + 1e-9:
            over = {var: v} if var == "T_in" else {"flow_factor": v}
            mh, Thi, mc, Tci = override(d, over if stream == "hot" else None, over if stream == "cold" else None)
            x = rate(g, ctx, mh, Thi, mc, Tci, fouled=True)
            sweep.append({"value": v, "Q_kW": x["Q"] / 1e3, "T_hot_out": x["T_hot_out"], "T_cold_out": x["T_cold_out"],
                          "T_metal_max": x["result"]["T_metal_max"], "T_metal_min": x["result"]["T_metal_min"]})
            v += sw["step"]

    # ---------------- mechanical ----------------
    tb, sh = d.tube, d.shell
    T_metal_max = max(v["result"]["T_metal_max"] for v in rt.values())
    T_des_shell = _round_up(max(T_metal_max, sh.T_in, sh.T_out) + 25, 25)
    T_des_front = _round_up(tb.T_in + 30, 25)
    T_des_rear = _round_up(max(tb.T_out, rt["Design, clean"]["T_hot_out" if d.tube_side == "hot" else "T_cold_out"]) + 30, 25)
    P = s.P_design
    front_mat = "SS_plate" if tb.T_in > 400 else "CS_plate"
    rear_mat = "SS_plate" if tb.T_out > 400 else "CS_plate"
    shell = mech.shell_thickness(g.Ds, P, "CS_plate", CA=s.CA)
    ch_front = mech.shell_thickness(g.Ds, P, front_mat, CA=1.5e-3 if front_mat == "SS_plate" else s.CA)
    ch_rear = mech.shell_thickness(g.Ds, P, rear_mat, CA=1.5e-3 if rear_mat == "SS_plate" else s.CA)
    ts = mech.tubesheet_thickness(Do, Pt, g.angle, g.Ds, P, CA_t=s.CA, pass_groove=5e-3 if g.Ntp > 1 else 0.0)
    flange = body_flange(g.Ds, max(shell["t"], ch_front["t"]))
    cover_front = mech.flat_cover_thk(flange["BC"], P, mech.MATERIALS[front_mat]["S"], CA=s.CA)
    cover_rear = mech.flat_cover_thk(flange["BC"], P, mech.MATERIALS[rear_mat]["S"], CA=s.CA)
    nz = g.noz
    rear_has_nozzle = g.Ntp % 2 == 1
    L_ch_front = _round_up((max(nz["tube_in"]["OD"], nz["tube_out"]["OD"]) if not rear_has_nozzle
                            else nz["tube_in"]["OD"]) + 0.30, 0.05)
    L_ch_rear = _round_up(nz["tube_out"]["OD"] + 0.30, 0.05) if rear_has_nozzle else _round_up(0.15 + 0.1 * g.Ds, 0.05)
    S_t = mech.MATERIALS["CS_tube"]["S"]
    t_tube_req = P * Do / (2 * S_t + 0.8 * P)
    T_shell_mean = float(np.mean(ctx.zones.Ts)) - 273.15
    A_t = g.Nt * math.pi / 4 * (Do ** 2 - Di ** 2)
    A_s = math.pi * (g.Ds + shell["t"]) * shell["t"]
    expn = mech.differential_expansion(g.L, r["T_tube_mean"], T_shell_mean, A_t, A_s)
    tema_rear = "L"
    W = {}
    rho_cs, rho_ss = 7850.0, 8000.0
    rho_f = rho_ss if front_mat == "SS_plate" else rho_cs
    rho_r = rho_ss if rear_mat == "SS_plate" else rho_cs
    W["tubes"] = g.Nt * math.pi / 4 * (Do ** 2 - Di ** 2) * g.L * rho_cs
    L_shell = g.L - 2 * ts["t"]
    W["shell"] = math.pi * (g.Ds + shell["t"]) * shell["t"] * L_shell * rho_cs
    W["tubesheets"] = 2 * (math.pi / 4 * flange["OD"] ** 2 - g.Nt * math.pi / 4 * mech.tube_hole_dia(Do) ** 2) * ts["t"] * rho_cs
    baf_area = (math.pi / 4 * g.Ds ** 2 - g.Swg) - (g.Nt * (1 - g.Fw)) * math.pi / 4 * (Do + g.Ltb) ** 2
    W["baffles"] = g.Nb * baf_area * g.t_baffle * rho_cs
    W["tie rods + spacers"] = g.n_tie * (math.pi / 4 * g.d_tie ** 2 + math.pi / 4 * ((g.d_tie + 0.012) ** 2 - (g.d_tie + 0.003) ** 2)) * L_shell * rho_cs
    W["channels"] = (math.pi * (g.Ds + ch_front["t"]) * ch_front["t"] * L_ch_front * rho_f
                     + math.pi * (g.Ds + ch_rear["t"]) * ch_rear["t"] * L_ch_rear * rho_r)
    W["body flanges"] = 4 * math.pi / 4 * (flange["OD"] ** 2 - g.Ds ** 2) * flange["t"] * rho_cs
    W["covers"] = math.pi / 4 * flange["OD"] ** 2 * (cover_front * rho_f + cover_rear * rho_r)
    W["nozzles, bellows, misc."] = 0.12 * sum(W.values())
    W["saddles"] = 2 * (0.012 * (g.Ds + 0.3) * 0.6 * 1.5) * rho_cs
    W_empty = sum(W.values())
    V_shell = (math.pi / 4 * g.Ds ** 2 - g.Nt * math.pi / 4 * Do ** 2) * L_shell
    V_tube = g.Nt * math.pi / 4 * Di ** 2 * g.L + math.pi / 4 * g.Ds ** 2 * (L_ch_front + L_ch_rear)
    ratio = mech.MATERIALS["CS_plate"]["S"] / mech.MATERIALS[front_mat]["S"]
    mechd = {
        "P_design_barg": P / 1e5, "T_design_shell": T_des_shell, "T_design_tube_front": T_des_front,
        "T_design_tube_rear": T_des_rear, "P_test_shell_barg": 1.3 * P / 1e5, "P_test_tube_barg": 1.3 * P / 1e5 * ratio,
        "front_material": mech.MATERIALS[front_mat]["spec"], "rear_material": mech.MATERIALS[rear_mat]["spec"],
        "front_is_ss": front_mat == "SS_plate", "rear_is_ss": rear_mat == "SS_plate",
        "hot_tube_inlet": tb.T_in > 400, "shell": shell, "channel_front": ch_front, "channel_rear": ch_rear,
        "tubesheet": ts, "flange": flange, "cover_front": cover_front, "cover_rear": cover_rear,
        "L_ch_front": L_ch_front, "L_ch_rear": L_ch_rear, "L_shell": L_shell, "rear_has_nozzle": rear_has_nozzle,
        "tube_t_req": t_tube_req, "tube_hole": mech.tube_hole_dia(Do), "baffle_hole": Do + g.Ltb,
        "baffle_OD": g.Ds - g.Lsb, "expansion": expn, "T_shell_mean": T_shell_mean, "weights": W,
        "W_empty": W_empty, "W_flooded": W_empty + 1000 * (V_shell + V_tube),
        "overall_length": g.L + L_ch_front + L_ch_rear + cover_front + cover_rear,
        "L_unsupported_max": mech.max_unsupported_span(Do),
        "tema_type": "AE" + tema_rear, "expansion_joint": expn["expansion_joint_required"],
    }
    rho_si = ctx.zones.shell["rho"][ctx.zones.i_shell_in]
    A_be = g.Bin * g.Ds * (1 - g.Do / g.Pt)
    bundle_rv2 = rho_si * (d.shell.m / (rho_si * A_be)) ** 2
    T_dew = None
    for st in (d.hot, d.cold):
        td = st.fluid.water_dew_point_C(st.P)
        if td is not None:
            T_dew = td if T_dew is None else max(T_dew, td)
    return {"params": p, "geom": g, "layout": lay, "result": r, "vib": vib, "violations": viol, "ratings": rt,
            "sweep": sweep, "mech": mechd, "design": d, "settings": s, "T_dew": T_dew, "bundle_entrance_rv2": bundle_rv2}

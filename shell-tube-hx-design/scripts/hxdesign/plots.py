"""Result plots (SVG via matplotlib). Colours: one hue per stream, kept across all plots."""
from __future__ import annotations

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from .optimize import pareto_front

C = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#4a3aa7"]
HOT, COLD, METAL, METAL2 = C[1], C[0], C[2], C[3]
INK, INK2, GRID = "#0b0b0b", "#52514e", "#e5e4e0"
MARKERS = ["o", "s", "^", "D", "v"]

plt.rcParams.update({
    "font.family": "DejaVu Sans", "font.size": 9.5, "axes.edgecolor": INK2, "axes.labelcolor": INK,
    "axes.titlesize": 11, "axes.titleweight": "bold", "axes.titlelocation": "left",
    "xtick.color": INK2, "ytick.color": INK2, "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.8,
    "axes.spines.top": False, "axes.spines.right": False, "lines.linewidth": 2.0,
    "legend.frameon": False, "svg.fonttype": "none", "figure.dpi": 110,
})


def _save(fig, path):
    fig.tight_layout()
    fig.savefig(path, format="svg")
    plt.close(fig)


def _pos(d, frac):
    """Distance from the tube-side inlet tubesheet for a fraction measured from the cold end."""
    L = d["geom"].L_eff
    return (1 - frac) * L if d["design"].tube_side == "hot" else frac * L


def temperature_profile(d, path):
    D = d["design"]
    pr = d["ratings"]["Design, fouled"]["result"]["profile"]
    prc = d["ratings"]["Design, clean"]["result"]["profile"]
    pe, pm, pmc = _pos(d, pr["x_frac"]), _pos(d, pr["x_mid"]), _pos(d, prc["x_mid"])
    fig, ax = plt.subplots(figsize=(8.2, 4.6))
    ax.plot(pe, pr["Th_e"], color=HOT, label=f"{D.hot.name} (hot, {'tube' if D.tube_side == 'hot' else 'shell'} side)")
    ax.plot(pe, pr["Tc_e"], color=COLD, label=f"{D.cold.name} (cold, {'shell' if D.tube_side == 'hot' else 'tube'} side)")
    ax.plot(pm, pr["T_metal_f"], color=METAL, ls="--", lw=1.6, label="Coldest tube metal, fouled")
    ax.plot(pmc, prc["T_metal_c"], color=METAL2, ls=":", lw=1.8, label="Coldest tube metal, clean")
    if d.get("T_dew") is not None:
        ax.axhline(d["T_dew"], color=INK2, lw=1, ls="-.")
        ax.text(d["geom"].L_eff * 0.98, d["T_dew"] + 3, f"water dew point {d['T_dew']:.0f} °C", ha="right",
                color=INK2, fontsize=8.5)
    for arr in (pr["Th_e"], pr["Tc_e"]):
        for i in (0, -1):
            ax.annotate(f"{arr[i]:.0f} °C", (pe[i], arr[i]), xytext=(4, 4), textcoords="offset points", color=INK, fontsize=8.5)
    ax.set_xlabel("Distance from tube-side inlet tubesheet (m)")
    ax.set_ylabel("Temperature (°C)")
    ax.set_title("Temperature profile at design flow (fouled, as built)")
    ax.legend(loc="best", fontsize=8.5)
    ax.set_xlim(0, d["geom"].L_eff)
    _save(fig, path)


def local_coefficients(d, path):
    pr = d["ratings"]["Design, fouled"]["result"]["profile"]
    pos = _pos(d, pr["x_mid"])
    fig, ax = plt.subplots(figsize=(8.2, 4.2))
    ax.plot(pos, pr["h_s"], color=C[0], label="h shell (Bell-Delaware)")
    ax.plot(pos, pr["h_t"], color=C[1], label="h tube (Gnielinski)")
    ax.plot(pos, pr["U_f"], color=C[2], label="U fouled (outside area)")
    ax.plot(pos, pr["U_c"], color=C[3], ls="--", label="U clean")
    ax.set_xlabel("Distance from tube-side inlet tubesheet (m)")
    ax.set_ylabel("Coefficient (W/m²·K)")
    ax.set_ylim(0, None)
    ax.set_title("Local heat-transfer coefficients along the exchanger")
    ax.legend(ncol=2, loc="lower center")
    _save(fig, path)


def reynolds_profile(d, path, Re_target=10000.0):
    pr = d["ratings"]["Design, fouled"]["result"]["profile"]
    pos = _pos(d, pr["x_mid"])
    L = d["geom"].L_eff
    fig, axes = plt.subplots(1, 2, figsize=(9.4, 3.9))
    axes[0].plot(pos, pr["Re_t"], color=C[1], marker="o", ms=3)
    for v, lab, ls in ((2300, "laminar limit 2,300", ":"), (Re_target, "fully turbulent 10,000", "-.")):
        axes[0].axhline(v, color=INK2, lw=1, ls=ls)
        axes[0].text(L * 0.98, v, lab, ha="right", va="bottom", color=INK2, fontsize=8.5)
    axes[0].set_ylim(0, max(pr["Re_t"].max(), Re_target) * 1.15)
    axes[0].set_title("Tube side Re (tube ID)", fontsize=10)
    axes[1].plot(pos, pr["Re_s"], color=C[0], marker="o", ms=3)
    axes[1].axhline(100, color=INK2, lw=1, ls=":")
    axes[1].text(L * 0.98, 100, "Bell-Delaware laminar limit 100", ha="right", va="bottom", color=INK2, fontsize=8.5)
    axes[1].set_ylim(0, pr["Re_s"].max() * 1.2)
    axes[1].set_title("Shell side crossflow Re (tube OD)", fontsize=10)
    for ax in axes:
        ax.set_xlabel("Distance from tube-side inlet tubesheet (m)")
        ax.set_ylabel("Reynolds number (-)")
    _save(fig, path)


def optimization_tradeoff(df, sel, path):
    feas = df[df.feasible.astype(bool)]
    fig, ax = plt.subplots(figsize=(8.2, 5.0))
    for i, (tube, grp) in enumerate(feas.groupby("tube", sort=False)):
        ax.scatter(grp["A_prov"], grp["P_fan"] / 1e3, s=14, color=C[i % 6], marker=MARKERS[i % 5], alpha=0.55,
                   edgecolors="none", label=f"{tube} tubes ({len(grp)})")
    pf = pareto_front(feas, "A_prov", "P_fan")
    ax.plot(pf["A_prov"], pf["P_fan"] / 1e3, color=INK, lw=1.4, label="Pareto front")
    ax.scatter([sel["A_prov"]], [sel["P_fan"] / 1e3], s=180, marker="*", color=C[5], edgecolors="white",
               linewidths=1.2, zorder=5, label="Selected (min. total cost)")
    ax.set_xlabel("Heat-transfer area provided (m²)")
    ax.set_ylabel("Fan / pump power, both sides (kW)")
    ax.set_title("Design-space search: area vs. pumping power (feasible designs)")
    ax.legend(loc="upper right")
    _save(fig, path)


def tac_vs_shell(df, sel, path):
    feas = df[df.feasible.astype(bool)]
    fig, ax = plt.subplots(figsize=(8.2, 4.6))
    for i, (tube, grp) in enumerate(feas.groupby("tube", sort=False)):
        best = grp.groupby("Ds")["TAC"].min() / 1e3
        ax.plot(best.index * 1e3, best.values, color=C[i % 6], marker=MARKERS[i % 5], ms=5, label=f"{tube} tubes")
    ax.scatter([sel["Ds"] * 1e3], [sel["TAC"] / 1e3], s=180, marker="*", color=C[5], edgecolors="white",
               zorder=5, label="Selected")
    ax.set_xlabel("Shell inside diameter (mm)")
    ax.set_ylabel("Total cost: capital + PV of pumping power (kUSD)")
    ax.set_title("Lowest total cost per shell size")
    ax.legend()
    _save(fig, path)


def constraint_summary(df, path):
    counts = {}
    for v in df.loc[~df.feasible.astype(bool), "violations"].fillna(""):
        for item in str(v).split(";"):
            if not item:
                continue
            key = item.replace("geometry:", "") if item.startswith("geometry") else item.split(":")[0]
            counts[key] = counts.get(key, 0) + 1
    s = pd.Series(counts).sort_values()
    fig, ax = plt.subplots(figsize=(8.2, 0.32 * len(s) + 1.4))
    ax.barh(s.index, s.values, color=C[0], height=0.6)
    for y, v in enumerate(s.values):
        ax.text(v, y, f" {v:,}", va="center", color=INK, fontsize=8.5)
    ax.set_xlabel("Candidate designs rejected (a design can fail several checks)")
    ax.set_title(f"Why candidates were rejected  ({(~df.feasible.astype(bool)).sum():,} of {len(df):,})")
    ax.grid(axis="y", visible=False)
    _save(fig, path)


def resistance_breakdown(d, path):
    rp = d["result"]["R_parts"]
    tot = sum(rp.values())
    s = pd.Series({k: v / tot * 100 for k, v in rp.items()}).sort_values()
    fig, ax = plt.subplots(figsize=(7.5, 3.4))
    ax.barh(s.index, s.values, color=C[0], height=0.6)
    for y, v in enumerate(s.values):
        ax.text(v, y, f" {v:.1f} %", va="center", color=INK, fontsize=9)
    ax.set_xlabel("Share of total thermal resistance (%)")
    ax.set_title(f"Thermal resistance breakdown (U fouled = {1 / tot:.1f} W/m²·K)")
    ax.grid(axis="y", visible=False)
    ax.set_xlim(0, s.max() * 1.2)
    _save(fig, path)


def bell_delaware(d, path):
    J = d["result"]["J"]
    labels = {"Jc": "Jc baffle cut", "Jl": "Jl leakage", "Jb": "Jb bundle bypass", "Js": "Js unequal spacing",
              "Jr": "Jr laminar"}
    s = pd.Series({labels[k]: v for k, v in J.items()})
    fig, ax = plt.subplots(figsize=(7.5, 3.4))
    ax.barh(s.index[::-1], s.values[::-1], color=C[2], height=0.6)
    for y, v in enumerate(s.values[::-1]):
        ax.text(v, y, f" {v:.3f}", va="center", color=INK, fontsize=9)
    ax.axvline(1.0, color=INK2, lw=1)
    ax.set_title(f"Bell-Delaware shell-side correction factors (product = {float(np.prod(list(J.values()))):.3f})")
    ax.set_xlim(0, 1.3)
    ax.grid(axis="y", visible=False)
    _save(fig, path)


def pressure_drop_breakdown(d, path):
    r, s = d["result"], d["settings"]
    fig, axes = plt.subplots(1, 2, figsize=(9, 3.6))
    for ax, key, title, lim, col in ((axes[0], "dP_tube_parts", f"Tube side: {r['dP_tube']:.0f} Pa", s.dP_tube_max, C[1]),
                                     (axes[1], "dP_shell_parts", f"Shell side: {r['dP_shell']:.0f} Pa", s.dP_shell_max, C[0])):
        ser = pd.Series(r[key])
        ax.barh(ser.index[::-1], ser.values[::-1], color=col, height=0.6)
        for y, v in enumerate(ser.values[::-1]):
            ax.text(max(v, 0), y, f" {v:.0f}", va="center", color=INK, fontsize=8.5)
        ax.set_title(title, fontsize=10)
        ax.set_xlabel(f"Pa (allowable {lim:.0f})")
        ax.grid(axis="y", visible=False)
    _save(fig, path)


def offdesign(d, path):
    D = d["design"]
    rows = list(d["ratings"].items())
    fig, ax = plt.subplots(figsize=(8.2, 0.55 * len(rows) + 1.8))
    y = np.arange(len(rows))
    ax.scatter([v["T_cold_out"] for _, v in rows], y, color=COLD, s=60, label=f"{D.cold.name} outlet", zorder=3)
    ax.scatter([v["T_hot_out"] for _, v in rows], y, color=HOT, s=60, marker="s", label=f"{D.hot.name} outlet", zorder=3)
    ax.scatter([v["result"]["T_metal_min"] for _, v in rows], y, color=METAL, s=60, marker="^",
               label="Min. tube metal", zorder=3)
    if d.get("T_dew") is not None:
        ax.axvline(d["T_dew"], color=INK2, lw=1, ls="-.")
        ax.text(d["T_dew"] + 1, -0.35, f"dew point {d['T_dew']:.0f} °C", color=INK2, fontsize=8.5)
    ax.set_yticks(y, [k for k, _ in rows])
    ax.invert_yaxis()
    ax.set_xlabel("Temperature (°C)")
    ax.set_title("Off-design rating of the selected exchanger")
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.16), ncol=3)
    _save(fig, path)


def sensitivity(d, path):
    if not d["sweep"]:
        return False
    sw = pd.DataFrame(d["sweep"])
    spec = d["design"].spec["sweep"]
    xl = f"{spec.get('stream', 'hot')} {'inlet temperature (°C)' if spec.get('var', 'T_in') == 'T_in' else 'flow factor (-)'}"
    fig, axes = plt.subplots(1, 2, figsize=(9.4, 3.9))
    axes[0].plot(sw["value"], sw["Q_kW"], color=C[0], marker="o", ms=4)
    axes[0].set_xlabel(xl.capitalize())
    axes[0].set_ylabel("Heat duty (kW)")
    axes[0].set_title("Duty", fontsize=10)
    axes[1].plot(sw["value"], sw["T_cold_out"], color=COLD, marker="o", ms=4, label="Cold outlet")
    axes[1].plot(sw["value"], sw["T_hot_out"], color=HOT, marker="s", ms=4, label="Hot outlet")
    axes[1].plot(sw["value"], sw["T_metal_max"], color=METAL2, marker="^", ms=4, label="Max. tube metal")
    axes[1].set_xlabel(xl.capitalize())
    axes[1].set_ylabel("Temperature (°C)")
    axes[1].set_title("Outlet and metal temperatures (fouled)", fontsize=10)
    axes[1].legend()
    _save(fig, path)
    return True

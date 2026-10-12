"""Design specification: load a JSON spec, fill defaults, close the energy balance.

A spec describes two single-phase streams ("hot" and "cold"), which one goes in the
tubes, limits, cost data and project metadata. See references/spec_schema.md.
"""
from __future__ import annotations

import copy
import json
from dataclasses import dataclass, field
from pathlib import Path

from .props import Fluid, build_fluid

P_ATM = 101325.0

# Molecular weights used by the combustion helper (integer values, as in most hand calcs)
MW = {"N2": 28.0, "CO": 28.0, "H2": 2.0, "CO2": 44.0, "CH4": 16.0, "O2": 32.0, "H2O": 18.0,
      "C2H6": 30.0, "C3H8": 44.0, "Ar": 40.0}
# O2 demand per mole and products for common fuel-gas species
_COMB = {"CO": (0.5, {"CO2": 1}), "H2": (0.5, {"H2O": 1}), "CH4": (2.0, {"CO2": 1, "H2O": 2}),
         "C2H6": (3.5, {"CO2": 2, "H2O": 3}), "C3H8": (5.0, {"CO2": 3, "H2O": 4})}
THERMO_NAMES = {"CO2": "carbon dioxide", "H2O": "water", "N2": "nitrogen", "O2": "oxygen", "Ar": "argon",
                "CO": "carbon monoxide", "H2": "hydrogen", "CH4": "methane"}

GAS_DEFAULTS = {"v_tube": [8.0, 25.0], "v_nozzle": 15.0, "dp_kPa": 1.5}
LIQ_DEFAULTS = {"v_tube": [0.8, 3.0], "v_nozzle": 2.5, "dp_kPa": 70.0}

DEFAULT_SPEC = {
    "project": {"name": "Shell & tube heat exchanger", "tag": "E-101", "client": "", "date": ""},
    "tube_side": "hot",
    "limits": {"L_max_m": 6.096, "L_min_m": 1.5, "LD_min": 3.0, "LD_max": 15.0, "FEI_max": 0.8,
               "area_safety_factor": 1.25, "T_metal_max_C": 400.0, "min_metal_temp_C": None,
               "Re_tube_min": 0.0},
    "mechanical": {"design_pressure_barg": None, "corrosion_allowance_mm": 3.0, "tema_class": "C"},
    "costs": {"per_kg_usd": 6.0, "per_tube_usd": 25.0, "fixed_usd": 5000.0, "electricity_usd_kWh": 0.12,
              "hours_per_year": 8000.0, "years": 10, "rate": 0.10, "fan_pump_efficiency": 0.70},
    "grid": {
        "baffle": ["SEG", "NTIW"],
        "tube": ["0.75in", "1in", "1.25in", "1.5in", "2in"],
        "pitch_ratio": [1.25, 1.33, 1.5],
        "angle": [30, 45, 90],
        "Ntp": [1, 2, 4],
        "Ds_range_m": [0.15, 1.25],
        "cut": [0.2, 0.25, 0.3, 0.35, 0.45],
        "B_ratio": [0.3, 0.4, 0.6, 0.8, 1.0, 1.5, 2.0, 3.0],
    },
    "rating_cases": [],          # list of {"label":..., "hot": {...overrides}, "cold": {...}}
    "load_fractions": [0.75, 0.5],
    "sweep": None,               # {"stream": "hot", "var": "T_in", "from": 300, "to": 700, "step": 25}
}


def _merge(base, over):
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def combustion(fuel_flow_Nm3_h: float, fuel: dict, excess_air: float, O2_air: float = 0.21,
               Vm: float = 22.414) -> dict:
    """Flue gas from complete combustion of a fuel gas (vol fractions) with excess air."""
    O2_st = sum(fuel.get(s, 0.0) * _COMB[s][0] for s in _COMB)
    air = O2_st / O2_air * (1 + excess_air)
    flue = {"CO2": fuel.get("CO2", 0.0), "H2O": fuel.get("H2O", 0.0),
            "N2": fuel.get("N2", 0.0) + air * (1 - O2_air), "O2": air * O2_air - O2_st}
    for s, (_, prod) in _COMB.items():
        for p_, n in prod.items():
            flue[p_] += fuel.get(s, 0.0) * n
    tot = sum(flue.values())
    y = {k: v / tot for k, v in flue.items() if v > 0}
    kg_h = sum(flue[k] * fuel_flow_Nm3_h * MW[k] / Vm for k in flue)
    return {"y": y, "flue_Nm3_h": tot * fuel_flow_Nm3_h, "flue_kg_h": kg_h,
            "air_Nm3_h": air * fuel_flow_Nm3_h, "O2_stoich": O2_st}


@dataclass
class Stream:
    role: str                 # "hot" | "cold"
    name: str
    phase: str                # "gas" | "liquid"
    fluid: Fluid
    T_in: float               # degC
    T_out: float
    m: float                  # kg/s
    P: float                  # Pa abs
    fouling: float            # m2K/W
    dp_allow: float           # Pa
    v_tube: tuple
    v_nozzle_in: float
    v_nozzle_out: float
    meta: dict = field(default_factory=dict)


@dataclass
class Design:
    spec: dict
    hot: Stream
    cold: Stream
    Q: float                  # W
    tube_side: str

    @property
    def tube(self) -> Stream:
        return self.hot if self.tube_side == "hot" else self.cold

    @property
    def shell(self) -> Stream:
        return self.cold if self.tube_side == "hot" else self.hot


def _stream_fluid(sd: dict, cache: Path, T_lo: float, T_hi: float):
    if "from_combustion" in sd:
        c = sd["from_combustion"]
        comb = combustion(c["fuel_flow_Nm3_h"], c["fuel"], c.get("excess_air", 0.1), c.get("O2_in_air", 0.21))
        sd = dict(sd)
        sd["components"] = {THERMO_NAMES[k]: v for k, v in comb["y"].items()}
        sd["basis"] = "mole"
        sd.setdefault("flow_kg_h", comb["flue_kg_h"])
        sd["_combustion"] = comb
    known = [t for t in (sd.get("T_in"), sd.get("T_out")) if t is not None]
    need = (min(known), max(known)) if len(known) == 2 else None
    fl = build_fluid(sd["name"], sd["components"], sd.get("basis", "mole"), sd.get("phase", "gas"),
                     float(sd.get("P_kPa_abs", 101.325)) * 1e3, T_lo, T_hi, cache, need)
    return sd, fl


def load(spec_path_or_dict, cache_dir: Path) -> Design:
    raw = spec_path_or_dict if isinstance(spec_path_or_dict, dict) else json.loads(Path(spec_path_or_dict).read_text())
    spec = _merge(DEFAULT_SPEC, raw)
    h, c = spec["hot"], spec["cold"]
    temps = [t for t in (h.get("T_in"), h.get("T_out"), c.get("T_in"), c.get("T_out")) if t is not None]
    sweep = spec.get("sweep") or {}
    extra = [sweep.get("from", temps[0]), sweep.get("to", temps[0])] if sweep else []
    T_lo, T_hi = min(temps + extra) - 15.0, max(temps + extra) + 40.0
    h, fh = _stream_fluid(h, cache_dir, T_lo, T_hi)
    c, fc = _stream_fluid(c, cache_dir, T_lo, T_hi)

    # ---- close the energy balance: exactly one of the four may be missing ---------------
    mh = h.get("flow_kg_h"); mc = c.get("flow_kg_h")
    mh = mh / 3600 if mh else None
    mc = mc / 3600 if mc else None
    Thi, Tho, Tci, Tco = h.get("T_in"), h.get("T_out"), c.get("T_in"), c.get("T_out")
    if Thi is None or Tci is None:
        raise ValueError("Both inlet temperatures are required.")
    K = 273.15
    missing = [k for k, v in (("hot flow", mh), ("hot T_out", Tho), ("cold flow", mc), ("cold T_out", Tco)) if v is None]
    if len(missing) != 1:
        raise ValueError(f"Specify all but one of hot flow, hot T_out, cold flow, cold T_out (missing: {missing}).")
    if mh and Tho is not None:
        Q = mh * (fh.h(Thi + K) - fh.h(Tho + K))
        if mc is None:
            mc = Q / (fc.h(Tco + K) - fc.h(Tci + K))
        else:
            Tco = float(fc.T_from_h(fc.h(Tci + K) + Q / mc)) - K
    else:
        Q = mc * (fc.h(Tco + K) - fc.h(Tci + K))
        if mh is None:
            mh = Q / (fh.h(Thi + K) - fh.h(Tho + K))
        else:
            Tho = float(fh.T_from_h(fh.h(Thi + K) - Q / mh)) - K
    if Tho - Tci <= 0 or Thi - Tco <= 0:
        raise ValueError("Temperature cross at a terminal: counter-flow cannot meet this duty.")

    def mk(role, sd, fl, Tin, Tout, m):
        dflt = GAS_DEFAULTS if fl.phase == "gas" else LIQ_DEFAULTS
        vin = sd.get("nozzle_velocity_in_m_s", sd.get("nozzle_velocity_m_s", dflt["v_nozzle"]))
        vout = sd.get("nozzle_velocity_out_m_s", sd.get("nozzle_velocity_m_s", dflt["v_nozzle"]))
        return Stream(role, sd["name"], fl.phase, fl, float(Tin), float(Tout), float(m),
                      float(sd.get("P_kPa_abs", 101.325)) * 1e3, float(sd.get("fouling_m2K_W", 0.00035)),
                      float(sd.get("allowable_dp_kPa", dflt["dp_kPa"])) * 1e3,
                      tuple(sd.get("tube_velocity_m_s", dflt["v_tube"])), float(vin), float(vout),
                      {k: v for k, v in sd.items() if k.startswith("_")})

    d = Design(spec, mk("hot", h, fh, Thi, Tho, mh), mk("cold", c, fc, Tci, Tco, mc), float(Q), spec["tube_side"])
    if spec["mechanical"]["design_pressure_barg"] is None:
        pmax = max(d.hot.P, d.cold.P) - P_ATM
        spec["mechanical"]["design_pressure_barg"] = max(1.0, round(1.1 * pmax / 1e5 + 0.5, 1))
    return d


def override(design: Design, hot: dict | None = None, cold: dict | None = None) -> tuple:
    """Return (m_hot, T_hot_in, m_cold, T_cold_in) for an off-design rating case."""
    hot, cold = hot or {}, cold or {}
    mh = hot.get("flow_kg_h", design.hot.m * 3600) / 3600 * hot.get("flow_factor", 1.0)
    mc = cold.get("flow_kg_h", design.cold.m * 3600) / 3600 * cold.get("flow_factor", 1.0)
    return mh, hot.get("T_in", design.hot.T_in), mc, cold.get("T_in", design.cold.T_in)

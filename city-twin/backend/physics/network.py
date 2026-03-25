"""
City-scale 80-bus, 3-voltage-tier power network definition.

Voltage tiers
─────────────
  400 kV : 5 HV transmission buses   (Bus 1–5)
  132 kV : 20 sub-transmission buses  (Bus 6–25)
   33 kV : 55 distribution buses      (Bus 26–80)

Total generation capacity ≈ 2 430 MW
Total connected load      ≈ 1 800 MW
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Tuple

# ──────────────────────────────────────────────
# System-wide constants
# ──────────────────────────────────────────────
BASE_MVA: int = 100
SLACK_BUS: int = 1
NOMINAL_FREQ_HZ: float = 60.0

# ──────────────────────────────────────────────
# Frozen data-classes
# ──────────────────────────────────────────────

@dataclass(frozen=True, slots=True)
class Bus:
    id: int
    name: str
    bus_type: str          # "slack", "gen", "load", "junction"
    voltage_kv: float      # 400, 132, or 33
    p_gen_mw: float = 0.0
    p_load_mw: float = 0.0
    q_load_mvar: float = 0.0
    v_setpoint_pu: float = 1.0


@dataclass(frozen=True, slots=True)
class Line:
    from_bus: int
    to_bus: int
    r_pu: float
    x_pu: float
    b_pu: float            # total line-charging susceptance
    limit_mw: float
    voltage_kv: float


@dataclass(frozen=True, slots=True)
class Transformer:
    from_bus: int
    to_bus: int
    from_kv: float
    to_kv: float
    r_pu: float
    x_pu: float
    rating_mva: float
    tap_ratio: float = 1.0


# ──────────────────────────────────────────────
# Generator configuration
# ──────────────────────────────────────────────

GENERATORS_CONFIG: List[dict] = [
    {"bus_id":  1, "gen_type": "nuclear", "capacity_mw": 800, "inertia_M": 80.0, "damping_D": 2.0, "p_mech_mw": 600, "ramp_rate_mw_per_s":  0.5},
    {"bus_id":  2, "gen_type": "hydro",   "capacity_mw": 400, "inertia_M": 15.0, "damping_D": 1.5, "p_mech_mw": 300, "ramp_rate_mw_per_s": 10.0},
    {"bus_id":  3, "gen_type": "gas",     "capacity_mw": 350, "inertia_M":  8.0, "damping_D": 1.0, "p_mech_mw": 280, "ramp_rate_mw_per_s":  5.0},
    {"bus_id":  4, "gen_type": "wind",    "capacity_mw": 200, "inertia_M":  0.0, "damping_D": 0.5, "p_mech_mw": 140, "ramp_rate_mw_per_s": 50.0},
    {"bus_id":  5, "gen_type": "solar",   "capacity_mw": 150, "inertia_M":  0.0, "damping_D": 0.5, "p_mech_mw": 100, "ramp_rate_mw_per_s": 50.0},
    {"bus_id":  8, "gen_type": "gas",     "capacity_mw": 120, "inertia_M":  6.0, "damping_D": 1.0, "p_mech_mw":  90, "ramp_rate_mw_per_s":  5.0},
    {"bus_id": 10, "gen_type": "gas",     "capacity_mw": 100, "inertia_M":  5.0, "damping_D": 1.0, "p_mech_mw":  75, "ramp_rate_mw_per_s":  5.0},
    {"bus_id": 12, "gen_type": "hydro",   "capacity_mw":  80, "inertia_M": 10.0, "damping_D": 1.5, "p_mech_mw":  60, "ramp_rate_mw_per_s":  8.0},
    {"bus_id": 15, "gen_type": "wind",    "capacity_mw":  60, "inertia_M":  0.0, "damping_D": 0.5, "p_mech_mw":  40, "ramp_rate_mw_per_s": 50.0},
    {"bus_id": 18, "gen_type": "solar",   "capacity_mw":  40, "inertia_M":  0.0, "damping_D": 0.5, "p_mech_mw":  25, "ramp_rate_mw_per_s": 50.0},
    {"bus_id": 20, "gen_type": "gas",     "capacity_mw":  80, "inertia_M":  5.0, "damping_D": 1.0, "p_mech_mw":  60, "ramp_rate_mw_per_s":  5.0},
    {"bus_id": 22, "gen_type": "wind",    "capacity_mw":  50, "inertia_M":  0.0, "damping_D": 0.5, "p_mech_mw":  30, "ramp_rate_mw_per_s": 50.0},
]

_gen_bus_ids: set = {g["bus_id"] for g in GENERATORS_CONFIG}
_gen_p_mech: Dict[int, float] = {g["bus_id"]: g["p_mech_mw"] for g in GENERATORS_CONFIG}

# ──────────────────────────────────────────────
# Bus definitions  (80 buses)
# ──────────────────────────────────────────────

def _make_buses() -> Tuple[Bus, ...]:
    buses: list[Bus] = []

    # ── 400 kV buses (1–5) ──
    _hv_names = {
        1: "HV Nuclear Station",
        2: "HV Hydro Dam",
        3: "HV Gas CCGT Plant",
        4: "HV Wind Farm Agg",
        5: "HV Solar Farm Agg",
    }
    for bid in range(1, 6):
        btype = "slack" if bid == SLACK_BUS else "gen"
        buses.append(Bus(
            id=bid,
            name=_hv_names[bid],
            bus_type=btype,
            voltage_kv=400.0,
            p_gen_mw=_gen_p_mech.get(bid, 0.0),
            v_setpoint_pu=1.02,
        ))

    # ── 132 kV buses (6–25) ──
    _mv_load: Dict[int, float] = {
        6: 120.0, 7: 80.0, 9: 100.0, 11: 90.0,
        13: 70.0, 14: 60.0, 16: 50.0, 19: 110.0,
    }
    _mv_names: Dict[int, str] = {
        6:  "Industrial Zone North",
        7:  "Industrial Zone East",
        8:  "Gas Peaker 1 Station",
        9:  "Steel Works Sub",
        10: "Gas Peaker 2 Station",
        11: "Cement Factory Sub",
        12: "Small Hydro Station",
        13: "Port & Harbour Sub",
        14: "Rail Traction Sub",
        15: "Wind Farm 2 Sub",
        16: "Data Centre Cluster",
        17: "Airport Sub",
        18: "Solar Farm 2 Sub",
        19: "Chemical Plant Sub",
        20: "Gas Peaker 3 Station",
        21: "Water Treatment Sub",
        22: "Wind Farm 3 Sub",
        23: "University Campus Sub",
        24: "Hospital Complex Sub",
        25: "City Ring Sub North",
    }
    for bid in range(6, 26):
        is_gen = bid in _gen_bus_ids
        load = _mv_load.get(bid, 0.0)
        buses.append(Bus(
            id=bid,
            name=_mv_names.get(bid, f"132kV Bus {bid}"),
            bus_type="gen" if is_gen else ("load" if load > 0 else "junction"),
            voltage_kv=132.0,
            p_gen_mw=_gen_p_mech.get(bid, 0.0),
            p_load_mw=load,
            q_load_mvar=round(load * 0.15, 1),
            v_setpoint_pu=1.01 if is_gen else 1.0,
        ))

    # ── 33 kV buses (26–80) ──
    _dist_loads: Dict[int, Tuple[str, float]] = {
        26: ("Residential North-West",   30.0),
        27: ("Residential North-East",   35.0),
        28: ("Residential North",        28.0),
        29: ("Commercial CBD Core",      40.0),
        30: ("Commercial CBD East",      38.0),
        31: ("Commercial CBD West",      35.0),
        32: ("Residential South-West",   25.0),
        33: ("Residential South-East",   22.0),
        34: ("Residential South",        28.0),
        35: ("Shopping District",        36.0),
        36: ("Office Park Alpha",        32.0),
        37: ("Office Park Beta",         30.0),
        38: ("Residential Inner West",   20.0),
        39: ("Residential Inner East",   22.0),
        40: ("Light Industry West",      35.0),
        41: ("Light Industry East",      32.0),
        42: ("Suburb Greenfield",        16.0),
        43: ("Suburb Riverside",         18.0),
        44: ("Suburb Hilltop",           14.0),
        45: ("Suburb Lakeside",          15.0),
        46: ("Commercial Marina",        26.0),
        47: ("Tech Park South",          38.0),
        48: ("Tech Park North",          36.0),
        49: ("Residential Midtown",      24.0),
        50: ("Residential Uptown",       22.0),
        51: ("Government Quarter",       28.0),
        52: ("Transport Hub Central",    34.0),
        53: ("Transport Hub South",      24.0),
        54: ("Hospital District",        32.0),
        55: ("University District",      26.0),
        56: ("Suburb Old Town",          18.0),
        57: ("Suburb Newlands",          16.0),
        58: ("Residential West End",     20.0),
        59: ("Residential East End",     18.0),
        60: ("Commercial Waterfront",    28.0),
        61: ("Suburb Heights",           12.0),
        62: ("Suburb Valley",            14.0),
        63: ("Suburb Meadows",           12.0),
        64: ("Industrial Light South",   24.0),
        65: ("Commercial Strip North",   22.0),
        66: ("Residential Garden",       15.0),
        67: ("Residential Park",         14.0),
        68: ("Suburb Orchard",           10.0),
        69: ("Suburb Pineview",          11.0),
        70: ("Suburb Maplewood",          9.0),
        71: ("Junction 33kV-A",           0.0),
        72: ("Junction 33kV-B",           0.0),
        73: ("Junction 33kV-C",           0.0),
        74: ("Junction 33kV-D",           0.0),
        75: ("Junction 33kV-E",           0.0),
        76: ("Suburb Cedarwood",          8.0),
        77: ("Suburb Birchwood",          8.0),
        78: ("Suburb Ashfield",           9.0),
        79: ("Suburb Elmwood",           10.0),
        80: ("Suburb Willowdale",         8.0),
    }
    for bid in range(26, 81):
        name, load = _dist_loads.get(bid, (f"33kV Bus {bid}", 10.0))
        buses.append(Bus(
            id=bid,
            name=name,
            bus_type="load" if load > 0 else "junction",
            voltage_kv=33.0,
            p_load_mw=load,
            q_load_mvar=round(load * 0.10, 1),
        ))

    return tuple(buses)


# ──────────────────────────────────────────────
# Transmission line definitions
# ──────────────────────────────────────────────

def _make_lines() -> Tuple[Line, ...]:
    lines: list[Line] = []

    # ── 400 kV lines (ring + radials) ──
    _hv_lines = [
        (1, 2, 0.0015, 0.015, 0.030, 1000.0),
        (2, 3, 0.0020, 0.020, 0.025, 900.0),
        (3, 4, 0.0025, 0.025, 0.020, 800.0),
        (4, 5, 0.0030, 0.030, 0.018, 700.0),
        (5, 1, 0.0020, 0.022, 0.022, 850.0),
        (1, 3, 0.0035, 0.040, 0.015, 600.0),
        (2, 4, 0.0040, 0.045, 0.012, 550.0),
        (2, 5, 0.0050, 0.050, 0.010, 500.0),
    ]
    for fb, tb, r, x, b, lim in _hv_lines:
        lines.append(Line(fb, tb, r, x, b, lim, 400.0))

    # ── 132 kV lines ──
    _mv_lines = [
        ( 6,  7, 0.012, 0.060, 0.008, 250.0),
        ( 7,  8, 0.015, 0.080, 0.006, 200.0),
        ( 8,  9, 0.010, 0.055, 0.007, 280.0),
        ( 9, 10, 0.018, 0.090, 0.005, 180.0),
        (10, 11, 0.014, 0.070, 0.006, 220.0),
        (11, 12, 0.020, 0.100, 0.005, 160.0),
        (12, 13, 0.016, 0.085, 0.006, 200.0),
        (13, 14, 0.022, 0.110, 0.004, 150.0),
        (14, 15, 0.012, 0.065, 0.007, 240.0),
        (15, 16, 0.025, 0.130, 0.004, 140.0),
        (16, 17, 0.018, 0.095, 0.005, 180.0),
        (17, 18, 0.013, 0.070, 0.006, 220.0),
        (18, 19, 0.020, 0.105, 0.005, 170.0),
        (19, 20, 0.015, 0.080, 0.006, 200.0),
        (20, 21, 0.028, 0.140, 0.003, 120.0),
        (21, 22, 0.017, 0.088, 0.005, 190.0),
        (22, 23, 0.030, 0.150, 0.003, 110.0),
        (23, 24, 0.012, 0.062, 0.007, 260.0),
        (24, 25, 0.014, 0.074, 0.006, 230.0),
        (25,  6, 0.016, 0.082, 0.006, 210.0),
        ( 6,  9, 0.022, 0.115, 0.004, 160.0),
        ( 8, 11, 0.019, 0.098, 0.005, 180.0),
        (10, 14, 0.025, 0.125, 0.004, 140.0),
        (16, 20, 0.021, 0.108, 0.005, 170.0),
        (17, 25, 0.023, 0.120, 0.004, 150.0),
    ]
    for fb, tb, r, x, b, lim in _mv_lines:
        lines.append(Line(fb, tb, r, x, b, lim, 132.0))

    # ── 33 kV lines ──
    _lv_lines = [
        (26, 27, 0.035, 0.100, 0.002, 60.0),
        (27, 28, 0.040, 0.120, 0.002, 55.0),
        (28, 29, 0.030, 0.090, 0.002, 70.0),
        (29, 30, 0.025, 0.085, 0.003, 75.0),
        (30, 31, 0.028, 0.095, 0.002, 70.0),
        (31, 32, 0.042, 0.130, 0.002, 50.0),
        (32, 33, 0.045, 0.140, 0.001, 45.0),
        (33, 34, 0.038, 0.115, 0.002, 55.0),
        (34, 35, 0.032, 0.098, 0.002, 65.0),
        (35, 36, 0.030, 0.092, 0.002, 68.0),
        (36, 37, 0.033, 0.100, 0.002, 62.0),
        (37, 38, 0.048, 0.150, 0.001, 42.0),
        (38, 39, 0.040, 0.125, 0.002, 50.0),
        (39, 40, 0.035, 0.108, 0.002, 58.0),
        (40, 41, 0.028, 0.088, 0.003, 72.0),
        (41, 42, 0.050, 0.160, 0.001, 38.0),
        (42, 43, 0.055, 0.175, 0.001, 35.0),
        (43, 44, 0.058, 0.185, 0.001, 32.0),
        (44, 45, 0.052, 0.168, 0.001, 36.0),
        (45, 46, 0.045, 0.142, 0.001, 42.0),
        (46, 47, 0.030, 0.095, 0.002, 65.0),
        (47, 48, 0.025, 0.082, 0.003, 75.0),
        (48, 49, 0.038, 0.118, 0.002, 52.0),
        (49, 50, 0.042, 0.132, 0.002, 48.0),
        (50, 51, 0.035, 0.108, 0.002, 58.0),
        (51, 52, 0.028, 0.090, 0.003, 70.0),
        (52, 53, 0.032, 0.100, 0.002, 62.0),
        (53, 54, 0.038, 0.120, 0.002, 55.0),
        (54, 55, 0.030, 0.095, 0.002, 65.0),
        (55, 56, 0.045, 0.142, 0.001, 42.0),
        (56, 57, 0.050, 0.158, 0.001, 38.0),
        (57, 58, 0.048, 0.152, 0.001, 40.0),
        (58, 59, 0.042, 0.135, 0.002, 46.0),
        (59, 60, 0.035, 0.110, 0.002, 55.0),
        (60, 61, 0.055, 0.175, 0.001, 35.0),
        (61, 62, 0.058, 0.188, 0.001, 32.0),
        (62, 63, 0.060, 0.195, 0.001, 30.0),
        (63, 64, 0.040, 0.128, 0.002, 48.0),
        (64, 65, 0.035, 0.112, 0.002, 55.0),
        (65, 66, 0.042, 0.135, 0.002, 46.0),
        (66, 67, 0.048, 0.155, 0.001, 40.0),
        (67, 68, 0.055, 0.178, 0.001, 35.0),
        (68, 69, 0.058, 0.185, 0.001, 32.0),
        (69, 70, 0.060, 0.200, 0.001, 30.0),
        # Ties through junction buses
        (71, 26, 0.020, 0.080, 0.003, 80.0),
        (71, 35, 0.022, 0.085, 0.003, 78.0),
        (72, 40, 0.020, 0.080, 0.003, 80.0),
        (72, 47, 0.022, 0.088, 0.003, 76.0),
        (73, 51, 0.020, 0.082, 0.003, 78.0),
        (73, 60, 0.025, 0.092, 0.002, 72.0),
        (74, 64, 0.022, 0.085, 0.003, 76.0),
        (74, 70, 0.028, 0.098, 0.002, 68.0),
        (75, 76, 0.030, 0.100, 0.002, 65.0),
        (76, 77, 0.032, 0.105, 0.002, 62.0),
        (77, 78, 0.035, 0.112, 0.002, 58.0),
        (78, 79, 0.038, 0.118, 0.002, 54.0),
        (79, 80, 0.040, 0.125, 0.002, 50.0),
        (75, 80, 0.045, 0.140, 0.001, 45.0),
    ]
    for fb, tb, r, x, b, lim in _lv_lines:
        lines.append(Line(fb, tb, r, x, b, lim, 33.0))

    return tuple(lines)


# ──────────────────────────────────────────────
# Transformer definitions
# ──────────────────────────────────────────────

def _make_transformers() -> Tuple[Transformer, ...]:
    xfmrs: list[Transformer] = []

    # ── 400 / 132 kV (6 units) ──
    _hv_mv = [
        (1,  6, 0.002, 0.08, 500.0, 1.00),
        (1,  7, 0.002, 0.08, 450.0, 1.00),
        (2,  9, 0.003, 0.09, 400.0, 1.00),
        (3, 14, 0.003, 0.09, 400.0, 1.02),
        (4, 17, 0.003, 0.10, 350.0, 1.00),
        (5, 25, 0.003, 0.10, 300.0, 0.98),
    ]
    for fb, tb, r, x, mva, tap in _hv_mv:
        xfmrs.append(Transformer(fb, tb, 400.0, 132.0, r, x, mva, tap))

    # ── 132 / 33 kV (15 units) ──
    _mv_lv = [
        ( 6, 26, 0.005, 0.12, 120.0, 1.00),
        ( 7, 28, 0.005, 0.12, 100.0, 1.00),
        ( 9, 29, 0.006, 0.13, 110.0, 1.02),
        (11, 32, 0.006, 0.14, 100.0, 1.00),
        (13, 38, 0.006, 0.13,  90.0, 1.00),
        (14, 40, 0.005, 0.12, 100.0, 1.00),
        (16, 47, 0.006, 0.14,  80.0, 1.02),
        (17, 49, 0.005, 0.12,  90.0, 1.00),
        (19, 52, 0.006, 0.13, 100.0, 1.00),
        (21, 55, 0.006, 0.14,  80.0, 1.00),
        (23, 60, 0.005, 0.12,  90.0, 1.02),
        (24, 64, 0.006, 0.13,  80.0, 1.00),
        (25, 71, 0.005, 0.12, 100.0, 1.00),
        ( 8, 72, 0.006, 0.13,  90.0, 1.00),
        (20, 75, 0.006, 0.14,  80.0, 1.00),
    ]
    for fb, tb, r, x, mva, tap in _mv_lv:
        xfmrs.append(Transformer(fb, tb, 132.0, 33.0, r, x, mva, tap))

    return tuple(xfmrs)


# ──────────────────────────────────────────────
# Materialised tuples
# ──────────────────────────────────────────────
BUSES: Tuple[Bus, ...] = _make_buses()
LINES: Tuple[Line, ...] = _make_lines()
TRANSFORMERS: Tuple[Transformer, ...] = _make_transformers()

NUM_BUSES: int = len(BUSES)
BUS_INDEX: Dict[int, int] = {bus.id: idx for idx, bus in enumerate(BUSES)}

# ──────────────────────────────────────────────
# Quick sanity helpers (run with `python -m backend.physics.network`)
# ──────────────────────────────────────────────

def _summary() -> None:
    total_gen = sum(b.p_gen_mw for b in BUSES)
    total_load = sum(b.p_load_mw for b in BUSES)
    print(f"Buses: {NUM_BUSES}  (400kV: 5, 132kV: 20, 33kV: 55)")
    print(f"Lines: {len(LINES)}   Transformers: {len(TRANSFORMERS)}")
    print(f"Total generation dispatch: {total_gen:.0f} MW")
    print(f"Total load:                {total_load:.0f} MW")
    print(f"Generation headroom:       {total_gen - total_load:.0f} MW")


if __name__ == "__main__":
    _summary()

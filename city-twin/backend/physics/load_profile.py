"""Real recorded demand profile for ambient load variation.

A normalized one-week hourly load shape (168 points, mean = 1.0) taken from the
**NREL RTS-GMLC** reliability test-system dataset (total of its three regions,
a representative July week). This is a *real recorded* demand curve — it carries
the genuine daily structure (overnight valley ≈ 0.66, evening peak ≈ 1.38) and
weekday/weekend variation, not a synthetic sinusoid.

The simulator maps its (fast) sim-time onto this profile so the operator watches
a realistic load cycle play out in minutes, and scales the profile's amplitude
to the 80-bus model's capacity so peaks stress the network without collapsing it.

Source: GridMod/RTS-GMLC, RTS_Data/timeseries_data_files/Load (ODbL/BSD).
"""

from __future__ import annotations

# Normalized hourly demand (mean = 1.0), one representative week (168 h).
WEEKLY_PROFILE: tuple[float, ...] = (
    0.7142, 0.6805, 0.658, 0.6571, 0.6662, 0.6975, 0.7668, 0.8496, 0.9275, 0.9944,
    1.06, 1.1202, 1.1746, 1.2188, 1.2496, 1.26, 1.242, 1.1856, 1.1203, 1.091,
    1.0346, 0.9403, 0.849, 0.7748, 0.7274, 0.6882, 0.6668, 0.6627, 0.6695, 0.7069,
    0.7822, 0.8647, 0.9421, 1.0138, 1.0812, 1.1663, 1.2159, 1.2561, 1.2867, 1.2967,
    1.2567, 1.2042, 1.1431, 1.1131, 1.0564, 0.9619, 0.8647, 0.7968, 0.7439, 0.7034,
    0.6832, 0.679, 0.6865, 0.717, 0.7847, 0.8734, 0.9459, 1.0165, 1.0804, 1.1445,
    1.1981, 1.2391, 1.2754, 1.2886, 1.27, 1.2249, 1.1619, 1.1279, 1.0735, 0.9812,
    0.888, 0.8109, 0.7599, 0.7222, 0.6991, 0.6954, 0.7007, 0.7307, 0.8083, 0.8922,
    0.973, 1.0498, 1.1286, 1.1945, 1.2507, 1.3008, 1.3333, 1.3444, 1.3281, 1.2734,
    1.2148, 1.1801, 1.1192, 1.0252, 0.926, 0.8471, 0.7911, 0.7507, 0.7289, 0.722,
    0.7274, 0.7524, 0.8222, 0.9077, 0.9904, 1.0801, 1.1545, 1.2272, 1.29, 1.3429,
    1.3753, 1.3841, 1.3647, 1.309, 1.2414, 1.2013, 1.1405, 1.0458, 0.9553, 0.8758,
    0.822, 0.7848, 0.7548, 0.7357, 0.7201, 0.7153, 0.7776, 0.8742, 0.9761, 1.0711,
    1.1498, 1.2241, 1.2747, 1.3147, 1.323, 1.3137, 1.2849, 1.2347, 1.1844, 1.156,
    1.1057, 1.0223, 0.9385, 0.8645, 0.8073, 0.7616, 0.7308, 0.7088, 0.69, 0.6835,
    0.7335, 0.818, 0.9079, 0.9944, 1.0733, 1.1404, 1.188, 1.2332, 1.2667, 1.2705,
    1.252, 1.2127, 1.1679, 1.1513, 1.1069, 1.0273, 0.9424, 0.8758,
)
_N = len(WEEKLY_PROFILE)


def load_multiplier(sim_time_s: float, *, day_seconds: float = 180.0,
                    amplitude: float = 0.5) -> float:
    """Demand multiplier at ``sim_time_s`` from the real profile.

    One profile-day plays out over ``day_seconds`` of sim time (default 3 min),
    so a full week cycles in ~21 min. ``amplitude`` scales the profile's real
    deviation from its mean down to a level the 80-bus model can carry
    (0.5 → roughly ±19%): the *shape* is real, the *magnitude* fits the network.
    """
    hours_per_sec = 24.0 / day_seconds
    pos = (sim_time_s * hours_per_sec) % _N
    i = int(pos)
    frac = pos - i
    raw = WEEKLY_PROFILE[i] * (1.0 - frac) + WEEKLY_PROFILE[(i + 1) % _N] * frac
    return 1.0 + amplitude * (raw - 1.0)

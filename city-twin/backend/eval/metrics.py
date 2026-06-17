"""Grid-stability metrics for scoring a rollout.

A rollout is summarised step-by-step into :class:`StepSummary` rows; those are
reduced into a :class:`RolloutMetrics` with a single composite ``cost`` (lower
is better) so controllers can be ranked. The cost weights encode the operating
doctrine: violations and instability dominate; shed load is penalised but
preferred to collapse.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from physics.network import NOMINAL_FREQ_HZ

# Composite-cost weights.
W_UNSERVED = 1.0          # per MW·s of load shed
W_FREQ = 200.0            # per Hz·s of integrated frequency deviation
W_VIOLATION = 50.0        # per second spent with any limit violated
W_NOT_RECOVERED = 5000.0  # flat penalty if the grid never returns to secure


class StepSummary(BaseModel):
    sim_time_s: float
    frequency_hz: float
    total_generation_mw: float
    total_load_mw: float
    max_line_loading_pct: float
    max_voltage_dev_pu: float
    n_violations: int
    shed_mw_cumulative: float
    secure: bool


class RolloutMetrics(BaseModel):
    controller: str
    scenario_id: str
    duration_s: float
    n_steps: int

    load_shed_mw: float = 0.0              # final cumulative MW shed by the controller
    integrated_unserved_mwh: float = 0.0   # ∫ shed_mw dt, in MW·h
    max_freq_dev_hz: float = 0.0
    integrated_freq_dev_hz_s: float = 0.0
    max_line_loading_pct: float = 0.0
    worst_voltage_dev_pu: float = 0.0
    violation_seconds: float = 0.0
    violation_step_fraction: float = 0.0
    n_actions: int = 0
    final_secure: bool = True
    time_to_recover_s: float | None = None  # from first post-fault violation to lasting recovery

    cost: float = 0.0
    notes: list[str] = Field(default_factory=list)


def compute_metrics(
    controller: str,
    scenario_id: str,
    steps: list[StepSummary],
    dt_s: float,
    n_actions: int,
    fault_start_s: float,
) -> RolloutMetrics:
    if not steps:
        return RolloutMetrics(controller=controller, scenario_id=scenario_id,
                              duration_s=0.0, n_steps=0)

    m = RolloutMetrics(
        controller=controller, scenario_id=scenario_id,
        duration_s=round(steps[-1].sim_time_s - steps[0].sim_time_s, 2),
        n_steps=len(steps), n_actions=n_actions,
    )

    integ_unserved = 0.0
    integ_freq = 0.0
    violation_secs = 0.0
    violation_steps = 0

    for s in steps:
        fdev = abs(s.frequency_hz - NOMINAL_FREQ_HZ)
        m.max_freq_dev_hz = max(m.max_freq_dev_hz, fdev)
        m.max_line_loading_pct = max(m.max_line_loading_pct, s.max_line_loading_pct)
        m.worst_voltage_dev_pu = max(m.worst_voltage_dev_pu, s.max_voltage_dev_pu)
        integ_freq += fdev * dt_s
        integ_unserved += s.shed_mw_cumulative * dt_s
        if not s.secure:
            violation_secs += dt_s
            violation_steps += 1

    m.load_shed_mw = round(steps[-1].shed_mw_cumulative, 2)
    m.integrated_unserved_mwh = round(integ_unserved / 3600.0, 5)
    m.max_freq_dev_hz = round(m.max_freq_dev_hz, 4)
    m.integrated_freq_dev_hz_s = round(integ_freq, 4)
    m.max_line_loading_pct = round(m.max_line_loading_pct, 1)
    m.worst_voltage_dev_pu = round(m.worst_voltage_dev_pu, 4)
    m.violation_seconds = round(violation_secs, 2)
    m.violation_step_fraction = round(violation_steps / len(steps), 4)
    m.final_secure = steps[-1].secure
    m.time_to_recover_s = _time_to_recover(steps, fault_start_s)

    # Composite cost. integ_unserved is already MW·s; integ_freq is Hz·s.
    cost = (
        W_UNSERVED * integ_unserved
        + W_FREQ * integ_freq
        + W_VIOLATION * violation_secs
    )
    if not m.final_secure:
        cost += W_NOT_RECOVERED
    m.cost = round(cost, 2)
    return m


def _time_to_recover(steps: list[StepSummary], fault_start_s: float) -> float | None:
    """Seconds from the first post-fault violation to the start of a lasting
    secure stretch that holds through the end of the rollout. ``None`` if the
    grid never had a violation, or never recovered."""
    first_violation_t: float | None = None
    for s in steps:
        if s.sim_time_s >= fault_start_s and not s.secure:
            first_violation_t = s.sim_time_s
            break
    if first_violation_t is None:
        return None  # never went insecure → nothing to recover from

    # Find the earliest time after which every step is secure.
    recovery_t: float | None = None
    secure_since: float | None = None
    for s in steps:
        if s.sim_time_s < first_violation_t:
            continue
        if s.secure:
            if secure_since is None:
                secure_since = s.sim_time_s
        else:
            secure_since = None
    recovery_t = secure_since
    if recovery_t is None:
        return None  # never recovered
    return round(recovery_t - first_violation_t, 2)

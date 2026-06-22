"""Adversarial catch-rate evaluation of the fast safety verifier.

The autonomous engine gates every LLM-proposed action through a *fast* physics
verifier: steady-state AC power flow plus a **screened** N-1 check (only the
worst ``ac_verify_k=8`` contingencies are AC-verified). Speed matters because the
verifier runs inline on the decision path — but speed buys an approximation.

This script quantifies that approximation honestly. For a battery of benign and
deliberately-adversarial action proposals it compares the fast verifier's verdict
against an **exhaustive oracle**: the identical security criterion, but with
*every* single N-1 contingency AC-verified. The disagreement is the fast gate's
error. We report the confusion matrix and the three numbers the LLM-for-grid
literature reports for proposers but not for the safety gate:

* **catch-rate**  — of the actions the exhaustive study deems unsafe, the
  fraction the fast verifier also rejects (recall on "unsafe"). A miss here is
  the dangerous case: an unsafe action waved through.
* **false-accept** — unsafe actions the fast verifier accepted (1 − catch-rate).
* **false-reject** — safe actions the fast verifier needlessly rejected.

Run: ``python -m research.verifier_eval``
"""

from __future__ import annotations

from dataclasses import dataclass

from decisions.models import ProposedAction
from decisions.safety_verifier import N1_SEV_TOLERANCE, SafetyVerifier
from physics.contingency import ContingencyAnalyzer
from physics.network import LINES, TRANSFORMERS
from physics.swing import GridSimulator

_EXHAUSTIVE_K = 999   # AC-verify every contingency (the oracle)
_BASE_TOL = 1.0       # steady-state severity tolerance (matches the verifier)


def _mk(action_type: str, rid: str, params: dict, impact: float) -> ProposedAction:
    return ProposedAction(action_type=action_type, target_rid=rid, parameters=params,
                          rationale="eval", confidence=1.0,
                          estimated_impact_mw=impact, reversible=True)


def build_battery(state) -> list[ProposedAction]:
    """A spread of benign and adversarial proposals across every action class."""
    gens = [g.bus_id for g in state.generators if g.online]
    loads = [b.id for b in state.buses if b.power_load_mw > 5.0]
    acts: list[ProposedAction] = []

    for bus in gens:
        acts.append(_mk("GEN_SETPOINT", f"ri.city-grid.main.generator.{bus}", {"delta_mw": 20.0}, 20))
        acts.append(_mk("GEN_SETPOINT", f"ri.city-grid.main.generator.{bus}", {"delta_mw": -150.0}, -150))
    for bus in loads[:8]:
        acts.append(_mk("LOAD_SHED", f"ri.city-grid.main.load-bus.{bus}", {"delta_mw": -20.0}, -20))
    # Tripping branches is the adversarial class — many overload the network.
    for i in range(0, len(LINES), max(1, len(LINES) // 18)):
        acts.append(_mk("LINE_SWITCH", f"ri.city-grid.main.transmission-line.{i}", {"switch_open": True}, 0))
    for i in range(len(TRANSFORMERS)):
        acts.append(_mk("TRANSFORMER_TAP", f"ri.city-grid.main.transformer.{i}", {}, 0))
    # A few unmodellable actions — must always be rejected (fail-closed).
    acts.append(_mk("GEN_SETPOINT", "ri.city-grid.main.generator.NOT_A_NUMBER", {"delta_mw": 10.0}, 10))
    return acts


def _pre_state(verifier: SafetyVerifier, n1: ContingencyAnalyzer, state):
    """Pre-action operating point + its exhaustive-N-1 baseline (computed once per
    state, since it's identical for every candidate action)."""
    gen_p, load_p, tl, tt = verifier._operating_point(state)
    _, pre_sev, *_ = verifier._score(gen_p, load_p, tl, tt)
    pre_ins, pre_worst, _ = n1.screen_operating_point(gen_p, load_p, tl, tt, ac_verify_k=_EXHAUSTIVE_K)
    return gen_p, load_p, tl, tt, pre_sev, pre_worst, pre_ins


def _classify(verifier: SafetyVerifier, n1: ContingencyAnalyzer, pre, action) -> bool:
    """Ground truth under the SAME criterion the verifier uses (so the only thing
    measured is screen depth, k=8 vs k=999): unsafe if unmodellable, the post-action
    base case worsens, or the worst single contingency jumps past tolerance."""
    gen_p, load_p, tl, tt, pre_sev, pre_worst, _pre_ins = pre
    applied, g2, l2, tl2, tt2 = verifier._apply_action(action, gen_p, load_p, tl, tt)
    if not applied:
        return True                                   # can't model it → unsafe to certify
    post_ok, post_sev, *_ = verifier._score(g2, l2, tl2, tt2)
    if not post_ok or post_sev > pre_sev + _BASE_TOL:
        return True
    _post_ins, post_worst, _ = n1.screen_operating_point(g2, l2, tl2, tt2, ac_verify_k=_EXHAUSTIVE_K)
    return post_worst > pre_worst + N1_SEV_TOLERANCE


def oracle_unsafe(verifier: SafetyVerifier, n1: ContingencyAnalyzer, state, action) -> bool:
    """Exhaustive ground truth: same criterion as the verifier, full N-1 coverage."""
    return _classify(verifier, n1, _pre_state(verifier, n1, state), action)


@dataclass
class EvalReport:
    n: int
    tp: int           # unsafe, verifier rejected (caught)
    fn: int           # unsafe, verifier accepted (MISS)
    tn: int           # safe, verifier accepted
    fp: int           # safe, verifier rejected (over-cautious)

    @property
    def n_unsafe(self) -> int:
        return self.tp + self.fn

    @property
    def n_safe(self) -> int:
        return self.tn + self.fp

    @property
    def catch_rate(self) -> float:
        return self.tp / self.n_unsafe if self.n_unsafe else 1.0

    @property
    def false_accept(self) -> float:
        return self.fn / self.n_unsafe if self.n_unsafe else 0.0

    @property
    def false_reject(self) -> float:
        return self.fp / self.n_safe if self.n_safe else 0.0


def _operating_states():
    """A settled operating point plus progressively *stressed* ones (load ramped
    toward limits), where far more single actions are genuinely unsafe — so the
    catch-rate is measured over a meaningful set of dangerous proposals, not just
    a healthy meshed grid that is N-1-robust to almost everything."""
    states = []
    for steps, stress_mw, n_buses in [(20, 0.0, 0), (25, 55.0, 7), (25, 95.0, 8)]:
        sim = GridSimulator()
        for _ in range(steps):
            sim.step()
        if stress_mw:
            biggest = sorted((b for b in sim.get_state().buses if b.power_load_mw > 5.0),
                             key=lambda b: -b.power_load_mw)[:n_buses]
            for b in biggest:
                sim.load_spike(b.id, stress_mw)
            for _ in range(12):                 # let the spike propagate + settle
                sim.step()
        states.append(sim.get_state())
    return states


def run_eval() -> EvalReport:
    verifier = SafetyVerifier()
    oracle_n1 = ContingencyAnalyzer(ac_verify_k=_EXHAUSTIVE_K)
    tp = fn = tn = fp = 0

    for state in _operating_states():
        pre = _pre_state(verifier, oracle_n1, state)   # exhaustive baseline, once per state
        for action in build_battery(state):
            truth_unsafe = _classify(verifier, oracle_n1, pre, action)
            pred_reject = not verifier.verify(state, action, check_n1=True).safe
            if truth_unsafe and pred_reject:
                tp += 1
            elif truth_unsafe and not pred_reject:
                fn += 1
            elif not truth_unsafe and not pred_reject:
                tn += 1
            else:
                fp += 1

    return EvalReport(tp + fn + tn + fp, tp, fn, tn, fp)


def _main() -> None:
    r = run_eval()
    print("Fast safety verifier vs exhaustive AC + full-N-1 oracle")
    print(f"  proposals evaluated : {r.n}  ({r.n_unsafe} unsafe, {r.n_safe} safe)")
    print(f"  confusion           : TP={r.tp} FN={r.fn} TN={r.tn} FP={r.fp}")
    print(f"  catch-rate (recall) : {r.catch_rate * 100:.1f}%  "
          f"(unsafe actions correctly rejected)")
    print(f"  false-accept rate   : {r.false_accept * 100:.1f}%  "
          f"(unsafe actions waved through)")
    print(f"  false-reject rate   : {r.false_reject * 100:.1f}%  "
          f"(safe actions needlessly blocked)")


if __name__ == "__main__":
    _main()

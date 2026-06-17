"""Close the loop: does the learned world model support *control*?

Trains a security world model on the trajectory dataset, wraps it as a
:class:`LearnedController` (counterfactual planner), and runs it head-to-head
against the do-nothing and rule-based baselines in the real simulator — scored
on the same grid-stability cost as the M2 harness. This is the final link of
the GridWorld arc: state → action → prediction → **control** → evaluation.

Usage (from city-twin/backend, needs torch):
    python -m eval.generate_dataset --out data/gw --seeds 8
    python -m research.control_eval --data data/gw
"""

from __future__ import annotations

import argparse

from eval.controllers import DoNothingController, GreedyRuleController
from eval.harness import format_table
from eval.runner import run_scenario
from eval.scenario import Scenario, scenario_library


def compare_controllers(bundle, scenarios: list[Scenario]) -> dict[str, list]:
    """Run do_nothing / greedy / learned on each scenario; metrics sorted by cost.

    ``bundle`` is a trained GraphModelBundle; importing it (and torch) is the
    caller's responsibility so this module stays import-safe without torch.
    """
    from .controller import LearnedController

    controllers = [
        DoNothingController(),
        GreedyRuleController(),
        LearnedController(bundle, candidate_source=GreedyRuleController()),
    ]
    results: dict[str, list] = {}
    for scen in scenarios:
        metrics = [run_scenario(scen, c).metrics for c in controllers]
        metrics.sort(key=lambda m: m.cost)
        results[scen.id] = metrics
    return results


def _summary(results: dict[str, list]) -> dict[str, dict]:
    agg: dict[str, dict] = {}
    for metrics in results.values():
        best = min(metrics, key=lambda m: m.cost).controller
        for m in metrics:
            a = agg.setdefault(m.controller, {"total_cost": 0.0, "wins": 0, "n": 0})
            a["total_cost"] += m.cost
            a["n"] += 1
            if m.controller == best:
                a["wins"] += 1
    for a in agg.values():
        a["mean_cost"] = round(a["total_cost"] / max(a["n"], 1), 1)
    return agg


def main() -> None:
    ap = argparse.ArgumentParser(description="Learned-controller vs baselines in the simulator")
    ap.add_argument("--data", required=True, help="trajectory dataset for training the world model")
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()

    from .controller import fit_graph_bundle
    from .dataset import load_dataset, split_by_trajectory

    raw = load_dataset(args.data)
    train, _, _ = split_by_trajectory(raw, seed=args.seed)
    print(f"Training world model on {len(train)} samples...")
    bundle = fit_graph_bundle(train, seed=args.seed)

    scenarios = list(scenario_library().values())
    results = compare_controllers(bundle, scenarios)

    for sid, metrics in results.items():
        print(f"\n=== {sid} ===")
        print(format_table(metrics))
        print(f"  winner: {metrics[0].controller} (cost {metrics[0].cost:.1f})")

    print("\n=== summary (mean cost / wins across scenarios) ===")
    for name, a in sorted(_summary(results).items(), key=lambda kv: kv[1]["mean_cost"]):
        print(f"  {name:<14} mean_cost={a['mean_cost']:>8}  wins={a['wins']}/{a['n']}")


if __name__ == "__main__":
    main()

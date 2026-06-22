"""Closed-loop control comparison: learned-dynamics planner vs baselines.

Trains the action-conditioned dynamics model on the dataset, then runs
do-nothing, greedy-rule, and the model-based ``learned_dynamics`` controller
through every scenario in the **real** simulator (with protection enabled, so an
unaddressed overload cascades) and prints the stability cost for each. This is
the honest, in-simulator test of whether planning over the learned model helps.

Usage (from city-twin/backend):
    python -m research.dynamics_control_eval --data data/gw_dyn
"""

from __future__ import annotations

import argparse

from eval.controllers import DoNothingController, GreedyRuleController
from eval.runner import run_scenario
from eval.scenario import scenario_library

from .dynamics import (
    PhysicsFlowDecoder,
    fit_dynamics,
    load_dynamics_dataset,
    split_by_trajectory,
)
from .dynamics_controller import LearnedDynamicsController


def main() -> None:
    ap = argparse.ArgumentParser(description="Closed-loop learned-dynamics control eval")
    ap.add_argument("--data", default="data/gw_dyn")
    ap.add_argument("--epochs", type=int, default=30)
    ap.add_argument("--horizon", type=int, default=10,
                    help="prediction horizon the planner looks ahead (steps; 0.1s each)")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--flow-loss-weight", type=float, default=3.0,
                    help="physics flow loss weight when training (0 = off)")
    ap.add_argument("--protection", action="store_true",
                    help="enable inverse-time protection so overloads cascade "
                         "(slower: collapsed grids hit the full solver-fallback ladder)")
    args = ap.parse_args()

    s = load_dynamics_dataset(args.data, horizon=args.horizon)
    train, _ = split_by_trajectory(s, seed=args.seed)
    print(f"Training dynamics model on {len(train)} transitions "
          f"(flow_loss_weight={args.flow_loss_weight})...")
    bundle = fit_dynamics(train, epochs=args.epochs, seed=args.seed,
                          flow_loss_weight=args.flow_loss_weight)
    decoder = PhysicsFlowDecoder().fit(train)

    library = scenario_library()
    controllers = [
        DoNothingController(),
        GreedyRuleController(),
        LearnedDynamicsController(bundle),                          # free-form edge head
        LearnedDynamicsController(bundle, flow_decoder=decoder),    # physics flow head
    ]

    print(f"\n{'scenario':<26}" + "".join(f"{c.name:>18}" for c in controllers))
    print("-" * (26 + 18 * len(controllers)))
    totals = {c.name: 0.0 for c in controllers}
    for scen in library.values():
        row = f"{scen.id:<26}"
        for c in controllers:
            r = run_scenario(scen, c, protection_enabled=args.protection)
            totals[c.name] += r.metrics.cost
            row += f"{r.metrics.cost:>18.1f}"
        print(row)
    print("-" * (26 + 18 * len(controllers)))
    print(f"{'TOTAL':<26}" + "".join(f"{totals[c.name]:>18.1f}" for c in controllers))


if __name__ == "__main__":
    main()

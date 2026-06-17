"""CLI: generate a GridWorld trajectory dataset.

Runs scenarios under baseline controllers, recording full graph state/action/
outcome trajectories to compressed .npz + JSON sidecars — the training corpus
for a learned grid world model.

Usage (from city-twin/backend):
    python -m eval.generate_dataset --out data/gridworld_v1
    python -m eval.generate_dataset --out data/gridworld_v1 --seeds 5
"""

from __future__ import annotations

import argparse
import os

from .controllers import DoNothingController, GreedyRuleController
from .runner import run_scenario
from .scenario import scenario_library


def main() -> None:
    ap = argparse.ArgumentParser(description="Generate GridWorld trajectory dataset")
    ap.add_argument("--out", default="data/gridworld_v1", help="output directory")
    ap.add_argument("--seeds", type=int, default=1,
                    help="number of seed variations per scenario")
    args = ap.parse_args()

    controllers = [DoNothingController(), GreedyRuleController()]
    library = scenario_library()
    out_dir = os.path.abspath(args.out)

    n_written = 0
    total_steps = 0
    for scenario in library.values():
        for s in range(args.seeds):
            scen = scenario.model_copy(update={"seed": scenario.seed + s})
            for controller in controllers:
                result = run_scenario(scen, controller, record_trajectory=True)
                rec = result.trajectory
                assert rec is not None
                labels = {
                    "final_secure": result.metrics.final_secure,
                    "load_shed_mw": result.metrics.load_shed_mw,
                    "max_freq_dev_hz": result.metrics.max_freq_dev_hz,
                    "time_to_recover_s": result.metrics.time_to_recover_s,
                    "cost": result.metrics.cost,
                    "family": scen.family,
                }
                path = rec.save(out_dir, labels=labels)
                n_written += 1
                total_steps += rec.n_steps
                print(f"  wrote {os.path.basename(path)}  ({rec.n_steps} steps)")

    print(f"\nDone. {n_written} trajectories, {total_steps} total steps -> {out_dir}")


if __name__ == "__main__":
    main()

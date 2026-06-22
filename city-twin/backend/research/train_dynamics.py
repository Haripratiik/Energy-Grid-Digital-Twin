"""CLI: train + honestly benchmark the action-conditioned dynamics world model.

Reports next-state prediction error (MAE) against the **persistence** baseline
(predict zero change) and an **action-ablation** (zero the action at inference),
both overall and on action-bearing steps. The ablation is the causal test that
the model actually uses the action.

Usage (from city-twin/backend):
    python -m research.train_dynamics --data data/gw_dyn
    python -m research.train_dynamics --data data/gw_dyn --holdout-family trafo_trip
"""

from __future__ import annotations

import argparse

from .dynamics import (
    PhysicsFlowDecoder,
    bootstrap_skill_ci,
    evaluate,
    evaluate_flow_decode,
    fit_dynamics,
    load_dynamics_dataset,
    split_by_family,
    split_by_trajectory,
)


def _skill(persist: float, learned: float) -> float:
    return (1.0 - learned / persist) * 100.0 if persist > 0 else 0.0


def _print_block(title: str, b: dict | None) -> None:
    if b is None:
        print(f"  {title}: (no samples)")
        return
    print(f"  {title} (n={b['n']}):")
    print(f"    Vm   MAE: persist {b['vm_persist']:.5f} | learned {b['vm_learned']:.5f} "
          f"| no-action {b['vm_ablated']:.5f}")
    print(f"    Va   MAE: persist {b['va_persist']:.5f} | learned {b['va_learned']:.5f}")
    print(f"    load MAE: persist {b['load_persist']:.5f} | learned {b['load_learned']:.5f} "
          f"| no-action {b['load_ablated']:.5f}")
    print(f"    skill vs persistence:  Vm {_skill(b['vm_persist'], b['vm_learned']):+.0f}%  "
          f"Va {_skill(b['va_persist'], b['va_learned']):+.0f}%  "
          f"load {_skill(b['load_persist'], b['load_learned']):+.0f}%")


def main() -> None:
    ap = argparse.ArgumentParser(description="Train the action-conditioned dynamics model")
    ap.add_argument("--data", default="data/gw_dyn")
    ap.add_argument("--horizon", type=int, default=1)
    ap.add_argument("--epochs", type=int, default=40)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--holdout-family", default=None,
                    help="hold out one fault family for test (generalization test)")
    ap.add_argument("--bootstrap", action="store_true",
                    help="trajectory-bootstrap 90%% CI on skill (significance check)")
    ap.add_argument("--flow-decode", action="store_true",
                    help="physics flow head: decode line loading from predicted angles")
    ap.add_argument("--flow-loss-weight", type=float, default=0.0,
                    help="weight on the differentiable physics flow loss during training "
                         "(0 = off; trains angles to decode to correct loadings)")
    args = ap.parse_args()

    s = load_dynamics_dataset(args.data, horizon=args.horizon)
    n_traj = len(set(s.traj_id.tolist()))
    print(f"Loaded {len(s)} transitions ({int(s.acted.sum())} action-bearing, "
          f"{100 * s.acted.mean():.1f}%) from {n_traj} trajectories, horizon={args.horizon}")

    if args.holdout_family:
        train, test = split_by_family(s, args.holdout_family)
        split_desc = f"held-out family '{args.holdout_family}'"
    else:
        train, test = split_by_trajectory(s, seed=args.seed)
        split_desc = "held-out trajectories"
    print(f"Train {len(train)} / Test {len(test)}  ({split_desc})\n")

    bundle = fit_dynamics(train, epochs=args.epochs, seed=args.seed,
                          flow_loss_weight=args.flow_loss_weight)
    res = evaluate(bundle, test)
    print("Next-state prediction MAE (lower is better; persistence = predict no change):")
    _print_block("ALL test steps", res["overall"])
    _print_block("DISTURBED steps (violation / off-nominal freq)", res["disturbed"])
    _print_block("ACTION-bearing steps", res["acted"])

    if args.bootstrap:
        ci = bootstrap_skill_ci(bundle, test, seed=args.seed)
        print("\nTrajectory-bootstrap skill% vs persistence  [p5, median, p95] "
              "(CI entirely > 0 ⇒ significant):")
        for slice_name in ("overall", "disturbed"):
            c = ci[slice_name]
            print(f"  {slice_name}:  Vm {c['vm']}   Va {c['va']}   load {c['load']}")

    if args.flow_decode:
        decoder = PhysicsFlowDecoder().fit(train)
        fd = evaluate_flow_decode(bundle, decoder, test)
        print(f"\nPhysics flow head — line-LOADING delta MAE on {fd['n_line_edges']} "
              "line edges (skill vs persistence):")
        print(f"  persistence (predict no change): {fd['persist']:.5f}")
        print(f"  free-form edge head:             {fd['learned_head']:.5f}  "
              f"({fd['skill_learned']:+.0f}%)")
        print(f"  PHYSICS decode (pred angles):    {fd['decoded']:.5f}  "
              f"({fd['skill_decoded']:+.0f}%)   <- deployable")
        print(f"  physics decode (TRUE angles):    {fd['decoded_true_angles']:.5f}  "
              f"({fd['skill_decoded_true']:+.0f}%)   <- upper bound (DC validity)")


if __name__ == "__main__":
    main()

"""Train and benchmark security-prediction models on a GridWorld dataset.

Compares, on a held-out split, four approaches at predicting whether the grid
is secure ``horizon`` steps ahead:

    persistence  — assume current security persists (no learning)
    logistic     — logistic regression on flattened features (numpy)
    mlp          — neural net on flattened features (topology-blind)
    gnn          — action-conditioned message-passing graph world model

Usage (from city-twin/backend):
    python -m eval.generate_dataset --out data/gw --seeds 8   # make data first
    python -m research.train --data data/gw
    python -m research.train --data data/gw --holdout-family trafo_trip
"""

from __future__ import annotations

import argparse

from .baselines import LogisticRegression, persistence_scores
from .dataset import Standardizer, load_dataset, split_by_family, split_by_trajectory
from .metrics import ClsMetrics, evaluate


def run(data_dir: str, horizon: int, holdout_family: str | None, seed: int) -> dict[str, ClsMetrics]:
    raw = load_dataset(data_dir, horizon=horizon)

    if holdout_family:
        train, test = split_by_family(raw, holdout_family)
        val = test
    else:
        train, val, test = split_by_trajectory(raw, seed=seed)

    results: dict[str, ClsMetrics] = {}

    # 1. persistence -------------------------------------------------------
    results["persistence"] = evaluate(test.y, persistence_scores(test.secure_now))

    # 2. logistic regression on flat features ------------------------------
    sc = Standardizer()
    Xtr = sc.fit_transform(train.flat())
    Xte = sc.transform(test.flat())
    logit = LogisticRegression(seed=seed).fit(Xtr, train.y)
    results["logistic"] = evaluate(test.y, logit.predict_proba(Xte))

    # 3 & 4. neural models (optional — only if torch is installed) ---------
    try:
        from .world_model import MLPModel, mlp_scores, train_mlp
        from .controller import fit_graph_bundle
    except ImportError:
        print("[torch not available — skipping mlp/gnn]")
        return results

    mlp = MLPModel(n_in=Xtr.shape[1])
    train_mlp(mlp, Xtr, train.y, seed=seed)
    results["mlp"] = evaluate(test.y, mlp_scores(mlp, Xte))

    bundle = fit_graph_bundle(train, seed=seed)
    results["gnn"] = evaluate(test.y, bundle.scores(test))

    return results


def _print_table(results: dict[str, ClsMetrics]) -> None:
    print(f"\n{'model':<14}{'acc':>8}{'F1':>8}{'AUROC':>8}{'prec':>8}{'recall':>8}{'n':>8}")
    print("-" * 62)
    for name, m in results.items():
        print(f"{name:<14}{m.accuracy:>8.3f}{m.f1:>8.3f}{m.auroc:>8.3f}"
              f"{m.precision:>8.3f}{m.recall:>8.3f}{m.n:>8}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Train GridWorld security predictors")
    ap.add_argument("--data", required=True, help="dataset directory of .npz trajectories")
    ap.add_argument("--horizon", type=int, default=20, help="prediction horizon (steps)")
    ap.add_argument("--holdout-family", help="hold out a fault family for the test set")
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()

    results = run(args.data, args.horizon, args.holdout_family, args.seed)
    split = f"held-out family={args.holdout_family}" if args.holdout_family else "by-trajectory split"
    print(f"\nGridWorld security prediction (horizon={args.horizon} steps, {split})")
    _print_table(results)


if __name__ == "__main__":
    main()

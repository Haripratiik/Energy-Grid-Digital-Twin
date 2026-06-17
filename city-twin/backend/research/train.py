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


def run_overload(data_dir: str, horizon: int, holdout_family: str | None,
                 seed: int) -> dict[str, ClsMetrics]:
    """Per-branch overload prediction (edge-level) — the topology-dependent task."""
    raw = load_dataset(data_dir, horizon=horizon)
    if holdout_family:
        train, test = split_by_family(raw, holdout_family)
    else:
        train, _, test = split_by_trajectory(raw, seed=seed)

    y_te = test.Y_edge.reshape(-1)
    results: dict[str, ClsMetrics] = {}

    # 1. persistence: a branch overloaded now is predicted overloaded ahead.
    results["persistence"] = evaluate(y_te, test.edge_loaded_now.reshape(-1))

    # 2. logistic on per-edge features (local context only).
    Xtr = train.per_edge_features().reshape(-1, train.per_edge_features().shape[-1])
    Xte = test.per_edge_features().reshape(-1, test.per_edge_features().shape[-1])
    sc = Standardizer()
    Xtr_s = sc.fit_transform(Xtr); Xte_s = sc.transform(Xte)
    logit = LogisticRegression(seed=seed).fit(Xtr_s, train.Y_edge.reshape(-1))
    results["logistic"] = evaluate(y_te, logit.predict_proba(Xte_s))

    try:
        from .world_model import (
            GraphWorldModel, MLPModel, graph_edge_scores, mlp_scores,
            train_graph_edges, train_mlp,
        )
    except ImportError:
        print("[torch not available — skipping mlp/gnn]")
        return results

    # 3. MLP on the same per-edge features (topology-blind).
    mlp = MLPModel(n_in=Xtr_s.shape[1])
    train_mlp(mlp, Xtr_s, train.Y_edge.reshape(-1), seed=seed)
    results["mlp"] = evaluate(y_te, mlp_scores(mlp, Xte_s))

    # 4. GNN edge head (multi-hop topology + action conditioning).
    gnn = GraphWorldModel(
        n_node_feat=train.X_node.shape[-1], n_edge_feat=train.X_edge.shape[-1],
        n_global_feat=train.X_global.shape[-1], n_action_feat=train.X_action.shape[-1],
    )
    gnn.set_topology(train.edge_index, n_nodes=train.X_node.shape[1])
    train_graph_edges(gnn, train, seed=seed)
    results["gnn"] = evaluate(y_te, graph_edge_scores(gnn, test))

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
    ap.add_argument("--target", choices=["security", "overload"], default="security",
                    help="security = global secure-ahead; overload = per-branch overload")
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()

    fn = run_overload if args.target == "overload" else run
    results = fn(args.data, args.horizon, args.holdout_family, args.seed)
    split = f"held-out family={args.holdout_family}" if args.holdout_family else "by-trajectory split"
    label = "per-branch overload" if args.target == "overload" else "security"
    print(f"\nGridWorld {label} prediction (horizon={args.horizon} steps, {split})")
    _print_table(results)


if __name__ == "__main__":
    main()

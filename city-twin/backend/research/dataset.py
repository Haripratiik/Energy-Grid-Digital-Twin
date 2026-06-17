"""Load GridWorld trajectories into a supervised learning task.

Task: **predict whether the grid will be secure ``horizon`` steps ahead**, given
the current graph state and the action taken now. ``secure`` means zero limit
violations (from the recorded ``n_violations`` global feature).

Splits are by *trajectory* (never leak steps from one rollout across the split)
and additionally by *fault family* (train on some families, test on a held-out
one) — the generalization test that matters for the world-model story.
"""

from __future__ import annotations

import glob
import json
import os
from dataclasses import dataclass

import numpy as np

# Index of n_violations within the global feature vector (see trajectory.py).
_N_VIOL_IDX = 5
# Index of loading_frac within the edge feature vector (see trajectory.py).
_EDGE_LOADING_IDX = 3
_OVERLOAD_FRAC = 1.0   # loading_frac > 1.0 == past thermal limit


@dataclass
class Samples:
    X_node: np.ndarray      # (N, n_nodes, n_node_feat)
    X_edge: np.ndarray      # (N, n_edges, n_edge_feat)
    X_global: np.ndarray    # (N, n_global_feat)
    X_action: np.ndarray    # (N, 4)
    y: np.ndarray           # (N,)  1 = secure at t+H
    secure_now: np.ndarray  # (N,)  1 = secure at t (persistence baseline)
    family: np.ndarray      # (N,)  object array of family strings
    traj_id: np.ndarray     # (N,)  int trajectory index
    edge_index: np.ndarray  # (2, n_edges) shared topology

    # Edge-level target (overload prediction); None for the security-only task.
    Y_edge: np.ndarray | None = None         # (N, n_edges) 1 = overloaded at t+H
    edge_loaded_now: np.ndarray | None = None  # (N, n_edges) 1 = overloaded at t

    def __len__(self) -> int:
        return len(self.y)

    def select(self, idx: np.ndarray) -> "Samples":
        return Samples(
            X_node=self.X_node[idx], X_edge=self.X_edge[idx],
            X_global=self.X_global[idx], X_action=self.X_action[idx],
            y=self.y[idx], secure_now=self.secure_now[idx],
            family=self.family[idx], traj_id=self.traj_id[idx],
            edge_index=self.edge_index,
            Y_edge=None if self.Y_edge is None else self.Y_edge[idx],
            edge_loaded_now=None if self.edge_loaded_now is None else self.edge_loaded_now[idx],
        )

    def per_edge_features(self) -> np.ndarray:
        """Per-edge feature tensor (N, n_edges, D) for non-graph edge baselines.

        Each edge gets its own features + both endpoint node features + the
        graph-global and action context. A flat model sees only this local
        context — no multi-hop topology, which is the point of the comparison.
        """
        src, dst = self.edge_index[0], self.edge_index[1]
        node_src = self.X_node[:, src, :]          # (N, E, Fn)
        node_dst = self.X_node[:, dst, :]
        n, e = node_src.shape[0], node_src.shape[1]
        glob = np.broadcast_to(self.X_global[:, None, :], (n, e, self.X_global.shape[1]))
        act = np.broadcast_to(self.X_action[:, None, :], (n, e, self.X_action.shape[1]))
        return np.concatenate([self.X_edge, node_src, node_dst, glob, act], axis=-1).astype(np.float32)

    def flat(self) -> np.ndarray:
        """Non-graph feature vector: global + action + node/edge aggregates."""
        node_mean = self.X_node.mean(axis=1)
        node_max = self.X_node.max(axis=1)
        node_min = self.X_node.min(axis=1)
        edge_mean = self.X_edge.mean(axis=1)
        edge_max = self.X_edge.max(axis=1)
        return np.concatenate(
            [self.X_global, self.X_action, node_mean, node_max, node_min,
             edge_mean, edge_max],
            axis=1,
        ).astype(np.float32)


def load_dataset(data_dir: str, horizon: int = 20) -> Samples:
    """Build supervised samples from every ``*.npz`` trajectory in ``data_dir``."""
    paths = sorted(glob.glob(os.path.join(data_dir, "*.npz")))
    if not paths:
        raise FileNotFoundError(f"No .npz trajectories found in {data_dir!r}")

    xn, xe, xg, xa, ys, sn, fam, tid = ([] for _ in range(8))
    ye, eln = [], []   # edge-overload label at t+H, edge overloaded now
    edge_index = None

    for traj_idx, path in enumerate(paths):
        d = np.load(path)
        gf = d["global_features"]
        T = gf.shape[0]
        if T <= horizon:
            continue
        if edge_index is None:
            edge_index = d["edge_index"]

        meta_path = path.replace(".npz", ".json")
        family = "unknown"
        if os.path.exists(meta_path):
            with open(meta_path) as f:
                family = json.load(f).get("labels", {}).get("family", "unknown")

        secure = (gf[:, _N_VIOL_IDX] == 0).astype(np.float32)
        node = d["node_features"]
        edge = d["edge_features"]
        act = d["actions"]
        edge_overloaded = (edge[:, :, _EDGE_LOADING_IDX] > _OVERLOAD_FRAC).astype(np.float32)

        for t in range(T - horizon):
            xn.append(node[t]); xe.append(edge[t]); xg.append(gf[t]); xa.append(act[t])
            ys.append(secure[t + horizon]); sn.append(secure[t])
            ye.append(edge_overloaded[t + horizon]); eln.append(edge_overloaded[t])
            fam.append(family); tid.append(traj_idx)

    if not ys:
        raise ValueError(f"No samples built (horizon {horizon} too long?)")

    return Samples(
        X_node=np.asarray(xn, np.float32), X_edge=np.asarray(xe, np.float32),
        X_global=np.asarray(xg, np.float32), X_action=np.asarray(xa, np.float32),
        y=np.asarray(ys, np.float32), secure_now=np.asarray(sn, np.float32),
        family=np.asarray(fam, dtype=object), traj_id=np.asarray(tid, np.int64),
        edge_index=edge_index,
        Y_edge=np.asarray(ye, np.float32), edge_loaded_now=np.asarray(eln, np.float32),
    )


def split_by_trajectory(
    s: Samples, val_frac: float = 0.15, test_frac: float = 0.15, seed: int = 0,
) -> tuple[Samples, Samples, Samples]:
    """Group split: whole trajectories go to exactly one of train/val/test."""
    traj_ids = np.unique(s.traj_id)
    rng = np.random.default_rng(seed)
    rng.shuffle(traj_ids)
    n = len(traj_ids)
    n_test = max(1, int(round(n * test_frac)))
    n_val = max(1, int(round(n * val_frac))) if n - n_test > 1 else 0
    test_ids = set(traj_ids[:n_test])
    val_ids = set(traj_ids[n_test:n_test + n_val])

    def mask(ids):
        return np.array([t in ids for t in s.traj_id])

    train_ids = set(traj_ids) - test_ids - val_ids
    return s.select(mask(train_ids)), s.select(mask(val_ids)), s.select(mask(test_ids))


def split_by_family(s: Samples, test_family: str) -> tuple[Samples, Samples]:
    """Hold out one fault family entirely for the test set."""
    test_mask = s.family == test_family
    if not test_mask.any():
        raise ValueError(f"family {test_family!r} not present in dataset")
    return s.select(~test_mask), s.select(test_mask)


class Standardizer:
    """Zero-mean/unit-variance scaler fit on training features."""

    def __init__(self) -> None:
        self.mean: np.ndarray | None = None
        self.std: np.ndarray | None = None

    def fit(self, x: np.ndarray) -> "Standardizer":
        self.mean = x.mean(axis=0)
        self.std = x.std(axis=0)
        self.std[self.std < 1e-6] = 1.0
        return self

    def transform(self, x: np.ndarray) -> np.ndarray:
        return ((x - self.mean) / self.std).astype(np.float32)

    def fit_transform(self, x: np.ndarray) -> np.ndarray:
        return self.fit(x).transform(x)

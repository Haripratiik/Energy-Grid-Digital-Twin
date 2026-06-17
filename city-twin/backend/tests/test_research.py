"""Tests for the GridWorld research layer.

Dataset / metrics / baselines run in CI (numpy only). Model + controller tests
are gated on torch via ``importorskip`` and use small synthetic data so they
stay fast and deterministic.
"""

from __future__ import annotations

import json
import os
import shutil

import numpy as np
import pytest

from research.baselines import LogisticRegression, persistence_scores
from research.dataset import (
    Samples, load_dataset, split_by_family, split_by_trajectory,
)
from research.metrics import evaluate

_TMP = os.path.join(os.path.dirname(__file__), "_tmp_research")

# Real topology dims (must match eval.trajectory).
from eval.trajectory import EDGE_FEATURES, GLOBAL_FEATURES, NODE_FEATURES, _EDGES
from physics.network import BUSES

N_NODES = len(BUSES)
N_EDGES = len(_EDGES)
EDGE_INDEX = np.array([(f, t) for (f, t, _) in _EDGES], dtype=np.int64).T


# --- synthetic fixtures ----------------------------------------------------

def _write_synthetic_npz(path: str, T: int, family: str, n_viol_seq: np.ndarray) -> None:
    rng = np.random.default_rng(abs(hash(family)) % 1000)
    gf = rng.normal(size=(T, len(GLOBAL_FEATURES))).astype(np.float32)
    gf[:, 5] = n_viol_seq  # n_violations channel drives the label
    np.savez_compressed(
        path,
        node_features=rng.normal(size=(T, N_NODES, len(NODE_FEATURES))).astype(np.float32),
        edge_features=rng.normal(size=(T, N_EDGES, len(EDGE_FEATURES))).astype(np.float32),
        edge_index=EDGE_INDEX,
        global_features=gf,
        actions=rng.normal(size=(T, 4)).astype(np.float32),
    )
    with open(path.replace(".npz", ".json"), "w") as f:
        json.dump({"labels": {"family": family}}, f)


@pytest.fixture(scope="module")
def synthetic_dir():
    shutil.rmtree(_TMP, ignore_errors=True)
    os.makedirs(_TMP)
    # Two families, a few trajectories each, with violation episodes.
    for i in range(3):
        seq = np.zeros(60); seq[20:35] = 1  # an insecure window
        _write_synthetic_npz(os.path.join(_TMP, f"famA_{i}.npz"), 60, "famA", seq)
    for i in range(3):
        seq = np.zeros(60); seq[10:25] = 2
        _write_synthetic_npz(os.path.join(_TMP, f"famB_{i}.npz"), 60, "famB", seq)
    yield _TMP
    shutil.rmtree(_TMP, ignore_errors=True)


# --- dataset ---------------------------------------------------------------

def test_load_dataset_shapes_and_labels(synthetic_dir):
    s = load_dataset(synthetic_dir, horizon=10)
    assert s.X_node.shape[1:] == (N_NODES, len(NODE_FEATURES))
    assert s.X_edge.shape[1:] == (N_EDGES, len(EDGE_FEATURES))
    assert s.edge_index.shape == (2, N_EDGES)
    assert set(np.unique(s.y)) <= {0.0, 1.0}
    assert set(s.family) == {"famA", "famB"}


def test_split_by_trajectory_has_no_leakage(synthetic_dir):
    s = load_dataset(synthetic_dir, horizon=10)
    train, val, test = split_by_trajectory(s, seed=1)
    tr = set(train.traj_id); va = set(val.traj_id); te = set(test.traj_id)
    assert tr.isdisjoint(te) and tr.isdisjoint(va) and va.isdisjoint(te)
    assert len(tr) + len(va) + len(te) == len(np.unique(s.traj_id))


def test_split_by_family_holds_out_target(synthetic_dir):
    s = load_dataset(synthetic_dir, horizon=10)
    train, test = split_by_family(s, "famB")
    assert set(test.family) == {"famB"}
    assert "famB" not in set(train.family)


def test_flat_feature_vector_is_2d(synthetic_dir):
    s = load_dataset(synthetic_dir, horizon=10)
    flat = s.flat()
    assert flat.ndim == 2 and flat.shape[0] == len(s)


def test_edge_labels_and_features(synthetic_dir):
    s = load_dataset(synthetic_dir, horizon=10)
    assert s.Y_edge.shape == (len(s), N_EDGES)
    assert s.edge_loaded_now.shape == (len(s), N_EDGES)
    assert set(np.unique(s.Y_edge)) <= {0.0, 1.0}
    pe = s.per_edge_features()
    assert pe.shape[:2] == (len(s), N_EDGES)
    # Per-edge feature = edge + 2*node + global + action dims.
    expected = len(EDGE_FEATURES) + 2 * len(NODE_FEATURES) + len(GLOBAL_FEATURES) + 4
    assert pe.shape[2] == expected


# --- metrics ---------------------------------------------------------------

def test_metrics_perfect_classifier():
    y = np.array([0, 0, 1, 1])
    m = evaluate(y, np.array([0.1, 0.2, 0.8, 0.9]))
    assert m.accuracy == 1.0 and m.f1 == 1.0 and m.auroc == 1.0


def test_auroc_half_for_random_constant():
    y = np.array([0, 1, 0, 1])
    m = evaluate(y, np.array([0.5, 0.5, 0.5, 0.5]))
    assert m.auroc == pytest.approx(0.5, abs=1e-6)


# --- baselines -------------------------------------------------------------

def test_persistence_uses_current_security():
    sec = np.array([1.0, 0.0, 1.0])
    assert np.array_equal(persistence_scores(sec), sec)


def test_logistic_learns_separable_data():
    rng = np.random.default_rng(0)
    X = np.vstack([rng.normal(-2, 1, (200, 4)), rng.normal(2, 1, (200, 4))]).astype(np.float32)
    y = np.concatenate([np.zeros(200), np.ones(200)])
    clf = LogisticRegression(epochs=300).fit(X, y)
    m = evaluate(y, clf.predict_proba(X))
    assert m.auroc > 0.95


# --- torch-gated: models + controller --------------------------------------

def _synthetic_samples(n: int, seed: int = 0) -> Samples:
    rng = np.random.default_rng(seed)
    viol = rng.integers(0, 3, size=n).astype(np.float32)
    glob = rng.normal(size=(n, len(GLOBAL_FEATURES))).astype(np.float32)
    glob[:, 5] = viol
    secure_now = (viol == 0).astype(np.float32)
    # Label: secure-ahead correlates with current security (learnable signal).
    y = ((viol == 0) ^ (rng.random(n) < 0.1)).astype(np.float32)
    edge = rng.normal(size=(n, N_EDGES, len(EDGE_FEATURES))).astype(np.float32)
    # Edge overload label: learnable from the edge's loading channel (index 3).
    Y_edge = (edge[:, :, 3] > 0.5).astype(np.float32)
    edge_loaded_now = (edge[:, :, 3] > 0.8).astype(np.float32)
    return Samples(
        X_node=rng.normal(size=(n, N_NODES, len(NODE_FEATURES))).astype(np.float32),
        X_edge=edge,
        X_global=glob, X_action=rng.normal(size=(n, 4)).astype(np.float32),
        y=y, secure_now=secure_now,
        family=np.array(["syn"] * n, dtype=object),
        traj_id=np.zeros(n, dtype=np.int64), edge_index=EDGE_INDEX,
        Y_edge=Y_edge, edge_loaded_now=edge_loaded_now,
    )


def test_gnn_trains_and_predicts_signal():
    pytest.importorskip("torch")
    from research.controller import fit_graph_bundle

    train = _synthetic_samples(300, seed=1)
    test = _synthetic_samples(150, seed=2)
    bundle = fit_graph_bundle(train, seed=0, epochs=40)
    m = evaluate(test.y, bundle.scores(test))
    assert 0.0 <= m.auroc <= 1.0
    assert m.auroc > 0.7, f"GNN should learn the synthetic signal (AUROC={m.auroc})"


def test_gnn_edge_head_predicts_overload():
    pytest.importorskip("torch")
    from research.world_model import (
        GraphWorldModel, graph_edge_scores, train_graph_edges,
    )

    train = _synthetic_samples(250, seed=1)
    test = _synthetic_samples(120, seed=2)
    gnn = GraphWorldModel(
        n_node_feat=len(NODE_FEATURES), n_edge_feat=len(EDGE_FEATURES),
        n_global_feat=len(GLOBAL_FEATURES), n_action_feat=4,
    )
    gnn.set_topology(EDGE_INDEX, n_nodes=N_NODES)
    train_graph_edges(gnn, train, seed=0, epochs=30)
    scores = graph_edge_scores(gnn, test)
    assert scores.shape == (len(test) * N_EDGES,)
    m = evaluate(test.Y_edge.reshape(-1), scores)
    assert m.auroc > 0.7, f"edge head should learn the synthetic signal (AUROC={m.auroc})"


def test_learned_controller_runs_in_harness():
    pytest.importorskip("torch")
    from research.controller import LearnedController, fit_graph_bundle
    from eval.controllers import GreedyRuleController
    from eval.runner import run_scenario
    from eval.scenario import Scenario, ScenarioEvent
    from physics.fault_handler import FaultType

    bundle = fit_graph_bundle(_synthetic_samples(200, seed=3), seed=0, epochs=10)
    controller = LearnedController(bundle, candidate_source=GreedyRuleController())

    scen = Scenario(
        id="t", family="gen_dropout", seed=5, settle_s=2.0, duration_s=6.0,
        events=[ScenarioEvent(at_s=2.0, fault_type=FaultType.GEN_DROPOUT,
                              target_rid="ri.city-grid.main.generator.3")],
    )
    res = run_scenario(scen, controller)
    assert res.metrics.n_steps > 0
    assert res.metrics.controller == "learned"

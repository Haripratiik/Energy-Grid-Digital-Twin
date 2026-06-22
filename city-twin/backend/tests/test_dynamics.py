"""Tests for the action-conditioned dynamics world model (Thrust B).

The exploratory-controller tests run without torch; the model tests are gated on
torch via ``importorskip`` and use small synthetic data so they stay fast.
"""

from __future__ import annotations

import numpy as np
import pytest

from eval.controllers import ExploratoryController
from physics.swing import GridSimulator


# --- exploratory data policy (no torch) -----------------------------------

def test_exploratory_controller_emits_valid_actions():
    state = GridSimulator().get_state()
    ctrl = ExploratoryController(epsilon=1.0, seed=1)
    n_acted = 0
    for _ in range(25):
        for a in ctrl.decide(state):
            assert a.action_type in ("GEN_SETPOINT", "LOAD_SHED")
            assert a.target_rid
            n_acted += 1
    assert n_acted > 0          # epsilon=1.0 → it acts most cycles


def test_exploratory_controller_is_reproducible():
    state = GridSimulator().get_state()
    c1, c2 = ExploratoryController(seed=7), ExploratoryController(seed=7)
    assert str(c1.decide(state)) == str(c2.decide(state))


# --- learned dynamics model (torch) ---------------------------------------

def _synthetic(samples_cls, *, n=500, n_nodes=6, n_edges=6, seed=0):
    """Synthetic transitions where the action causes a known Vm change at its
    target node, on top of small passive noise — so a working model must beat
    persistence AND must use the action."""
    rng = np.random.default_rng(seed)
    X_node = rng.normal(size=(n, n_nodes, 7)).astype(np.float32)
    X_node[:, :, 0] = 1.0 + 0.02 * rng.normal(size=(n, n_nodes))   # Vm ~ 1.0
    X_edge = (np.abs(rng.normal(size=(n, n_edges, 6))) * 0.3).astype(np.float32)
    X_edge[:, :, 5] = 0.0                                          # is_transformer=0 → all lines
    X_global = rng.normal(size=(n, 6)).astype(np.float32)
    X_anode = np.zeros((n, n_nodes, 4), np.float32)
    acted = np.zeros(n, np.float32)
    dY_node = (0.005 * rng.normal(size=(n, n_nodes, 2))).astype(np.float32)
    dY_edge = (0.005 * rng.normal(size=(n, n_edges, 1))).astype(np.float32)
    for i in range(n):
        if rng.random() < 0.5:
            acted[i] = 1.0
            node = int(rng.integers(n_nodes))
            mag = float(rng.uniform(-0.5, 0.5))
            X_anode[i, node, 0] = 1.0
            X_anode[i, node, 1] = mag
            X_anode[i, node, 2] = 1.0
            dY_node[i, node, 0] += 0.30 * mag                       # action → ΔVm
    edge_index = np.array([[i % n_nodes for i in range(n_edges)],
                           [(i + 1) % n_nodes for i in range(n_edges)]], dtype=np.int64)
    return samples_cls(
        X_node=X_node, X_edge=X_edge, X_global=X_global, X_anode=X_anode,
        dY_node=dY_node, dY_edge=dY_edge, acted=acted,
        family=np.array(["synthetic"] * n, dtype=object),
        traj_id=(np.arange(n) % 10).astype(np.int64), edge_index=edge_index,
    )


def test_dynamics_model_beats_persistence_and_uses_action():
    pytest.importorskip("torch")
    from research.dynamics import DynamicsSamples, evaluate, fit_dynamics

    s = _synthetic(DynamicsSamples)
    bundle = fit_dynamics(s, epochs=60, seed=0)
    res = evaluate(bundle, s)

    overall, acted = res["overall"], res["acted"]
    # 1. The learned model beats the persistence (zero-delta) baseline on Vm.
    assert overall["vm_learned"] < overall["vm_persist"]
    # 2. Zeroing the action at inference HURTS on action-bearing steps — proof the
    #    model causally uses the action, not just the passive dynamics.
    assert acted["vm_ablated"] > acted["vm_learned"]


def test_dynamics_split_and_shapes():
    pytest.importorskip("torch")
    from research.dynamics import DynamicsSamples, split_by_trajectory

    s = _synthetic(DynamicsSamples, n=200)
    train, test = split_by_trajectory(s, test_frac=0.3, seed=1)
    assert len(train) + len(test) == len(s)
    assert set(train.traj_id).isdisjoint(set(test.traj_id))   # no trajectory leakage


def test_physics_flow_decoder_recovers_and_decodes():
    """On data where loading = c·|angle-diff| exactly (the DC line-flow law), the
    decoder must recover c and decode loading deltas from angle deltas."""
    pytest.importorskip("torch")
    from research.dynamics import DynamicsSamples, PhysicsFlowDecoder

    rng = np.random.default_rng(0)
    N, n_nodes, n_edges = 300, 6, 5
    edge_index = np.array([[i % n_nodes for i in range(n_edges)],
                           [(i + 2) % n_nodes for i in range(n_edges)]], dtype=np.int64)
    X_node = np.zeros((N, n_nodes, 7), np.float32)
    X_node[:, :, 1] = rng.normal(0, 10, (N, n_nodes))            # bus angles (deg)
    c_true = rng.uniform(0.01, 0.05, n_edges).astype(np.float32)
    angdiff = X_node[:, edge_index[0], 1] - X_node[:, edge_index[1], 1]
    X_edge = np.zeros((N, n_edges, 6), np.float32)
    X_edge[:, :, 3] = c_true[None, :] * np.abs(angdiff)          # loading = c·|Δθ|
    X_edge[:, :, 5] = 0.0                                        # all lines

    s = DynamicsSamples(
        X_node=X_node, X_edge=X_edge, X_global=np.zeros((N, 6), np.float32),
        X_anode=np.zeros((N, n_nodes, 4), np.float32),
        dY_node=np.zeros((N, n_nodes, 2), np.float32),
        dY_edge=np.zeros((N, n_edges, 1), np.float32),
        acted=np.zeros(N, np.float32), family=np.array(["s"] * N, dtype=object),
        traj_id=np.zeros(N, np.int64), edge_index=edge_index,
    )
    dec = PhysicsFlowDecoder().fit(s)
    assert np.allclose(dec.c, c_true, atol=5e-3)                 # recovers susceptance

    dva = rng.normal(0, 2, (N, n_nodes)).astype(np.float32)
    decoded = dec.decode_from_arrays(X_node, dva)
    ang_next = angdiff + (dva[:, edge_index[0]] - dva[:, edge_index[1]])
    true_dl = c_true[None, :] * (np.abs(ang_next) - np.abs(angdiff))
    assert np.abs(decoded - true_dl).max() < 1e-2               # decodes Δloading from Δangle


def test_flow_loss_training_runs():
    pytest.importorskip("torch")
    from research.dynamics import DynamicsSamples, fit_dynamics

    s = _synthetic(DynamicsSamples, n=200)
    bundle = fit_dynamics(s, epochs=10, seed=0, flow_loss_weight=2.0)   # must not error
    assert bundle.model is not None


def test_bootstrap_skill_ci_shape_and_ordering():
    pytest.importorskip("torch")
    from research.dynamics import DynamicsSamples, bootstrap_skill_ci, fit_dynamics

    s = _synthetic(DynamicsSamples)
    bundle = fit_dynamics(s, epochs=40, seed=0)
    ci = bootstrap_skill_ci(bundle, s, n_boot=100, seed=0)
    for slice_name in ("overall", "disturbed"):
        for comp in ("vm", "va", "load"):
            p5, p50, p95 = ci[slice_name][comp]
            assert p5 <= p50 <= p95            # percentiles ordered
    # The synthetic data plants an action→ΔVm effect, so a trained model should
    # beat persistence on Vm — its bootstrap CI should sit clearly positive.
    assert ci["overall"]["vm"][0] > 0          # p5 above zero ⇒ significant

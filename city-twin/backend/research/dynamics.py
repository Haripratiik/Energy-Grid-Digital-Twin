"""Action-conditioned graph **dynamics** world model.

This is the upgrade over :mod:`research.world_model` (which predicts a single
binary security bit ``H`` steps ahead). Here the model learns the actual grid
*dynamics under intervention*:

    (state_t, action_t)  ->  state_{t+H}

predicting the **next-state delta** of the physically meaningful quantities —
per-bus voltage magnitude & angle, and per-branch loading. Two design choices
fix the weaknesses of the original world model:

1. **Next-state target, not a label.** The model predicts how the grid *moves*,
   so it can be rolled out and planned over, not just queried for a yes/no.
2. **Action injected at the acted node**, not at the graph readout. The action
   is encoded as a per-node feature (non-zero only at the bus it targets) and
   enters message passing, so its effect can propagate through the topology —
   which is what an action-conditioned *dynamics* model needs.

Baseline: **persistence** (predict zero delta — "the grid doesn't move"). A
learned model only earns its keep by beating it. We also report an **ablation**
(zero the action features at inference) to show, causally, that the model uses
the action — not just the passive dynamics.

Pure PyTorch (manual message passing); import only when torch is available.
"""

from __future__ import annotations

import dataclasses
import glob
import json
import os
from dataclasses import dataclass

import numpy as np
import torch
import torch.nn as nn

from physics.network import BUS_INDEX

from .dataset import Standardizer
from .world_model import _mlp

# Feature-vector indices (see eval/trajectory.py).
_VM_IDX, _VA_IDX = 0, 1            # node: voltage magnitude pu, voltage angle deg
# edge: [from_idx, to_idx, flow_mw(abs), loading_frac, tripped, is_transformer]
_EDGE_LOADING_IDX = 3
_EDGE_ISXF_IDX = 5
_ACTION_TYPE_LOAD_SHED = 1
_ACTION_TYPE_GEN_SETPOINT = 2


# ---------------------------------------------------------------------------
# Dataset
# ---------------------------------------------------------------------------

@dataclass
class DynamicsSamples:
    X_node: np.ndarray       # (N, n_nodes, n_node_feat)   state_t
    X_edge: np.ndarray       # (N, n_edges, n_edge_feat)
    X_global: np.ndarray     # (N, n_global_feat)
    X_anode: np.ndarray      # (N, n_nodes, 4)  per-node action features
    dY_node: np.ndarray      # (N, n_nodes, 2)  Δ[Vm, Va] over the horizon
    dY_edge: np.ndarray      # (N, n_edges, 1)  Δ loading_frac
    acted: np.ndarray        # (N,)  1 if an action was applied at t
    family: np.ndarray       # (N,)  object array of fault-family strings
    traj_id: np.ndarray      # (N,)  int trajectory index
    edge_index: np.ndarray   # (2, n_edges)

    def __len__(self) -> int:
        return len(self.traj_id)

    def select(self, idx) -> "DynamicsSamples":
        return dataclasses.replace(
            self, X_node=self.X_node[idx], X_edge=self.X_edge[idx],
            X_global=self.X_global[idx], X_anode=self.X_anode[idx],
            dY_node=self.dY_node[idx], dY_edge=self.dY_edge[idx],
            acted=self.acted[idx], family=self.family[idx], traj_id=self.traj_id[idx],
        )


def _action_node_features(a: np.ndarray, n_nodes: int) -> np.ndarray:
    """Per-node action features [is_target, signed_mag/100, is_gen, is_shed]."""
    feat = np.zeros((n_nodes, 4), dtype=np.float32)
    if a[0] < 0.5:                       # acted flag
        return feat
    type_id, target, mag = int(round(a[1])), int(round(a[2])), float(a[3])
    node = BUS_INDEX.get(target)
    if node is None:                     # branch-targeted action: not node-local
        return feat
    feat[node, 0] = 1.0
    feat[node, 1] = mag / 100.0
    feat[node, 2] = 1.0 if type_id == _ACTION_TYPE_GEN_SETPOINT else 0.0
    feat[node, 3] = 1.0 if type_id == _ACTION_TYPE_LOAD_SHED else 0.0
    return feat


def load_dynamics_dataset(data_dir: str, horizon: int = 1) -> DynamicsSamples:
    """Build ``(state_t, action_t) -> Δstate_{t+H}`` samples from .npz trajectories."""
    paths = sorted(glob.glob(os.path.join(data_dir, "*.npz")))
    if not paths:
        raise FileNotFoundError(f"No .npz trajectories found in {data_dir!r}")

    xn, xe, xg, xa, dyn, dye, ac, fam, tid = ([] for _ in range(9))
    edge_index = None

    for traj_idx, path in enumerate(paths):
        d = np.load(path)
        node, edge, gf, act = (d["node_features"], d["edge_features"],
                               d["global_features"], d["actions"])
        T = gf.shape[0]
        if T <= horizon:
            continue
        if edge_index is None:
            edge_index = d["edge_index"]
        n_nodes = node.shape[1]

        family = "unknown"
        meta_path = path.replace(".npz", ".json")
        if os.path.exists(meta_path):
            with open(meta_path) as f:
                family = json.load(f).get("labels", {}).get("family", "unknown")

        for t in range(T - horizon):
            anode = _action_node_features(act[t], n_nodes)
            xn.append(node[t]); xe.append(edge[t]); xg.append(gf[t])
            xa.append(anode)
            dyn.append(node[t + horizon][:, [_VM_IDX, _VA_IDX]] - node[t][:, [_VM_IDX, _VA_IDX]])
            dye.append((edge[t + horizon][:, [_EDGE_LOADING_IDX]]
                        - edge[t][:, [_EDGE_LOADING_IDX]]))
            # "acted" reflects an action the model actually SEES (encoded at a
            # node), not merely that the recorder logged one — branch-targeted
            # actions that don't map to a bus node are not node-encoded, so they
            # must not pollute the acted slice / ablation.
            ac.append(float(anode[:, 0].max() > 0.5))
            fam.append(family); tid.append(traj_idx)

    if not tid:
        raise ValueError(f"No samples built (horizon {horizon} too long?)")

    return DynamicsSamples(
        X_node=np.asarray(xn, np.float32), X_edge=np.asarray(xe, np.float32),
        X_global=np.asarray(xg, np.float32), X_anode=np.asarray(xa, np.float32),
        dY_node=np.asarray(dyn, np.float32), dY_edge=np.asarray(dye, np.float32),
        acted=np.asarray(ac, np.float32), family=np.asarray(fam, dtype=object),
        traj_id=np.asarray(tid, np.int64), edge_index=edge_index,
    )


def split_by_trajectory(s: DynamicsSamples, *, test_frac: float = 0.2, seed: int = 0):
    ids = np.unique(s.traj_id)
    rng = np.random.default_rng(seed)
    rng.shuffle(ids)
    n_test = max(1, int(round(len(ids) * test_frac)))
    test_ids = set(ids[:n_test])
    mask = np.array([t in test_ids for t in s.traj_id])
    return s.select(~mask), s.select(mask)


def split_by_family(s: DynamicsSamples, test_family: str):
    test = s.family == test_family
    if not test.any():
        raise ValueError(f"family {test_family!r} not present")
    return s.select(~test), s.select(test)


# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------

class GraphDynamicsModel(nn.Module):
    """Message-passing GNN predicting per-node and per-edge next-state deltas.

    The action enters as a per-node feature (``x_anode``) at the *encoder*, so it
    participates in every round of message passing and its effect can propagate
    through the topology — the key difference from the readout-only conditioning
    in :class:`research.world_model.GraphWorldModel`.
    """

    def __init__(self, n_node_feat: int, n_edge_feat: int, n_global_feat: int,
                 n_anode_feat: int = 4, hidden: int = 64, n_layers: int = 3) -> None:
        super().__init__()
        self.hidden = hidden
        self.n_layers = n_layers
        self.node_enc = nn.Linear(n_node_feat + n_anode_feat + n_global_feat, hidden)
        self.msg = nn.ModuleList([
            _mlp([2 * hidden + n_edge_feat, hidden, hidden]) for _ in range(n_layers)
        ])
        self.upd = nn.ModuleList([_mlp([2 * hidden, hidden]) for _ in range(n_layers)])
        self.node_head = _mlp([hidden, hidden, 2])                       # Δ[Vm, Va]
        self.edge_head = _mlp([2 * hidden + n_edge_feat, hidden, 1])     # Δ loading

    def set_topology(self, edge_index: np.ndarray, n_nodes: int) -> None:
        src = np.concatenate([edge_index[0], edge_index[1]])
        dst = np.concatenate([edge_index[1], edge_index[0]])
        self.register_buffer("src", torch.as_tensor(src, dtype=torch.long), persistent=False)
        self.register_buffer("dst", torch.as_tensor(dst, dtype=torch.long), persistent=False)
        self.register_buffer("e_src", torch.as_tensor(edge_index[0], dtype=torch.long), persistent=False)
        self.register_buffer("e_dst", torch.as_tensor(edge_index[1], dtype=torch.long), persistent=False)
        deg = np.bincount(dst, minlength=n_nodes).astype(np.float32)
        deg[deg == 0] = 1.0
        self.register_buffer("deg", torch.as_tensor(deg).view(1, n_nodes, 1), persistent=False)
        self.n_nodes = n_nodes

    def forward(self, x_node, x_edge, x_global, x_anode):
        b, n, _ = x_node.shape
        g = x_global[:, None, :].expand(b, n, x_global.shape[-1])
        h = torch.relu(self.node_enc(torch.cat([x_node, x_anode, g], dim=-1)))
        edge_feat = torch.cat([x_edge, x_edge], dim=1)                   # both directions
        for layer in range(self.n_layers):
            m = self.msg[layer](torch.cat([h[:, self.src, :], h[:, self.dst, :], edge_feat], dim=-1))
            agg = torch.zeros(b, self.n_nodes, self.hidden, device=h.device)
            agg.index_add_(1, self.dst, m)
            agg = agg / self.deg
            h = torch.relu(h + self.upd[layer](torch.cat([h, agg], dim=-1)))
        d_node = self.node_head(h)                                       # (b, N, 2)
        e_feats = torch.cat([h[:, self.e_src, :], h[:, self.e_dst, :], x_edge], dim=-1)
        d_edge = self.edge_head(e_feats)                                 # (b, E, 1)
        return d_node, d_edge


# ---------------------------------------------------------------------------
# Train / predict
# ---------------------------------------------------------------------------

@dataclass
class DynamicsBundle:
    model: GraphDynamicsModel
    sc_node: Standardizer
    sc_edge: Standardizer
    sc_global: Standardizer
    sc_dnode: Standardizer    # target scalers (standardise the deltas)
    sc_dedge: Standardizer

    def predict_delta(self, s: DynamicsSamples, *, zero_action: bool = False):
        """Return predicted (Δnode, Δedge) in **raw** units for a Samples set."""
        xa = np.zeros_like(s.X_anode) if zero_action else s.X_anode
        return self.predict_arrays(s.X_node, s.X_edge, s.X_global, xa)

    def predict_arrays(self, X_node, X_edge, X_global, X_anode):
        """Predict (Δnode, Δedge) in raw units from batched feature arrays.

        Used both by :meth:`predict_delta` and by the model-based controller,
        which builds one-sample batches per candidate action.
        """
        xn = self.sc_node.transform(X_node.reshape(-1, X_node.shape[-1])).reshape(X_node.shape)
        xe = self.sc_edge.transform(X_edge.reshape(-1, X_edge.shape[-1])).reshape(X_edge.shape)
        xg = self.sc_global.transform(X_global)
        self.model.eval()
        with torch.no_grad():
            dn, de = self.model(torch.as_tensor(xn), torch.as_tensor(xe),
                                torch.as_tensor(xg), torch.as_tensor(X_anode.astype(np.float32)))
        dn = _inv(self.sc_dnode, dn.reshape(-1, 2).numpy()).reshape(X_node.shape[0], X_node.shape[1], 2)
        de = _inv(self.sc_dedge, de.reshape(-1, 1).numpy()).reshape(X_edge.shape[0], X_edge.shape[1], 1)
        return dn, de


def _inv(scaler: Standardizer, x: np.ndarray) -> np.ndarray:
    return x * scaler.std + scaler.mean


def fit_dynamics(train: DynamicsSamples, *, epochs: int = 40, lr: float = 1e-3,
                 batch_size: int = 256, hidden: int = 64, n_layers: int = 3,
                 seed: int = 0, flow_loss_weight: float = 0.0) -> DynamicsBundle:
    torch.manual_seed(seed)
    sc_node = Standardizer().fit(train.X_node.reshape(-1, train.X_node.shape[-1]))
    sc_edge = Standardizer().fit(train.X_edge.reshape(-1, train.X_edge.shape[-1]))
    sc_global = Standardizer().fit(train.X_global)
    sc_dnode = Standardizer().fit(train.dY_node.reshape(-1, 2))
    sc_dedge = Standardizer().fit(train.dY_edge.reshape(-1, 1))

    model = GraphDynamicsModel(
        n_node_feat=train.X_node.shape[-1], n_edge_feat=train.X_edge.shape[-1],
        n_global_feat=train.X_global.shape[-1], n_anode_feat=train.X_anode.shape[-1],
        hidden=hidden, n_layers=n_layers,
    )
    model.set_topology(train.edge_index, n_nodes=train.X_node.shape[1])
    bundle = DynamicsBundle(model, sc_node, sc_edge, sc_global, sc_dnode, sc_dedge)

    xn = torch.as_tensor(sc_node.transform(
        train.X_node.reshape(-1, train.X_node.shape[-1])).reshape(train.X_node.shape))
    xe = torch.as_tensor(sc_edge.transform(
        train.X_edge.reshape(-1, train.X_edge.shape[-1])).reshape(train.X_edge.shape))
    xg = torch.as_tensor(sc_global.transform(train.X_global))
    xa = torch.as_tensor(train.X_anode)
    tn = torch.as_tensor(sc_dnode.transform(train.dY_node.reshape(-1, 2)).reshape(train.dY_node.shape))
    te = torch.as_tensor(sc_dedge.transform(train.dY_edge.reshape(-1, 1)).reshape(train.dY_edge.shape))

    # Optional physics-informed flow loss: penalise the model when the line
    # loadings DECODED from its predicted angles (DC line-flow law) miss the true
    # loading change — i.e. train the model to predict angles that decode to
    # correct loadings, directly targeting the loading bottleneck. The decode is
    # linear in the angles, so it's a differentiable layer. (See PhysicsFlowDecoder.)
    flow = None
    if flow_loss_weight > 0:
        dec = PhysicsFlowDecoder().fit(train)
        ei = train.edge_index
        flow = {
            "c": torch.as_tensor(dec.c),                                # (E,)
            "is_line": torch.as_tensor(dec.is_line),                    # (E,) bool
            "e_src": model.e_src, "e_dst": model.e_dst,                 # (E,) long buffers
            "ang_now": torch.as_tensor(
                (train.X_node[:, ei[0], _VA_IDX]
                 - train.X_node[:, ei[1], _VA_IDX]).astype(np.float32)),  # (N,E) raw deg
            "true_dl": torch.as_tensor(train.dY_edge[:, :, 0]),         # (N,E) raw loading Δ
            "std_va": float(sc_dnode.std[1]), "mean_va": float(sc_dnode.mean[1]),
            "load_std": float(sc_dedge.std.reshape(-1)[0]),
        }

    opt = torch.optim.Adam(model.parameters(), lr=lr, weight_decay=1e-5)
    loss_fn = nn.MSELoss()
    n = len(train)
    rng = np.random.default_rng(seed)
    for _ in range(epochs):
        model.train()
        order = rng.permutation(n)
        for i in range(0, n, batch_size):
            idx = order[i:i + batch_size]
            opt.zero_grad()
            dn, de = model(xn[idx], xe[idx], xg[idx], xa[idx])
            loss = loss_fn(dn, tn[idx]) + loss_fn(de, te[idx])
            if flow is not None:
                raw_dva = dn[:, :, 1] * flow["std_va"] + flow["mean_va"]   # (B,N) raw Δangle
                ang0 = flow["ang_now"][idx]                               # (B,E)
                dad = raw_dva[:, flow["e_src"]] - raw_dva[:, flow["e_dst"]]
                dec_dl = flow["c"][None, :] * (torch.abs(ang0 + dad) - torch.abs(ang0))
                m = flow["is_line"]
                fl = loss_fn(dec_dl[:, m] / flow["load_std"],
                             flow["true_dl"][idx][:, m] / flow["load_std"])
                loss = loss + flow_loss_weight * fl
            loss.backward()
            opt.step()
    return bundle


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------

def _mae(pred: np.ndarray, true: np.ndarray) -> float:
    return float(np.abs(pred - true).mean())


# Global-feature indices (see eval/trajectory.py): [sim_time, freq, gen, load, loss, n_viol]
_G_FREQ_IDX, _G_NVIOL_IDX = 1, 5
_NOMINAL_HZ = 60.0


def evaluate(bundle: DynamicsBundle, s: DynamicsSamples) -> dict:
    """MAE of learned vs persistence (zero-delta) vs action-ablated.

    Reported on three slices: ALL steps, ACTION-bearing steps, and DISTURBED
    steps (input state has a limit violation or off-nominal frequency). The slice
    masks are functions of the *input* state, not the target, so the comparison
    is not circular. Persistence is unbeatable on a quiescent grid (nothing
    moves in 100 ms); the learned model earns its keep on disturbed/transient
    states, which is exactly where a control-relevant world model must be good.
    """
    dn, de = bundle.predict_delta(s)
    dn0, de0 = bundle.predict_delta(s, zero_action=True)   # action ablation

    def block(mask):
        if mask.sum() == 0:
            return None
        sn, se = s.dY_node[mask], s.dY_edge[mask]
        return {
            "n": int(mask.sum()),
            "vm_persist": _mae(0.0, sn[..., 0]), "vm_learned": _mae(dn[mask][..., 0], sn[..., 0]),
            "va_persist": _mae(0.0, sn[..., 1]), "va_learned": _mae(dn[mask][..., 1], sn[..., 1]),
            "load_persist": _mae(0.0, se), "load_learned": _mae(de[mask], se),
            "vm_ablated": _mae(dn0[mask][..., 0], sn[..., 0]),
            "load_ablated": _mae(de0[mask], se),
        }

    disturbed = (s.X_global[:, _G_NVIOL_IDX] > 0) | \
        (np.abs(s.X_global[:, _G_FREQ_IDX] - _NOMINAL_HZ) > 0.05)
    return {
        "overall": block(np.ones(len(s), dtype=bool)),
        "acted": block(s.acted > 0.5),
        "disturbed": block(disturbed),
    }


def bootstrap_skill_ci(bundle: DynamicsBundle, s: DynamicsSamples, *,
                       n_boot: int = 400, seed: int = 0) -> dict:
    """Trajectory-level bootstrap CI on next-state skill vs persistence.

    Resamples whole test *trajectories* with replacement (respecting grouping,
    so the CI isn't over-optimistic) and recomputes skill — answering "is the
    +X% skill distinguishable from 0 on this test set?" with a single trained
    model (addresses the single-seed/no-error-bar critique cheaply: predictions
    are fixed, only the averaging set is resampled). Returns (p5, p50, p95) of
    skill% per component, for the ALL and DISTURBED slices.
    """
    dn, de = bundle.predict_delta(s)
    # Per-sample mean-abs persistence vs learned error, per component.
    comps = {
        "vm": (np.abs(s.dY_node[..., 0]).mean(1), np.abs(dn[..., 0] - s.dY_node[..., 0]).mean(1)),
        "va": (np.abs(s.dY_node[..., 1]).mean(1), np.abs(dn[..., 1] - s.dY_node[..., 1]).mean(1)),
        "load": (np.abs(s.dY_edge[..., 0]).mean(1), np.abs(de[..., 0] - s.dY_edge[..., 0]).mean(1)),
    }
    disturbed = (s.X_global[:, _G_NVIOL_IDX] > 0) | \
        (np.abs(s.X_global[:, _G_FREQ_IDX] - _NOMINAL_HZ) > 0.05)
    traj = s.traj_id
    uniq = np.unique(traj)
    traj_to_idx = {t: np.where(traj == t)[0] for t in uniq}
    rng = np.random.default_rng(seed)

    def ci(slice_mask):
        out = {}
        for name, (p, l) in comps.items():
            skills = []
            for _ in range(n_boot):
                chosen = rng.choice(uniq, size=len(uniq), replace=True)
                idx = np.concatenate([traj_to_idx[t] for t in chosen])
                idx = idx[slice_mask[idx]]
                if idx.size == 0:
                    continue
                P, L = p[idx].mean(), l[idx].mean()
                skills.append((1.0 - L / P) * 100.0 if P > 0 else 0.0)
            out[name] = (round(float(np.percentile(skills, 5)), 1),
                         round(float(np.percentile(skills, 50)), 1),
                         round(float(np.percentile(skills, 95)), 1))
        return out

    return {"overall": ci(np.ones(len(s), dtype=bool)), "disturbed": ci(disturbed)}


# ---------------------------------------------------------------------------
# Physics-informed flow head: decode line loading from predicted bus angles
# ---------------------------------------------------------------------------

class PhysicsFlowDecoder:
    """Decode line **loading** from bus-**angle** predictions via the DC line-flow law.

    The free-form edge head fails — loading is persistence-hard and doesn't
    generalize. But the model's *one* significant, generalizing strength is
    angle prediction, and DC power flow makes line flow a deterministic function
    of the angle difference across the line: ``P_ij = b_ij·(θ_i − θ_j)``, so
    ``loading_frac ≈ c_i·|θ_i − θ_j|`` (through the origin: no angle spread ⇒ no
    flow ⇒ no loading). We **fit one coefficient c_i per line** by ordinary least
    squares on the training data — which automatically absorbs the AC solver's
    *effective* per-unit parameters (incl. the scaling in ``ac_powerflow``) and
    the small reactive/loss terms — then decode loading deltas from the model's
    predicted angle deltas. Transformers carry no recorded MW flow, so they fall
    back to the learned edge head (``is_line`` marks which edges are decodable).

    This is the physics-informed flow head: predict the quantity the model is
    good at (angles), and let the physics map it to the quantity control needs
    (loading) — instead of learning loading from scratch.
    """

    def __init__(self) -> None:
        self.c: np.ndarray | None = None         # (E,) loading per |degree|, 0 for non-lines
        self.is_line: np.ndarray | None = None   # (E,) bool
        self.edge_index: np.ndarray | None = None  # (2, E)

    def fit(self, s: "DynamicsSamples") -> "PhysicsFlowDecoder":
        ei = s.edge_index
        angdiff = np.abs(s.X_node[:, ei[0], _VA_IDX] - s.X_node[:, ei[1], _VA_IDX])  # (N,E) |deg|
        loading = s.X_edge[:, :, _EDGE_LOADING_IDX]                                  # (N,E)
        is_line = s.X_edge[0, :, _EDGE_ISXF_IDX] < 0.5
        c = np.zeros(angdiff.shape[1], np.float32)
        for i in range(angdiff.shape[1]):
            if not is_line[i]:
                continue
            x, y = angdiff[:, i], loading[:, i]
            denom = float((x * x).sum())
            c[i] = float((x * y).sum() / denom) if denom > 1e-9 else 0.0
        self.c, self.is_line, self.edge_index = c, is_line, ei
        return self

    def decode_from_arrays(self, x_node: np.ndarray, dva_node: np.ndarray) -> np.ndarray:
        """Δloading_frac per edge from node features (B, nodes, F) and predicted
        node-angle deltas (B, nodes). Anchored to current loading (uses
        |θ_next| − |θ_now| with the fitted slope), so a zero angle-change
        prediction reproduces persistence and the per-line fit offset cancels."""
        ei = self.edge_index
        ang_now = x_node[:, ei[0], _VA_IDX] - x_node[:, ei[1], _VA_IDX]              # signed (B,E)
        ang_next = ang_now + (dva_node[:, ei[0]] - dva_node[:, ei[1]])
        d_loading = self.c[None, :] * (np.abs(ang_next) - np.abs(ang_now))
        d_loading[:, ~self.is_line] = 0.0
        return d_loading.astype(np.float32)

    def decode_loading_delta(self, s: "DynamicsSamples", dva_node: np.ndarray) -> np.ndarray:
        """Predicted Δloading_frac per edge from predicted node-angle deltas (N, nodes)."""
        return self.decode_from_arrays(s.X_node, dva_node)


def evaluate_flow_decode(bundle: DynamicsBundle, decoder: PhysicsFlowDecoder,
                         s: DynamicsSamples) -> dict:
    """Loading-delta MAE on LINE edges: persistence vs free-form head vs physics
    decode (from predicted angles) vs the true-angle upper bound. Skill =
    1 − MAE/persistence. The true-angle row isolates whether the DC decode itself
    is valid (perfect angles); the predicted-angle row is the deployable result."""
    dn, de = bundle.predict_delta(s)
    line = decoder.is_line
    true_dl = s.dY_edge[..., 0][:, line]
    persist = _mae(0.0, true_dl)
    learned = _mae(de[..., 0][:, line], true_dl)
    decoded = _mae(decoder.decode_loading_delta(s, dn[..., 1])[:, line], true_dl)
    decoded_true = _mae(decoder.decode_loading_delta(s, s.dY_node[..., 1])[:, line], true_dl)

    def skill(m):
        return (1.0 - m / persist) * 100.0 if persist > 0 else 0.0

    return {
        "n_line_edges": int(line.sum()),
        "persist": persist, "learned_head": learned,
        "decoded": decoded, "decoded_true_angles": decoded_true,
        "skill_learned": skill(learned), "skill_decoded": skill(decoded),
        "skill_decoded_true": skill(decoded_true),
    }

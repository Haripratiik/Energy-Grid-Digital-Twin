"""Trajectory recording for GridWorld dataset generation.

Each rollout is captured as a sequence of graph snapshots — node features per
bus, edge features per branch, global features, and the action applied at that
step — plus outcome labels. Saved as a compressed ``.npz`` (fixed-shape tensors,
ready for a graph world model) alongside a JSON sidecar of metadata.

This is the bridge from the simulator to learned-dynamics research: the exact
state/action/outcome tuples a world model trains on.
"""

from __future__ import annotations

import json
import os
from typing import TYPE_CHECKING, Optional

import numpy as np

from decisions.models import ProposedAction
from physics.network import BUS_INDEX, BUSES, GENERATORS_CONFIG, LINES, TRANSFORMERS

if TYPE_CHECKING:
    from physics.swing import GridState

# Per-bus node feature layout.
NODE_FEATURES = [
    "voltage_magnitude_pu", "voltage_angle_deg", "power_load_mw",
    "power_generation_mw", "voltage_kv_norm", "is_generator", "status_code",
]
# Per-branch edge feature layout (lines and transformers unified).
EDGE_FEATURES = [
    "from_idx", "to_idx", "flow_mw", "loading_frac", "tripped", "is_transformer",
]
GLOBAL_FEATURES = [
    "sim_time_s", "frequency_hz", "total_generation_mw", "total_load_mw",
    "total_loss_mw", "n_violations",
]
# Compact action encoding: [acted, type_id, target_idx, magnitude_mw].
ACTION_TYPE_IDS = {
    "NO_OP": 0, "LOAD_SHED": 1, "GEN_SETPOINT": 2,
    "LINE_SWITCH": 3, "TRANSFORMER_TAP": 4, "ISLANDING": 5,
}
_STATUS_CODE = {"normal": 0.0, "warning": 1.0, "critical": 2.0, "tripped": 3.0}

# Static edge index (lines then transformers), computed once.
_GEN_BUS_IDS = {g["bus_id"] for g in GENERATORS_CONFIG}


def _static_edges() -> list[tuple[int, int, int]]:
    """(from_node_idx, to_node_idx, is_transformer) for every branch."""
    edges: list[tuple[int, int, int]] = []
    for ln in LINES:
        edges.append((BUS_INDEX[ln.from_bus], BUS_INDEX[ln.to_bus], 0))
    for xf in TRANSFORMERS:
        edges.append((BUS_INDEX[xf.from_bus], BUS_INDEX[xf.to_bus], 1))
    return edges


_EDGES = _static_edges()


class TrajectoryRecorder:
    """Accumulates per-step graph tensors for one rollout."""

    def __init__(self, scenario_id: str, controller: str, seed: int) -> None:
        self.scenario_id = scenario_id
        self.controller = controller
        self.seed = seed
        self._nodes: list[np.ndarray] = []
        self._edges: list[np.ndarray] = []
        self._globals: list[np.ndarray] = []
        self._actions: list[np.ndarray] = []
        self._action_log: list[dict] = []

    def record(self, state: "GridState", actions: list[ProposedAction]) -> None:
        self._nodes.append(self._node_tensor(state))
        self._edges.append(self._edge_tensor(state))
        self._globals.append(self._global_tensor(state))
        self._actions.append(self._action_tensor(actions))
        if actions:
            self._action_log.append({
                "sim_time_s": state.sim_time_s,
                "actions": [a.model_dump() for a in actions],
            })

    # -- tensor builders ----------------------------------------------------

    @staticmethod
    def _node_tensor(state: "GridState") -> np.ndarray:
        rows = np.zeros((len(BUSES), len(NODE_FEATURES)), dtype=np.float32)
        for b in state.buses:
            i = BUS_INDEX[b.id]
            rows[i] = [
                b.voltage_magnitude_pu, b.voltage_angle_deg, b.power_load_mw,
                b.power_generation_mw, b.voltage_kv / 400.0,
                1.0 if b.id in _GEN_BUS_IDS else 0.0,
                _STATUS_CODE.get(b.status, 0.0),
            ]
        return rows

    @staticmethod
    def _edge_tensor(state: "GridState") -> np.ndarray:
        rows = np.zeros((len(_EDGES), len(EDGE_FEATURES)), dtype=np.float32)
        n_lines = len(LINES)
        for i, (fr, to, is_xf) in enumerate(_EDGES):
            if i < n_lines:
                ln = state.lines[i]
                flow, loading, tripped = ln.flow_mw, ln.flow_pct_of_limit, float(ln.tripped)
            else:
                xf = state.transformers[i - n_lines]
                flow = 0.0
                loading = xf.loading_pct / 100.0
                tripped = 1.0 if xf.status == "tripped" else 0.0
            rows[i] = [fr, to, flow, loading, tripped, float(is_xf)]
        return rows

    @staticmethod
    def _global_tensor(state: "GridState") -> np.ndarray:
        n_viol = sum(
            1 for ln in state.lines if ln.flow_pct_of_limit > 1.0 and not ln.tripped
        ) + sum(
            1 for xf in state.transformers if xf.loading_pct > 100.0 and xf.status != "tripped"
        ) + sum(
            1 for b in state.buses if abs(b.voltage_magnitude_pu - 1.0) > 0.10
        )
        return np.array([
            state.sim_time_s, state.system_frequency_hz, state.total_generation_mw,
            state.total_load_mw, state.total_loss_mw, float(n_viol),
        ], dtype=np.float32)

    @staticmethod
    def _action_tensor(actions: list[ProposedAction]) -> np.ndarray:
        if not actions:
            return np.array([0.0, 0.0, 0.0, 0.0], dtype=np.float32)
        a = actions[0]
        try:
            target_idx = float(a.target_rid.rsplit(".", 1)[-1])
        except ValueError:
            target_idx = 0.0
        return np.array([
            1.0, float(ACTION_TYPE_IDS.get(a.action_type, 0)),
            target_idx, float(a.estimated_impact_mw),
        ], dtype=np.float32)

    # -- persistence --------------------------------------------------------

    def save(self, out_dir: str, *, labels: Optional[dict] = None) -> str:
        os.makedirs(out_dir, exist_ok=True)
        base = f"{self.scenario_id}__{self.controller}__seed{self.seed}"
        npz_path = os.path.join(out_dir, base + ".npz")
        np.savez_compressed(
            npz_path,
            node_features=np.stack(self._nodes) if self._nodes else np.zeros((0,)),
            edge_features=np.stack(self._edges) if self._edges else np.zeros((0,)),
            edge_index=np.array([(f, t) for (f, t, _) in _EDGES], dtype=np.int64).T,
            global_features=np.stack(self._globals) if self._globals else np.zeros((0,)),
            actions=np.stack(self._actions) if self._actions else np.zeros((0,)),
        )
        meta = {
            "scenario_id": self.scenario_id,
            "controller": self.controller,
            "seed": self.seed,
            "n_steps": len(self._nodes),
            "n_nodes": len(BUSES),
            "n_edges": len(_EDGES),
            "node_features": NODE_FEATURES,
            "edge_features": EDGE_FEATURES,
            "global_features": GLOBAL_FEATURES,
            "action_encoding": ["acted", "type_id", "target_idx", "magnitude_mw"],
            "action_type_ids": ACTION_TYPE_IDS,
            "action_log": self._action_log,
            "labels": labels or {},
        }
        with open(os.path.join(out_dir, base + ".json"), "w") as f:
            json.dump(meta, f, indent=2)
        return npz_path

    @property
    def n_steps(self) -> int:
        return len(self._nodes)

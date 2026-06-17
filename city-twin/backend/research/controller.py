"""Counterfactual planner: control via the learned world model.

A :class:`LearnedController` evaluates candidate interventions by asking the
trained world model "if I take this action, will the grid be secure a few
seconds from now?" and picks the action with the highest predicted security —
the control application of the world model (Phase 5 of the GridWorld plan).

Imports torch, so it lives in ``research/`` (not ``eval/``) to keep the core
harness dependency-free.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import torch

from decisions.models import ProposedAction
from eval.controllers import GreedyRuleController
from eval.trajectory import TrajectoryRecorder
from .dataset import Samples, Standardizer
from .world_model import GraphWorldModel, graph_scores, train_graph_model


@dataclass
class GraphModelBundle:
    """A trained graph model plus the feature scalers it was fit with."""

    model: GraphWorldModel
    sc_node: Standardizer
    sc_edge: Standardizer
    sc_global: Standardizer
    sc_action: Standardizer

    def _standardize(self, s: Samples) -> Samples:
        import dataclasses
        return dataclasses.replace(
            s,
            X_node=self.sc_node.transform(s.X_node.reshape(-1, s.X_node.shape[-1])).reshape(s.X_node.shape),
            X_edge=self.sc_edge.transform(s.X_edge.reshape(-1, s.X_edge.shape[-1])).reshape(s.X_edge.shape),
            X_global=self.sc_global.transform(s.X_global),
            X_action=self.sc_action.transform(s.X_action),
        )

    def scores(self, s: Samples) -> np.ndarray:
        """Batched P(secure ahead) over a Samples set."""
        return graph_scores(self.model, self._standardize(s))

    def score_one(self, node, edge, glob, action) -> float:
        n = self.sc_node.transform(node)[None]
        e = self.sc_edge.transform(edge)[None]
        g = self.sc_global.transform(glob[None])
        a = self.sc_action.transform(action[None])
        self.model.eval()
        with torch.no_grad():
            logit = self.model(
                torch.as_tensor(n), torch.as_tensor(e),
                torch.as_tensor(g), torch.as_tensor(a),
            )
        return float(torch.sigmoid(logit).item())


def fit_graph_bundle(train: Samples, *, seed: int = 0, epochs: int = 60) -> GraphModelBundle:
    """Fit scalers on train, train the GNN, and return a usable bundle."""
    sc_node = Standardizer().fit(train.X_node.reshape(-1, train.X_node.shape[-1]))
    sc_edge = Standardizer().fit(train.X_edge.reshape(-1, train.X_edge.shape[-1]))
    sc_global = Standardizer().fit(train.X_global)
    sc_action = Standardizer().fit(train.X_action)
    bundle = GraphModelBundle(
        model=GraphWorldModel(
            n_node_feat=train.X_node.shape[-1], n_edge_feat=train.X_edge.shape[-1],
            n_global_feat=train.X_global.shape[-1], n_action_feat=train.X_action.shape[-1],
        ),
        sc_node=sc_node, sc_edge=sc_edge, sc_global=sc_global, sc_action=sc_action,
    )
    bundle.model.set_topology(train.edge_index, n_nodes=train.X_node.shape[1])
    train_graph_model(bundle.model, bundle._standardize(train), seed=seed, epochs=epochs)
    return bundle


class LearnedController:
    """Ranks candidate actions by the world model's predicted security."""

    name = "learned"

    def __init__(self, bundle: GraphModelBundle, candidate_source=None) -> None:
        self._bundle = bundle
        self._candidates = candidate_source or GreedyRuleController()

    def decide(self, state) -> list[ProposedAction]:
        node = TrajectoryRecorder._node_tensor(state)
        edge = TrajectoryRecorder._edge_tensor(state)
        glob = TrajectoryRecorder._global_tensor(state)

        # Candidate menu: do-nothing plus each action the heuristic proposes.
        menu: list[list[ProposedAction]] = [[]]
        for a in self._candidates.decide(state):
            menu.append([a])

        best_actions: list[ProposedAction] = []
        best_p = -1.0
        for acts in menu:
            avec = TrajectoryRecorder._action_tensor(acts)
            p = self._bundle.score_one(node, edge, glob, avec)
            if p > best_p:
                best_p, best_actions = p, acts
        return best_actions

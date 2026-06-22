"""Model-based control via the learned dynamics world model.

A :class:`LearnedDynamicsController` selects actions by *simulating* each
candidate through the learned dynamics model: it predicts the next-state for
do-nothing and for each proposed intervention, scores the predicted limit
violations, and picks the lowest. This is the control payoff of the world model
— planning over a learned model of the grid rather than reacting with fixed
rules. The candidate menu is sourced from the greedy heuristic, so the model's
job is *selection* (including choosing to do nothing when an action would not
help — the failure mode of the over-eager greedy rule).
"""

from __future__ import annotations

import numpy as np

from eval.controllers import GreedyRuleController
from eval.trajectory import TrajectoryRecorder

from .dynamics import _EDGE_LOADING_IDX, _VM_IDX, _action_node_features


class LearnedDynamicsController:
    name = "learned_dynamics"

    def __init__(self, bundle, candidate_source=None, flow_decoder=None) -> None:
        self._bundle = bundle
        self._candidates = candidate_source or GreedyRuleController()
        # If given, LINE loading is DECODED from the model's predicted angles via
        # the DC line-flow law instead of read from the free-form edge head.
        # Experimental: covers lines only (transformers carry no recorded flow);
        # not yet shown to beat persistence with the model's real angles.
        self._flow_decoder = flow_decoder
        if flow_decoder is not None:
            self.name = "learned_dyn+phys"

    def decide(self, state):
        node = TrajectoryRecorder._node_tensor(state)
        edge = TrajectoryRecorder._edge_tensor(state)
        glob = TrajectoryRecorder._global_tensor(state)

        proposed = self._candidates.decide(state)
        # Menu: do-nothing, each single proposed action, and the full set.
        menu = [[]]
        menu += [[a] for a in proposed]
        if len(proposed) > 1:
            menu.append(list(proposed))

        best_acts, best_score = [], float("inf")
        for acts in menu:
            score = self._predicted_violation(node, edge, glob, acts)
            if score < best_score - 1e-9:
                best_score, best_acts = score, acts
        return best_acts

    def _predicted_violation(self, node, edge, glob, acts) -> float:
        avec = TrajectoryRecorder._action_tensor(acts)
        anode = _action_node_features(avec, node.shape[0])[None]
        dn, de = self._bundle.predict_arrays(node[None], edge[None], glob[None], anode)
        if self._flow_decoder is not None:
            d_loading = self._flow_decoder.decode_from_arrays(node[None], dn[:, :, 1])[0]
        else:
            d_loading = de[0, :, 0]
        pred_loading = edge[:, _EDGE_LOADING_IDX] + d_loading
        pred_vm = node[:, _VM_IDX] + dn[0, :, 0]
        overload = float(np.clip(pred_loading - 1.0, 0.0, None).sum())
        v_violation = float(np.clip(np.abs(pred_vm - 1.0) - 0.10, 0.0, None).sum())
        return overload + 5.0 * v_violation

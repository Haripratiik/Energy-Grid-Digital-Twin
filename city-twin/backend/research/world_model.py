"""Action-conditioned models for predicting near-term grid security.

* :class:`GraphWorldModel` — message-passing GNN over the grid topology, with
  the candidate action injected at the graph-readout stage. Tests hypothesis
  H1/H2 from the GridWorld plan: topology + action conditioning help.
* :class:`MLPModel` — same task on flattened (topology-blind) features; the
  control for "does the graph structure actually matter?".

Implemented in pure PyTorch (manual scatter-add message passing) so there is no
torch-geometric dependency. Import this module only when torch is available.
"""

from __future__ import annotations

import numpy as np
import torch
import torch.nn as nn


def _mlp(sizes: list[int]) -> nn.Sequential:
    layers: list[nn.Module] = []
    for i in range(len(sizes) - 1):
        layers.append(nn.Linear(sizes[i], sizes[i + 1]))
        if i < len(sizes) - 2:
            layers.append(nn.ReLU())
    return nn.Sequential(*layers)


class GraphWorldModel(nn.Module):
    def __init__(self, n_node_feat: int, n_edge_feat: int, n_global_feat: int,
                 n_action_feat: int, hidden: int = 32, n_layers: int = 2) -> None:
        super().__init__()
        self.hidden = hidden
        self.n_layers = n_layers
        self.node_enc = nn.Linear(n_node_feat, hidden)
        self.msg = nn.ModuleList([
            _mlp([2 * hidden + n_edge_feat, hidden, hidden]) for _ in range(n_layers)
        ])
        self.upd = nn.ModuleList([
            _mlp([2 * hidden, hidden]) for _ in range(n_layers)
        ])
        # Graph-level head (security prediction).
        self.head = _mlp([hidden + n_global_feat + n_action_feat, hidden, 1])
        # Edge-level head (per-branch overload prediction): endpoint embeddings +
        # the branch's own features + graph/action context.
        self.edge_head = _mlp(
            [2 * hidden + n_edge_feat + n_global_feat + n_action_feat, hidden, 1]
        )

    def set_topology(self, edge_index: np.ndarray, n_nodes: int) -> None:
        # Directed edges for message passing (graph made undirected).
        src = np.concatenate([edge_index[0], edge_index[1]])
        dst = np.concatenate([edge_index[1], edge_index[0]])
        self.register_buffer("src", torch.as_tensor(src, dtype=torch.long), persistent=False)
        self.register_buffer("dst", torch.as_tensor(dst, dtype=torch.long), persistent=False)
        # Original edges (one per branch) for the edge head.
        self.register_buffer("e_src", torch.as_tensor(edge_index[0], dtype=torch.long), persistent=False)
        self.register_buffer("e_dst", torch.as_tensor(edge_index[1], dtype=torch.long), persistent=False)
        deg = np.bincount(dst, minlength=n_nodes).astype(np.float32)
        deg[deg == 0] = 1.0
        self.register_buffer("deg", torch.as_tensor(deg).view(1, n_nodes, 1), persistent=False)
        self.n_nodes = n_nodes

    def _embed(self, x_node, x_edge):
        """Run message passing; return per-node embeddings (B, N, H)."""
        b = x_node.shape[0]
        h = torch.relu(self.node_enc(x_node))
        edge_feat = torch.cat([x_edge, x_edge], dim=1)              # both directions
        for layer in range(self.n_layers):
            h_src = h[:, self.src, :]
            h_dst = h[:, self.dst, :]
            m = self.msg[layer](torch.cat([h_src, h_dst, edge_feat], dim=-1))
            agg = torch.zeros(b, self.n_nodes, self.hidden, device=h.device)
            agg.index_add_(1, self.dst, m)
            agg = agg / self.deg
            h = h + self.upd[layer](torch.cat([h, agg], dim=-1))
            h = torch.relu(h)
        return h

    def forward(self, x_node, x_edge, x_global, x_action):
        """Graph-level security logit (B,)."""
        h = self._embed(x_node, x_edge)
        graph_emb = h.mean(dim=1)
        feats = torch.cat([graph_emb, x_global, x_action], dim=-1)
        return self.head(feats).squeeze(-1)

    def forward_edges(self, x_node, x_edge, x_global, x_action):
        """Per-branch overload logits (B, E)."""
        h = self._embed(x_node, x_edge)                            # (B, N, H)
        b, e = x_edge.shape[0], x_edge.shape[1]
        h_src = h[:, self.e_src, :]                                # (B, E, H)
        h_dst = h[:, self.e_dst, :]
        glob = x_global[:, None, :].expand(b, e, x_global.shape[-1])
        act = x_action[:, None, :].expand(b, e, x_action.shape[-1])
        feats = torch.cat([h_src, h_dst, x_edge, glob, act], dim=-1)
        return self.edge_head(feats).squeeze(-1)                   # (B, E)


class MLPModel(nn.Module):
    """Topology-blind control on flattened features."""

    def __init__(self, n_in: int, hidden: int = 64) -> None:
        super().__init__()
        self.net = _mlp([n_in, hidden, hidden, 1])

    def forward(self, x_flat):
        return self.net(x_flat).squeeze(-1)


# ---------------------------------------------------------------------------
# Training utilities
# ---------------------------------------------------------------------------

def _pos_weight(y: np.ndarray) -> torch.Tensor:
    pos = max(float(y.sum()), 1.0)
    neg = max(float(len(y) - y.sum()), 1.0)
    return torch.tensor(neg / pos, dtype=torch.float32)


def train_graph_model(model: GraphWorldModel, train, val=None, *, epochs: int = 60,
                      lr: float = 1e-3, batch_size: int = 256, seed: int = 0):
    torch.manual_seed(seed)
    opt = torch.optim.Adam(model.parameters(), lr=lr, weight_decay=1e-4)
    loss_fn = nn.BCEWithLogitsLoss(pos_weight=_pos_weight(train.y))

    xn = torch.as_tensor(train.X_node); xe = torch.as_tensor(train.X_edge)
    xg = torch.as_tensor(train.X_global); xa = torch.as_tensor(train.X_action)
    y = torch.as_tensor(train.y)
    n = len(train.y)
    rng = np.random.default_rng(seed)

    for _ in range(epochs):
        model.train()
        for idx in _batches(n, batch_size, rng):
            opt.zero_grad()
            logits = model(xn[idx], xe[idx], xg[idx], xa[idx])
            loss = loss_fn(logits, y[idx])
            loss.backward()
            opt.step()
    return model


def graph_scores(model: GraphWorldModel, s) -> np.ndarray:
    model.eval()
    with torch.no_grad():
        logits = model(
            torch.as_tensor(s.X_node), torch.as_tensor(s.X_edge),
            torch.as_tensor(s.X_global), torch.as_tensor(s.X_action),
        )
        return torch.sigmoid(logits).numpy()


def train_graph_edges(model: GraphWorldModel, train, *, epochs: int = 60,
                      lr: float = 1e-3, batch_size: int = 256, seed: int = 0):
    """Train the edge head to predict per-branch overload (train.Y_edge)."""
    torch.manual_seed(seed)
    opt = torch.optim.Adam(model.parameters(), lr=lr, weight_decay=1e-4)
    Ye = train.Y_edge
    loss_fn = nn.BCEWithLogitsLoss(pos_weight=_pos_weight(Ye.reshape(-1)))

    xn = torch.as_tensor(train.X_node); xe = torch.as_tensor(train.X_edge)
    xg = torch.as_tensor(train.X_global); xa = torch.as_tensor(train.X_action)
    ye = torch.as_tensor(Ye)
    n = len(train.y)
    rng = np.random.default_rng(seed)
    for _ in range(epochs):
        model.train()
        for idx in _batches(n, batch_size, rng):
            opt.zero_grad()
            logits = model.forward_edges(xn[idx], xe[idx], xg[idx], xa[idx])
            loss = loss_fn(logits, ye[idx])
            loss.backward()
            opt.step()
    return model


def graph_edge_scores(model: GraphWorldModel, s) -> np.ndarray:
    """Flattened per-edge overload probabilities (N*E,)."""
    model.eval()
    with torch.no_grad():
        logits = model.forward_edges(
            torch.as_tensor(s.X_node), torch.as_tensor(s.X_edge),
            torch.as_tensor(s.X_global), torch.as_tensor(s.X_action),
        )
        return torch.sigmoid(logits).reshape(-1).numpy()


def train_mlp(model: MLPModel, X: np.ndarray, y: np.ndarray, *, epochs: int = 60,
              lr: float = 1e-3, batch_size: int = 256, seed: int = 0):
    torch.manual_seed(seed)
    opt = torch.optim.Adam(model.parameters(), lr=lr, weight_decay=1e-4)
    loss_fn = nn.BCEWithLogitsLoss(pos_weight=_pos_weight(y))
    Xt = torch.as_tensor(X); yt = torch.as_tensor(y)
    n = len(y)
    rng = np.random.default_rng(seed)
    for _ in range(epochs):
        model.train()
        for idx in _batches(n, batch_size, rng):
            opt.zero_grad()
            loss = loss_fn(model(Xt[idx]), yt[idx])
            loss.backward()
            opt.step()
    return model


def mlp_scores(model: MLPModel, X: np.ndarray) -> np.ndarray:
    model.eval()
    with torch.no_grad():
        return torch.sigmoid(model(torch.as_tensor(X))).numpy()


def _batches(n: int, batch_size: int, rng):
    order = rng.permutation(n)
    for i in range(0, n, batch_size):
        yield order[i:i + batch_size]

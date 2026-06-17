"""Non-graph baselines: persistence and logistic regression (pure numpy)."""

from __future__ import annotations

import numpy as np


def persistence_scores(secure_now: np.ndarray) -> np.ndarray:
    """Predict that current security persists ``horizon`` steps ahead.

    A deliberately strong baseline: grids that are secure now usually stay
    secure, so any learned model must beat this to be worth anything.
    """
    return np.asarray(secure_now, dtype=float)


class LogisticRegression:
    """L2-regularised logistic regression trained by full-batch gradient descent."""

    def __init__(self, lr: float = 0.1, epochs: int = 400, l2: float = 1e-3,
                 seed: int = 0) -> None:
        self.lr = lr
        self.epochs = epochs
        self.l2 = l2
        self.seed = seed
        self.w: np.ndarray | None = None
        self.b: float = 0.0

    @staticmethod
    def _sigmoid(z: np.ndarray) -> np.ndarray:
        return 1.0 / (1.0 + np.exp(-np.clip(z, -30, 30)))

    def fit(self, X: np.ndarray, y: np.ndarray) -> "LogisticRegression":
        rng = np.random.default_rng(self.seed)
        n, d = X.shape
        self.w = rng.normal(0, 0.01, size=d)
        self.b = 0.0
        # Class weighting handles the secure/insecure imbalance.
        pos = max(y.sum(), 1.0)
        neg = max(n - y.sum(), 1.0)
        w_pos, w_neg = n / (2 * pos), n / (2 * neg)
        sample_w = np.where(y == 1, w_pos, w_neg)

        for _ in range(self.epochs):
            p = self._sigmoid(X @ self.w + self.b)
            grad = (sample_w * (p - y))
            gw = X.T @ grad / n + self.l2 * self.w
            gb = grad.sum() / n
            self.w -= self.lr * gw
            self.b -= self.lr * gb
        return self

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        return self._sigmoid(X @ self.w + self.b)

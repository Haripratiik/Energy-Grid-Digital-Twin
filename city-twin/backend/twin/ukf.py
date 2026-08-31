"""Unscented Kalman Filter (Julier–Uhlmann), pure numpy.

The UKF propagates a small deterministic set of *sigma points* through the true
nonlinear process and measurement functions, avoiding the Jacobians an EKF needs
— a better fit for the swing dynamics, which are strongly nonlinear in the rotor
angles. State-independent additive process/measurement noise is assumed.
"""

from __future__ import annotations

from typing import Callable

import numpy as np


class UnscentedKalmanFilter:
    def __init__(
        self,
        n_states: int,
        Q: np.ndarray,
        R: np.ndarray,
        *,
        alpha: float = 1e-3,
        beta: float = 2.0,
        kappa: float = 0.0,
    ) -> None:
        self.n = n_states
        self.Q = Q
        self.R = R
        self.x = np.zeros(n_states)
        self.P = np.eye(n_states)

        # Innovation covariance from the most recent update(). None until one
        # has run: normalized_innovation_sq() is meaningless before there is an
        # innovation to normalise, and an explicit error beats an AttributeError
        # raised from an attribute that was never assigned.
        self._last_S: np.ndarray | None = None

        lam = alpha ** 2 * (n_states + kappa) - n_states
        self._lambda = lam
        c = n_states + lam
        self._gamma = np.sqrt(c)
        # Sigma-point weights.
        self.Wm = np.full(2 * n_states + 1, 1.0 / (2.0 * c))
        self.Wc = self.Wm.copy()
        self.Wm[0] = lam / c
        self.Wc[0] = lam / c + (1.0 - alpha ** 2 + beta)

    # -- sigma points ------------------------------------------------------

    def _sigma_points(self, x: np.ndarray, P: np.ndarray) -> np.ndarray:
        P = 0.5 * (P + P.T) + 1e-9 * np.eye(self.n)   # symmetrize + jitter
        S = np.linalg.cholesky(P)
        pts = np.empty((2 * self.n + 1, self.n))
        pts[0] = x
        for i in range(self.n):
            col = self._gamma * S[:, i]
            pts[1 + i] = x + col
            pts[1 + self.n + i] = x - col
        return pts

    # -- predict / update --------------------------------------------------

    def predict(self, f: Callable[[np.ndarray], np.ndarray]) -> None:
        pts = self._sigma_points(self.x, self.P)
        prop = np.array([f(p) for p in pts])
        x_pred = self.Wm @ prop
        dx = prop - x_pred
        P_pred = (self.Wc[:, None, None] * np.einsum("ki,kj->kij", dx, dx)).sum(0)
        self.x = x_pred
        self.P = P_pred + self.Q

    def update(self, z: np.ndarray, h: Callable[[np.ndarray], np.ndarray]) -> np.ndarray:
        """Correct with measurement ``z``; returns the innovation vector."""
        pts = self._sigma_points(self.x, self.P)
        Z = np.array([h(p) for p in pts])
        z_pred = self.Wm @ Z
        dz = Z - z_pred
        Pzz = (self.Wc[:, None, None] * np.einsum("ki,kj->kij", dz, dz)).sum(0) + self.R
        dx = pts - self.x
        Pxz = (self.Wc[:, None, None] * np.einsum("ki,kj->kij", dx, dz)).sum(0)
        K = Pxz @ np.linalg.inv(Pzz)
        innovation = z - z_pred
        self.x = self.x + K @ innovation
        self.P = self.P - K @ Pzz @ K.T
        self._last_S = Pzz                # innovation covariance (for anomaly score)
        return innovation

    def normalized_innovation_sq(self, innovation: np.ndarray) -> float:
        """Mahalanobis² of the innovation — χ²-distributed when the model fits;
        a spike signals the plant has diverged from the twin's model."""
        if self._last_S is None:
            raise RuntimeError(
                "normalized_innovation_sq() requires a preceding update(): "
                "the innovation covariance does not exist until one has run."
            )
        return float(innovation @ np.linalg.solve(self._last_S, innovation))

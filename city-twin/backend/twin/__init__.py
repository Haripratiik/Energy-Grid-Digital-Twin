"""Digital-twin layer: a twin synchronized to a physical plant via estimation.

Demonstrates the defining property of a digital twin — a model kept continuously
synchronized to a physical asset from a stream of noisy, partial sensor
measurements — using an Unscented Kalman Filter over the nonlinear multi-machine
swing dynamics. The "plant" is ground truth (never directly observed); the
"twin" tracks it, quantifies its own uncertainty, and flags when reality diverges
from the model (anomaly detection).
"""

from .ukf import UnscentedKalmanFilter
from .digital_twin import DigitalTwin, TwinConfig

__all__ = ["UnscentedKalmanFilter", "DigitalTwin", "TwinConfig"]

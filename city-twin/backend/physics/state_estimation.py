"""Weighted-Least-Squares state estimation with bad-data detection.

The other half of "digital twin": a control room never measures the true state.
It collects a *redundant, noisy, occasionally-faulty* set of measurements and
solves for the most likely state by weighted least squares — then runs a
statistical test to catch gross sensor errors.

This is the linear (DC) formulation: the state is the vector of bus voltage
angles (slack fixed at 0), and the measurements are branch active-power flows
and bus power injections, each with a known variance:

    z = H·θ + e ,   e ~ N(0, R)
    θ̂ = (Hᵀ R⁻¹ H)⁻¹ Hᵀ R⁻¹ z              (WLS estimate)

Bad data is detected by the **chi-squared test** on the weighted residual and
localized by the **largest normalized residual** (LNR). It reuses the DC network
model (incidence + susceptances) from :mod:`physics.lodf`.
"""

from __future__ import annotations

import numpy as np
from pydantic import BaseModel
from scipy.stats import chi2

from .lodf import DCSystem


class EstimationResult(BaseModel):
    n_measurements: int
    n_states: int
    redundancy: float                 # measurements / states
    objective_j: float                # weighted residual sum of squares
    chi2_threshold: float             # detection threshold at the confidence level
    bad_data_detected: bool
    max_normalized_residual: float
    flagged_measurement: int | None   # index of the most suspect measurement
    angle_rmse_rad: float             # estimated vs true bus angles
    flow_rmse_pu: float               # estimated vs true branch flows
    measurement_noise_pu: float       # input sensor noise (for comparison)


class DCStateEstimator:
    """Linear WLS state estimator over a :class:`DCSystem`."""

    def __init__(self, dc: DCSystem) -> None:
        self.dc = dc
        self.keep = dc._keep
        self.ns = len(self.keep)                       # number of estimated angles

        A = dc.A
        b = dc.b
        # True bus angles implied by the network injections (reference state).
        B = A.T @ (b[:, None] * A)
        self._Bri = np.linalg.inv(B[np.ix_(self.keep, self.keep)])
        self.theta_true = np.zeros(dc.n)
        self.theta_true[self.keep] = self._Bri @ dc.P[self.keep]

        # Measurement model H (rows = measurements, cols = estimated angles):
        #   branch flows:  f_l = b_l (θ_from − θ_to)
        #   bus injections: P_i = (B θ)_i
        H_flow = (b[:, None] * A)[:, self.keep]        # (L, ns)
        H_inj = B[np.ix_(self.keep, self.keep)]        # (ns, ns)
        self.H = np.vstack([H_flow, H_inj])            # (L+ns, ns)
        self.n_meas = self.H.shape[0]
        self._n_flow = A.shape[0]

        # True (noise-free) measurements.
        self.z_true = self.H @ self.theta_true[self.keep]

    # -- measurement simulation -------------------------------------------

    def simulate_measurements(
        self, noise_pu: float = 0.02, seed: int = 0,
        bad_index: int | None = None, bad_error_pu: float = 0.5,
    ) -> tuple[np.ndarray, np.ndarray]:
        """Return (z, sigma): noisy measurements and their std-devs.

        If ``bad_index`` is given, that measurement gets a gross additive error
        to exercise bad-data detection.
        """
        rng = np.random.default_rng(seed)
        sigma = np.full(self.n_meas, noise_pu)
        z = self.z_true + rng.normal(0, noise_pu, self.n_meas)
        if bad_index is not None:
            z[bad_index] += bad_error_pu
        return z, sigma

    # -- estimation --------------------------------------------------------

    def estimate(self, z: np.ndarray, sigma: np.ndarray, *, confidence: float = 0.99) -> EstimationResult:
        Rinv = 1.0 / sigma ** 2
        G = self.H.T @ (Rinv[:, None] * self.H)        # gain matrix
        Ginv = np.linalg.inv(G)
        theta_r = Ginv @ (self.H.T @ (Rinv * z))       # WLS estimate

        residual = z - self.H @ theta_r
        J = float(residual @ (Rinv * residual))        # chi-squared statistic
        dof = max(self.n_meas - self.ns, 1)
        threshold = float(chi2.ppf(confidence, dof))

        bad_data = J > threshold

        # Normalized residuals for bad-data localization.
        #   Ω = R − H G⁻¹ Hᵀ  (residual covariance); r_N,i = |r_i| / √Ω_ii
        HGHt = np.einsum("ij,jk,ik->i", self.H, Ginv, self.H)   # diag(H G⁻¹ Hᵀ)
        omega = sigma ** 2 - HGHt
        omega = np.where(omega > 1e-12, omega, 1e-12)
        r_norm = np.abs(residual) / np.sqrt(omega)
        max_rn = float(r_norm.max())
        # Localize only once the chi-squared test has *detected* bad data — the
        # standard detect-then-identify procedure (avoids false flags from the
        # expected tail exceedances across many measurements).
        flagged = int(np.argmax(r_norm)) if (bad_data and max_rn > 3.0) else None

        theta_est = np.zeros(self.dc.n)
        theta_est[self.keep] = theta_r
        angle_rmse = float(np.sqrt(np.mean((theta_est - self.theta_true) ** 2)))
        flow_true = self.z_true[: self._n_flow]
        flow_est = (self.H @ theta_r)[: self._n_flow]
        flow_rmse = float(np.sqrt(np.mean((flow_est - flow_true) ** 2)))

        return EstimationResult(
            n_measurements=self.n_meas, n_states=self.ns,
            redundancy=round(self.n_meas / self.ns, 2),
            objective_j=round(J, 2), chi2_threshold=round(threshold, 2),
            bad_data_detected=bad_data,
            max_normalized_residual=round(max_rn, 2),
            flagged_measurement=flagged,
            angle_rmse_rad=angle_rmse, flow_rmse_pu=flow_rmse,
            measurement_noise_pu=sigma.mean(),
        )


def _main() -> None:
    import pandapower.networks as nw

    dc = DCSystem.from_pandapower(nw.case118())
    est = DCStateEstimator(dc)
    print("WLS state estimation — IEEE-118")
    print(f"  measurements={est.n_meas}  states={est.ns}  "
          f"redundancy={est.n_meas / est.ns:.2f}")

    z, sigma = est.simulate_measurements(noise_pu=0.02, seed=1)
    clean = est.estimate(z, sigma)
    print(f"\n[clean] J={clean.objective_j} (threshold {clean.chi2_threshold}) "
          f"-> bad data: {clean.bad_data_detected}")
    print(f"  flow RMSE {clean.flow_rmse_pu:.4f} pu vs sensor noise "
          f"{clean.measurement_noise_pu:.4f} pu (redundancy denoises)")
    print(f"  angle RMSE {clean.angle_rmse_rad:.4f} rad")

    zb, sb = est.simulate_measurements(noise_pu=0.02, seed=1, bad_index=42, bad_error_pu=0.5)
    bad = est.estimate(zb, sb)
    print(f"\n[gross error injected at measurement 42] J={bad.objective_j} "
          f"-> bad data: {bad.bad_data_detected}")
    print(f"  largest normalized residual {bad.max_normalized_residual} "
          f"at measurement {bad.flagged_measurement}")


if __name__ == "__main__":
    _main()

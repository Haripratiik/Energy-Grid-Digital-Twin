"""Classical multi-machine transient-stability model.

Each generator is represented as a constant voltage ``E∠δ`` behind its transient
reactance ``X'd``; loads are converted to constant-impedance shunts; the network
is **Kron-reduced** to the generator internal nodes, giving a reduced admittance
matrix ``Y_red``. The electrical power of each machine is then a closed-form
function of all rotor angles:

    Pe_i = |E_i| · Σ_j |E_j| · ( G_ij·cos(δ_i − δ_j) + B_ij·sin(δ_i − δ_j) )

and each machine obeys the swing equation

    dδ_i/dt = ω_i ,   (2H_i/ω_s)·dω_i/dt = Pm_i − Pe_i − D_i·ω_i .

This is the textbook model for transient-stability and **dynamic state
estimation**. Crucially it is fully analytical and vectorised — fast enough to
propagate the dozens of sigma points an Unscented Kalman Filter needs per step,
unlike the pandapower-coupled simulator.

The operating point (E, δ₀, Pm) is derived from the *validated* IEEE-9 power-flow
solution, so the model is anchored to a recognized benchmark.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

OMEGA_S = 2.0 * np.pi * 60.0   # synchronous speed (rad/s)

# Standard WSCC 9-bus machine data (Anderson & Fouad), ordered by generator bus.
_H = np.array([23.64, 6.40, 3.01])         # inertia constants (s)
_XD_PRIME = np.array([0.0608, 0.1198, 0.1813])  # transient reactances (pu)
_D = np.array([0.1, 0.1, 0.1])             # damping — lightly-damped ~1.3 Hz modes


@dataclass
class ClassicalMultiMachine:
    """Analytical multi-machine swing model on the reduced network."""

    E: np.ndarray        # internal EMF magnitudes (m,)
    delta0: np.ndarray   # equilibrium rotor angles (m,)
    Pm: np.ndarray       # mechanical power = Pe at equilibrium (m,)
    M: np.ndarray        # 2H/ω_s inertia coefficients (m,)
    D: np.ndarray        # damping (m,)
    G: np.ndarray        # Re(Y_red) (m, m)
    B: np.ndarray        # Im(Y_red) (m, m)

    @property
    def m(self) -> int:
        return len(self.E)

    @property
    def n_states(self) -> int:
        return 2 * self.m

    # -- dynamics ----------------------------------------------------------

    def electrical_power(self, delta: np.ndarray) -> np.ndarray:
        """Pe for every machine given rotor angles (vectorised)."""
        dij = delta[:, None] - delta[None, :]
        EE = self.E[:, None] * self.E[None, :]
        return (EE * (self.G * np.cos(dij) + self.B * np.sin(dij))).sum(axis=1)

    def derivatives(self, x: np.ndarray) -> np.ndarray:
        """dx/dt for state x = [δ(m), ω(m)]."""
        m = self.m
        delta, omega = x[:m], x[m:]
        ddelta = omega
        domega = (self.Pm - self.electrical_power(delta) - self.D * omega) / self.M
        return np.concatenate([ddelta, domega])

    def step_rk4(self, x: np.ndarray, dt: float) -> np.ndarray:
        """One RK4 step (pure function — safe for sigma-point propagation)."""
        k1 = self.derivatives(x)
        k2 = self.derivatives(x + 0.5 * dt * k1)
        k3 = self.derivatives(x + 0.5 * dt * k2)
        k4 = self.derivatives(x + dt * k3)
        return x + (dt / 6.0) * (k1 + 2 * k2 + 2 * k3 + k4)

    def equilibrium_state(self) -> np.ndarray:
        return np.concatenate([self.delta0, np.zeros(self.m)])

    # -- construction ------------------------------------------------------

    @classmethod
    def from_ieee9(cls) -> "ClassicalMultiMachine":
        """Build the reduced model from the solved IEEE-9 power flow."""
        import pandapower as pp
        import pandapower.networks as nw

        net = nw.case9()
        pp.runpp(net, algorithm="nr", calculate_voltage_angles=True)

        ic = net._ppc["internal"]
        Ybus = np.asarray(ic["Ybus"].todense())          # (n, n) complex
        n = Ybus.shape[0]
        vm = net.res_bus.vm_pu.values
        va = np.deg2rad(net.res_bus.va_degree.values)
        V = vm * np.exp(1j * va)                           # complex bus voltages
        base = net.sn_mva

        # Map generators (ext_grid + gen) to their buses, ordered by bus index.
        gen_buses, Pg, Qg = [], [], []
        for _, r in net.res_ext_grid.iterrows():
            b = int(net.ext_grid.at[r.name, "bus"])
            gen_buses.append(b); Pg.append(r.p_mw); Qg.append(r.q_mvar)
        for _, r in net.res_gen.iterrows():
            b = int(net.gen.at[r.name, "bus"])
            gen_buses.append(b); Pg.append(r.p_mw); Qg.append(r.q_mvar)
        order = np.argsort(gen_buses)
        gen_buses = np.array(gen_buses)[order]
        Pg = np.array(Pg)[order] / base
        Qg = np.array(Qg)[order] / base

        # Loads → constant-impedance shunts added to the bus diagonal.
        Yaug = Ybus.copy()
        Sload = np.zeros(n, dtype=complex)
        for _, r in net.res_load.iterrows():
            b = int(net.load.at[r.name, "bus"])
            Sload[b] += (r.p_mw + 1j * r.q_mvar) / base
        for b in range(n):
            if abs(V[b]) > 1e-9 and abs(Sload[b]) > 0:
                Yaug[b, b] += np.conj(Sload[b]) / (abs(V[b]) ** 2)

        # Augment with m internal generator nodes behind X'd.
        m = len(gen_buses)
        xd = _XD_PRIME[:m]
        Yfull = np.zeros((n + m, n + m), dtype=complex)
        Yfull[:n, :n] = Yaug
        E = np.zeros(m, dtype=complex)
        for i, b in enumerate(gen_buses):
            y = 1.0 / (1j * xd[i])
            g = n + i
            Yfull[g, g] += y
            Yfull[b, b] += y
            Yfull[g, b] -= y
            Yfull[b, g] -= y
            # Internal EMF from the operating point: E = V + jX'd·I, I = conj(S/V).
            Sgi = Pg[i] + 1j * Qg[i]
            Igi = np.conj(Sgi / V[b])
            E[i] = V[b] + 1j * xd[i] * Igi

        # Kron-reduce: keep internal nodes (last m), eliminate the n buses.
        keep = slice(n, n + m)
        elim = slice(0, n)
        Ykk = Yfull[keep, keep]
        Yke = Yfull[keep, elim]
        Yek = Yfull[elim, keep]
        Yee = Yfull[elim, elim]
        Y_red = Ykk - Yke @ np.linalg.solve(Yee, Yek)

        E_mag = np.abs(E)
        delta0 = np.angle(E)
        G, B = Y_red.real, Y_red.imag
        M = 2.0 * _H[:m] / OMEGA_S

        model = cls(E=E_mag, delta0=delta0, Pm=np.zeros(m), M=M, D=_D[:m], G=G, B=B)
        # Set Pm = Pe(δ₀) so the system starts in exact equilibrium.
        model.Pm = model.electrical_power(delta0)
        return model

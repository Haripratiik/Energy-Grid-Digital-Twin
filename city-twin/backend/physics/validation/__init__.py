"""Physics validation against recognized benchmarks.

Two independent validations establish that the simulation physics are correct,
not merely plausible:

* ``powerflow_benchmark`` — solves the standard IEEE test systems and proves the
  AC power-flow solution is correct (independent solvers agree to ~1e-9, nodal
  power is conserved, and total losses match published reference values).
* ``dynamics_benchmark`` — validates the swing-equation integrator against the
  *analytical* small-signal oscillation frequency of a single-machine-infinite-
  bus system, and demonstrates turbine-governor primary frequency response.
"""

from .powerflow_benchmark import PowerFlowValidation, validate_powerflow
from .dynamics_benchmark import (
    SMIBValidation, GovernorValidation, validate_smib, validate_governor,
)

__all__ = [
    "PowerFlowValidation", "validate_powerflow",
    "SMIBValidation", "validate_smib",
    "GovernorValidation", "validate_governor",
]

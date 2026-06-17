"""GridWorld evaluation & dataset-generation harness.

A headless, deterministic layer over the grid simulator that:

* replays reproducible, seeded fault scenarios (``scenario.py``),
* drives them under pluggable control policies (``controllers.py``),
* records full state/action/outcome trajectories (``trajectory.py``),
* scores rollouts on grid-stability metrics (``metrics.py``),
* and compares controllers head-to-head (``runner.py`` / ``harness.py``).

This is both the evaluation harness for the autonomous decision engine *and*
the dataset-generation core for the GridWorld learned-world-model research
extension — the two are the same machinery.
"""

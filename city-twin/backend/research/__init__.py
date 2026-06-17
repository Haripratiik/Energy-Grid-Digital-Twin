"""GridWorld learned-world-model research layer.

Trains action-conditioned models on the trajectory datasets produced by
``eval.generate_dataset`` to predict near-term grid security, and benchmarks a
graph neural world model against non-graph and persistence baselines.

The research question (from the GridWorld plan): can a topology-aware,
action-conditioned model predict how the grid evolves under interventions well
enough to support control — beating models that ignore graph structure?

Modules:
* ``dataset``     — load .npz trajectories into supervised samples + splits.
* ``metrics``     — classification metrics (numpy, no sklearn dependency).
* ``baselines``   — persistence + logistic-regression baselines (numpy).
* ``world_model`` — action-conditioned message-passing GNN (pure PyTorch).
* ``train``       — train/eval CLI producing the comparison table.
"""

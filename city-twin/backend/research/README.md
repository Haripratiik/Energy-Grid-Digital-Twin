# GridWorld — Learned World Model

The research extension: can a learned, **action-conditioned** model of the grid
predict how it evolves under interventions well enough to support control? This
turns the simulator into a physical-AI benchmark — the same state → action →
future-prediction → evaluation loop that underlies embodied world models, in a
non-robot physical domain.

## The pipeline

```
eval.generate_dataset   ──>  .npz trajectories (graph state, action, outcome labels)
        │
        ▼
research.dataset        ──>  supervised samples: predict "secure H steps ahead"
        │                     splits: by-trajectory (no leakage) + held-out fault family
        ▼
research.{baselines,world_model}
        │   persistence · logistic · MLP (topology-blind) · GNN (action-conditioned)
        ▼
research.train          ──>  benchmark table (accuracy / F1 / AUROC)
        │
        ▼
research.controller     ──>  LearnedController: rank candidate actions by the model's
                              predicted security — the counterfactual planner
```

## Running it

```bash
cd city-twin/backend
pip install -r requirements-research.txt          # adds CPU torch

python -m eval.generate_dataset --out data/gw --seeds 8     # generate trajectories
python -m research.train --data data/gw                     # by-trajectory split
python -m research.train --data data/gw --holdout-family trafo_trip   # generalization
```

The dataset/metrics/baselines run without torch; the MLP and GNN are skipped if
torch is absent (and their tests `importorskip`), so core CI stays dependency-free.

## Task

For each timestep, given the current graph state (per-bus node features, per-branch
edge features, global features) and the action taken, predict whether the grid is
**secure** (zero limit violations) `horizon` steps (default 2 s) later.

## Models

- **persistence** — assume current security persists. A deliberately strong baseline.
- **logistic / MLP** — on flattened features (global + action + node/edge aggregates);
  topology-blind controls.
- **GNN** ([world_model.py](world_model.py)) — message passing over the grid graph
  (`node encoder → k× {edge-conditioned messages, mean-aggregate, update} → mean pool`),
  with the candidate action injected at readout. Pure PyTorch, no torch-geometric.

## Findings (honest)

On a dataset of 48 trajectories (6 fault families × 4 seeds × 2 controllers):

**By-trajectory split** (train/test share fault families):

| model | acc | F1 | AUROC |
|---|---|---|---|
| persistence | 0.948 | 0.891 | 0.967 |
| logistic | 0.948 | 0.891 | 0.979 |
| **mlp** | **0.975** | **0.944** | **0.997** |
| gnn | 0.954 | 0.901 | 0.984 |

**Held-out family** (`trafo_trip` never seen in training):

| model | acc | F1 | AUROC |
|---|---|---|---|
| persistence | 0.903 | 0.824 | 0.894 |
| logistic | 0.710 | 0.182 | 0.918 |
| mlp | 0.839 | 0.656 | 0.935 |
| gnn | 0.710 | 0.182 | 0.911 |

**Interpretation.** All learned models beat persistence on AUROC, and on the
held-out family they *rank* unseen-fault risk better than persistence (AUROC
0.91–0.94 vs 0.89) — but fixed-threshold calibration degrades sharply under
distribution shift (F1 collapses). At this short horizon the GNN does **not**
beat the topology-blind MLP: near-term security is largely readable from
aggregate features, so explicit topology adds little. This is a genuine result,
not a tuned demo — the deliverable is the rigorous evaluation harness, including
the generalization split that *reveals* the calibration-shift failure.

## Where the GNN should earn its keep (future work)

The short-horizon, aggregate-readable task under-uses topology. The promising
directions, in order:

1. **Harder, topology-dependent targets** — predict *which* element overloads, or
   cascade depth/path, not just a global secure/insecure bit.
2. **Longer horizons** — multi-step rollout where local aggregates stop sufficing.
3. **More data + held-out *assets*** (unseen fault locations), where graph
   structure should generalize better than memorized flat patterns.
4. **Calibration under shift** — temperature scaling / threshold transfer.
5. **Close the control loop** — evaluate `LearnedController` head-to-head against
   `greedy_rule` in the harness across families.

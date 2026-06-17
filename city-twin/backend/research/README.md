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
python -m research.train --data data/gw                              # security, by-trajectory
python -m research.train --data data/gw --holdout-family trafo_trip  # security, generalization
python -m research.train --data data/gw --target overload            # per-branch overload
python -m research.train --data data/gw --target overload --holdout-family trafo_trip
```

The dataset/metrics/baselines run without torch; the MLP and GNN are skipped if
torch is absent (and their tests `importorskip`), so core CI stays dependency-free.

## Tasks

Two prediction targets, selected with `--target`:

- **`security`** (default) — *graph-level*: will the grid be secure (zero limit
  violations) `horizon` steps ahead? Largely readable from aggregate features.
- **`overload`** — *edge-level*: for **each** branch, will it be thermally
  overloaded `horizon` steps ahead? A genuinely topology-structured output where
  multi-hop context (post-contingency rerouting) should matter — the task that
  actually exercises the GNN's inductive bias.

Both use the current graph state (per-bus node features, per-branch edge
features, global features) and the action taken; horizon defaults to 2 s.

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

**Interpretation (security task).** All learned models beat persistence on AUROC,
and on the held-out family they *rank* unseen-fault risk better than persistence
(AUROC 0.91–0.94 vs 0.89) — but fixed-threshold calibration degrades sharply
under distribution shift (F1 collapses). At this short horizon the GNN does
**not** beat the topology-blind MLP: near-term security is largely readable from
aggregate features, so explicit topology adds little.

### Per-branch overload task (`--target overload`)

**By-trajectory split** (edge-level; ~256k edge predictions):

| model | acc | F1 | AUROC |
|---|---|---|---|
| persistence | 0.997 | 0.924 | 0.950 |
| logistic | 0.931 | 0.358 | 0.995 |
| mlp | 0.992 | 0.825 | 0.999 |
| gnn | 0.986 | 0.742 | 0.999 |

**Held-out family** (`trafo_trip`):

| model | acc | F1 | AUROC |
|---|---|---|---|
| persistence | 0.997 | **0.926** | 0.952 |
| logistic | 0.931 | 0.396 | **0.974** |
| mlp | 0.971 | 0.512 | 0.859 |
| gnn | 0.962 | 0.218 | 0.887 |

**Interpretation (overload task).** In-distribution, the learned models rank
overload risk far better than persistence (AUROC 0.99+ vs 0.95) — they
anticipate *new* overloads, not just persistence — with GNN and MLP tied. Under
held-out-family shift the picture is more honest: the strong simple baselines
win overall (persistence on F1/calibration, logistic on AUROC), and the neural
nets overfit to seen families. But **the GNN generalizes better than the MLP**
(AUROC 0.887 vs 0.859) — a modest, real signal that topological inductive bias
aids cross-family transfer, consistent with hypothesis H3. The honest headline:
strong baselines are hard to beat here, the neural nets need more data/regular-
isation to generalize, and the graph structure helps *relatively* exactly where
the theory predicts.

## Where the GNN should earn its keep (future work)

The per-branch overload task (above) already moves to a topology-structured
target and shows the GNN generalizing better than the MLP. Remaining directions:

1. **More data + regularisation** — the neural nets overfit at 4 seeds; the
   in-distribution AUROC (0.999) vs held-out (0.86–0.89) gap says the bottleneck
   is data/regularisation, not capacity. Generate 8–16 seeds and add dropout.
2. **Held-out *assets*** (unseen fault locations within a family), where a
   topology-aware model should generalize better than memorized flat patterns.
3. **Cascade-depth / which-element-fails-first** targets under `GRID_PROTECTION`,
   where multi-hop reasoning is unavoidable.
4. **Longer horizons** — multi-step rollout where local aggregates stop sufficing.
5. **Calibration under shift** — temperature scaling / threshold transfer (the
   F1 collapse is a calibration, not ranking, failure).
6. **Close the control loop** — evaluate `LearnedController` head-to-head against
   `greedy_rule` in the harness across families.

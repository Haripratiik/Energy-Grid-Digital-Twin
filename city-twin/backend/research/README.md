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

### Closing the loop: control (`research.control_eval`)

The ultimate question — does the learned model support *action*? We wrap the
trained security model as a `LearnedController` (counterfactual planner: score
each candidate action by predicted P(secure ahead), pick the best) and run it
head-to-head against the baselines in the simulator, across all six scenarios:

| controller | mean cost | wins |
|---|---|---|
| learned | 3365.6 | 1/6 |
| do_nothing | 3365.7 | 3/6 |
| greedy_rule | 3538.2 | 2/6 |

**Interpretation.** The learned planner behaves almost identically to do-nothing:
its global security model can't confidently predict that an intervention will
*improve* future security, so it defaults to `NO_OP`. That has an upside — it
avoids `greedy`'s wasteful over-shedding on the unrecoverable line/compound
faults — but a decisive downside: it **misses the `trafo_trip` recovery** that
`greedy` achieves (cost 6539 vs 2032), because it never predicts the shedding
action will help. The lesson is precise and motivates the roadmap above: a
control-useful world model must predict action *effects on specific
constraints* (the per-branch overload target), not a single global secure/
insecure bit. The loop is closed and measured — the result honestly bounds what
this model can do for control today.

## Action-conditioned **dynamics** world model (next-state prediction)

The security/overload models above predict a *binary label* `H` steps ahead, with
the action injected only at readout, trained on near-actionless data — and their
learned controller collapsed to no-op. This extension
([dynamics.py](dynamics.py), [dynamics_controller.py](dynamics_controller.py))
fixes all three weaknesses and is the more faithful "world model":

1. **Dense exploratory data** — a new `ExploratoryController` perturbs the grid
   with a random valid action every cycle, lifting action density from **1.1% →
   14.2%** of steps, so the model can actually see action *effects*.
2. **Next-state target, not a label** — it predicts the per-bus voltage
   magnitude & angle and per-branch loading **deltas**, so it can be rolled out
   and planned over.
3. **Action injected at the acted node** — the action is a per-node feature that
   enters message passing, so its effect propagates through the topology.

```bash
python -m eval.generate_dataset --out data/gw_dyn --explore-seeds 6   # dense (s,a) data
python -m research.train_dynamics --data data/gw_dyn --horizon 20     # next-state benchmark
python -m research.dynamics_control_eval --data data/gw_dyn           # closed-loop control
```

### Findings (honest, with caveats)

Next-state MAE vs the **persistence** baseline (predict no change), 48
trajectories / ~16k transitions. "skill" = 1 − MAE/persistence (positive = beats
persistence). **Single seed** — see caveats below; these are preliminary.

**Horizon sweep** (held-out *trajectories*; same fault families in train+test):

| horizon | slice | Vm skill | Va (angle) skill | loading skill |
|---|---|---:|---:|---:|
| 1 (0.1 s) | all | −152% | −40% | −30% |
| 10 (1.0 s) | disturbed | −3% | +6% | −8% |
| 20 (2.0 s) | all | −2% | +5% | −4% |
| 20 (2.0 s) | disturbed | +7% | +10% | ~0% |

**Held-out fault family** (`trafo_trip` never seen in training — the honest
generalization test, H=20):

| slice | Vm skill | Va (angle) skill | loading skill |
|---|---:|---:|---:|
| all | −1% | **+8%** | −2% |
| disturbed | −17% | **+7%** | −9% |
| action-bearing | −6% | **+11%** | −3% |

**Significance (trajectory bootstrap, 90% CI on skill% — `--bootstrap`):** on the
held-out family, overall **Va = [+3.4, +7.8, +12.1] — entirely above zero, so the
angle-dynamics generalization is statistically significant**, not single-seed
luck. Vm = [−4.9, −1.2, +2.4] and loading = [−5.7, −1.8, +1.4] **straddle zero →
indistinguishable from persistence** (confirmed null). On disturbed states Vm and
loading are *significantly worse* than persistence (CIs entirely negative) — the
model overfits those quantities to seen families. The bootstrap resamples whole
test *trajectories*, so it respects grouping rather than over-counting correlated
steps.

**Interpretation.** The result tracks the physics. At 100 ms the grid is
quasi-static (Vm moves ~6e-5), so "predict no change" is nearly unbeatable. The
genuine, *generalizing* signal is **voltage angle** — the swing-equation
quantity that actually moves: the model beats persistence on angle by +5–11%
**even on a fault family it never trained on**, and a trajectory bootstrap puts
the 90% CI at **[+3.4%, +12.1%] — entirely above zero**, so this is a
statistically real, transferable result, not memorized patterns or single-seed
luck. Voltage magnitude and line **loading**, which are quasi-static and
power-flow-set, do **not** generalize — their bootstrap CIs straddle zero
(or are negative on disturbed states); the model overfits them to seen families.

**Action ablation (suggestive, not yet conclusive).** Zeroing the action at
inference *slightly* degrades action-bearing-step prediction (H=20: Vm
0.143→0.144, ~0.7%). That is directionally right but **within single-seed
noise** — it is weak evidence on real data. The synthetic unit test
([test_dynamics.py](../tests/test_dynamics.py)) proves the machinery detects a
*planted* action effect; confirming it on real data needs a magnitude
**dose-response** test, not one sub-1% MAE delta.

**Caveats (what an honest reviewer will rightly attack — and the fix queue).**
- **Single seed for the point estimates** (all tables are `seed=0`), but the
  **trajectory bootstrap above settles significance**: the angle generalization
  CI excludes zero (real), the Vm/loading CIs include zero (null). A multi-seed
  sweep would additionally bound optimizer-init variance — worth doing, but the
  headline no longer rests on one seed.
- **Multi-action contamination at long horizons.** A sample conditions on the
  action at `t` but targets `state_{t+20}`; the exploratory policy acts every
  ~5 steps, so other actions land inside the window. The (s,a)→s_{t+H} target is
  confounded at H=20. The clean signal is at short H (where persistence wins) —
  an inherent tension. Fix: build only windows with no intervening action, or
  condition on the action *sequence*. *Next.*
- The headline "held-out trajectories" split shares fault families across
  train/test; the **held-out-family** table above is the honest generalization
  number and is what should be cited.

### Closing the loop: model-based control ([dynamics_control_eval.py](dynamics_control_eval.py))

A `LearnedDynamicsController` selects actions by *simulating* each candidate
through the learned dynamics model — predicting the ~1 s-ahead state and scoring
its limit violations — then picks the lowest, **including doing nothing when no
action is predicted to help**. Run head-to-head against do-nothing and the
greedy rule in the real simulator (protection on, so overloads cascade):

| scenario | do_nothing | greedy_rule | learned_dynamics |
|---|---:|---:|---:|
| gen_dropout_gas3 | 210.4 | 210.3 | 210.4 |
| line_trip_central | 6546.7 | 9351.0 | **6546.7** |
| load_spike_industrial | 46.5 | 46.5 | 46.5 |
| trafo_trip_radial | 6538.9 | **2031.8** | 7382.7 |
| compound_gen_then_line | 6782.4 | 9520.4 | 6876.1 |
| renewable_volatility_load | 69.1 | 69.1 | 69.1 |
| **TOTAL** | **20194** | 21229 | 21131 |

**Interpretation (honest — no positive control result yet).** The planner
**loses to do-nothing overall** (21131 vs 20194); its only "win" is a 0.5% edge
over `greedy_rule`, and that comes from *greedy harming itself* by over-shedding
on the meshed `line_trip`/`compound` faults, not from skilful planning. The
planner correctly declines those harmful sheds (matching do-nothing) but
**misses the `trafo_trip` recovery** greedy achieves (7383 vs 2032). The cause is
*precisely diagnosed*, not hand-waved: because line-**loading** prediction is no
better than persistence (~0% skill above), every candidate action scores an
almost identical predicted overload, so the planner can't tell that shedding
would relieve the transformer overload — and defaults to no-op. So the world
model adds **no control value today**, and the bottleneck is specific: make
loading predictable. The right fix (below) is a physics-informed flow head —
predict nodal injection changes and decode line flows via the project's existing
**PTDF/LODF** factors ([physics/lodf.py](../physics/lodf.py)), so flows stay
valid through line trips — rather than a free-form edge head learning loading
from scratch.

### Physics-informed flow head (built)

The loading bottleneck has a precise fix, now implemented
([dynamics.py](dynamics.py) `PhysicsFlowDecoder`): don't learn loading with a
free-form edge head — **decode it from the model's predicted bus angles** via the
DC line-flow law. Line flow is a deterministic function of the angle difference
across a line (`P_ij = b_ij·(θ_i−θ_j)`, so `loading ≈ c_i·|θ_i−θ_j|`), and angle
is the one quantity the model predicts significantly and generalizably. The
per-line susceptance `c_i` is fit from data (one OLS coefficient per line), which
absorbs the AC solver's *effective* parameters automatically.

Held-out family, line-loading-delta MAE, skill vs persistence:

| loading predictor | skill |
|---|---:|
| free-form edge head | −2% |
| physics decode, model's angles | −42% |
| **physics decode, _true_ angles** | **+90%** |

Read the +90% carefully: it feeds the decoder the **true** next-angles, so it is
an **oracle/invertibility check** — it shows that *if* the angles were perfect the
decode recovers loading, i.e. the algebra is right. It does **not** show the
deployable method works.

The decode is then made a **differentiable layer trained end-to-end with a
loading-decode loss** (`fit_dynamics(flow_loss_weight=…)`): the model is penalised
when the loadings decoded from its angles miss the truth, so it learns angles that
*decode well* — physics in the loss, not just the readout. This moves the
deployable (predicted-angle) decode from **−42% → −11%** at weight 1.0 — real
movement, **but still worse than persistence (0%)**: as it stands the flow head
does *not yet* beat the trivial baseline on real model angles.

**Honest status — built and instructive, NOT yet a demonstrated win:**
- The **only positive number (+90%) uses the ground-truth angles**; with the
  model's real angles the decode is −11% (and the free-form head −2%) — neither
  beats persistence.
- **Control was not re-run** with the physics head. The planner integration is
  wired (`LearnedDynamicsController(flow_decoder=…)`, a 4th controller in
  `dynamics_control_eval`) and smoke-tested, but there is **no measured control
  result** for it. No "proven architecture" claim is warranted.
- **Transformers are excluded by construction** (they carry no recorded MW flow,
  so the line-flow law doesn't apply). The `trafo_trip` overload the planner most
  needs to solve is a *transformer* overload — so this flow head does **nothing**
  for it. Decoding transformer loading needs a different relation (tap/branch
  model or a PTDF/LODF formulation).
- Two known formulation weaknesses: loading is fit as `c·|Δθ|` (a V-shape,
  because `flow_mw` is stored as |flow|), so the decode mishandles **flow
  reversals** and the training gradient is **sign-unstable** for lightly-loaded
  lines — which likely explains why the flow loss stalled at −11%. A **signed**
  formulation (`flow = b·Δθ` with directional flow, decode loading from |flow|)
  would remove both and is the right next step.

So: a real, correctly-implemented physics-decode mechanism with a clear
diagnosis, but an **open problem**, not a finished result.

### Next, ranked (dynamics model)

After an adversarial self-review, in payoff order:

1. **Honest evaluation** — held-out-family headline ✅ and trajectory-bootstrap
   CIs ✅ (angle generalization significant; Vm/loading null). Remaining: a
   multi-seed sweep to bound optimizer-init variance, and a dose-response
   ablation (below) for a conclusive "uses the action" claim.
2. **Physics-informed flow head** — built (decode loading from angles via the DC
   line-flow law + a differentiable flow loss), but **not yet a win**: oracle-only
   validation, −11% deployable (loses to persistence), control not re-run,
   transformers excluded. Real remaining work, not just tuning: (a) a **signed**
   `flow = b·Δθ` formulation to kill the V-shape/sign-instability; (b) a
   **PTDF/LODF** variant ([physics/lodf.py](../physics/lodf.py)) that covers
   transformers and post-trip topology; (c) then actually measure control.
3. **De-confound the horizon target** — only build samples whose `[t, t+H]`
   window contains no later action, or condition on the full action sequence.
4. **Strengthen the ablation into a dose-response** — sweep action magnitude and
   show predicted Δstate scales monotonically (real causal evidence).
5. **Encode branch-targeted actions** (line/transformer switching) as edge
   features rather than dropping them — required for a true grid-control model.
6. **Re-run control only once loading is predictable**, with per-scenario
   significance; stop citing "beats greedy" while the planner loses to do-nothing.

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

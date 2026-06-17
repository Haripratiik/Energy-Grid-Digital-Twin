# Roadmap — From Demo to Flagship

**Goal:** evolve this from an impressive Palantir-style demo into a project that
survives a hard technical interview — defensible physics, real platform
engineering, and a measurably-good AI control layer.

**North star:** every milestone below should produce something you can answer a
hostile follow-up question about. The framing for each item is *"what does this
prove?"*

**Scope decision:** all new work targets [`city-twin/`](../city-twin/). The
`grid-twin/` IEEE 9-bus app is demoted to a minimal reference — no new features.
Its one genuinely useful idea (JAX batch power flow) gets lifted into city-twin
for fast contingency screening (Milestone 1).

**GridWorld convergence (see `gridworld_research_plan`):** the sharper north
star is a **physical-AI / world-model benchmark** — learn an action-conditioned
model of grid dynamics and test whether it can rank stabilizing interventions
under faults. This *converges* with the roadmap: GridWorld needs reproducible
seeded scenarios, headless deterministic rollout, and trajectory logging (its
Phases 1–2), which are exactly M2's headless harness. M1's contingency engine
produces the **ground-truth simulator action/contingency rankings** GridWorld's
learned planner must beat. So the build order is unchanged; M2 is engineered as
the dataset-generation core, not just an eval harness.

---

## Where it stands today (honest assessment)

**Genuinely strong:**
- Real electromechanical physics — RK4 swing equation per generator with
  inertia-weighted system frequency *emerging* from the machines
  ([swing.py:204-241](../city-twin/backend/physics/swing.py#L204-L241)),
  coupled to a pandapower Newton-Raphson AC power flow with multi-algorithm
  fallback ([ac_powerflow.py:254-271](../city-twin/backend/physics/ac_powerflow.py#L254-L271)).
- Structured decision layer — risk classification, SEMI/FULL_AUTO policy with
  countdowns, audit log, outcome monitoring.
- Ontology + BFS impact propagation, and a Foundry export path.

**The gaps between "demo" and "flagship":**
1. **Reactive, not predictive.** The grid only responds *after* a fault is
   injected ([autonomous_engine.py:61](../city-twin/backend/decisions/autonomous_engine.py#L61)).
   Real control rooms run continuous N-1 contingency analysis.
2. **No evaluation.** "GPT proposes actions" is unfalsifiable. There is no
   measure of whether the AI's decisions are *good*.
3. **Everything is in-memory and single-process.** Decision log, alerts,
   scenarios, chat — all lost on restart. No persistence, no replay.
4. **Zero tests.** No `test_*` files exist in the repo. First thing an
   interviewer will notice.
5. **Faults don't cascade on their own.** Trips are manual; there's no
   protection model that auto-trips on sustained overload, so "cascade" is
   scripted, not emergent.

---

## Milestone 1 — N-1 Contingency Engine (physics) — ✅ SHIPPED

> Implemented in [`physics/contingency.py`](../city-twin/backend/physics/contingency.py),
> wired into the sim loop + `GET /contingencies` in
> [`main.py`](../city-twin/backend/main.py), tested in
> [`tests/test_contingency.py`](../city-twin/backend/tests/test_contingency.py)
> (7 passing). DC-screen-then-AC-verify; 123 contingencies in ~1.3 s on its own
> decoupled network. Confirms the 400 kV core is N-1 secure and the 33 kV
> radial edges + distribution transformers are the weak points.
> **Next:** lift grid-twin's JAX idea for batched DC screening, and stream the
> ranked list into the operator console.

**The spine of everything else.** For every element that could fail *right now*,
re-solve power flow with it removed and flag resulting limit violations.

**Proves:** you understand how grids are actually operated (N-1 security is the
defining control-room workload), not just how to wire an AC solver.

**Build:**
- `physics/contingency.py` — `ContingencyAnalyzer` that iterates lines /
  transformers / generators, re-solves via the existing `solve(...)`
  (already accepts outage sets), and returns ranked results: which single
  outage causes the worst voltage / thermal / frequency violation.
- **Performance is the real design problem.** ~124 NR solves/cycle is too slow
  to run every tick. Two-stage screening:
  - *Screen* with a fast linear (DC) approximation — this is where a JAX
    batch solver (lifted from grid-twin) earns its place; solve all N
    contingencies as one vectorized linear system.
  - *Verify* only the top-K worst screened contingencies with full AC.
  - Run on a throttled cadence (e.g. every 2-5 s) in the executor, not inline
    in the 20 ms tick.
- New endpoint `GET /contingencies` → ranked list with severity + violation
  detail. Stream a compact summary in the SSE payload.

**Interview defense to prepare:** why DC-screen-then-AC-verify; what a
contingency "severity score" should weight (overload margin vs. voltage vs.
islanding); why N-1 and not N-2.

---

## Milestone 2 — Evaluation Harness / GridWorld core (AI) — ✅ SHIPPED

> Implemented as the [`eval/`](../city-twin/backend/eval/) package: seeded
> reproducible scenarios ([scenario.py](../city-twin/backend/eval/scenario.py),
> 6 fault families), pluggable controllers (do-nothing, topology-aware greedy,
> LLM — [controllers.py](../city-twin/backend/eval/controllers.py)), a
> deterministic headless runner ([runner.py](../city-twin/backend/eval/runner.py)),
> stability metrics with a composite cost ([metrics.py](../city-twin/backend/eval/metrics.py)),
> GNN-ready trajectory recording ([trajectory.py](../city-twin/backend/eval/trajectory.py)),
> and CLIs (`python -m eval.run_eval`, `python -m eval.generate_dataset`).
> Tested in [tests/test_eval.py](../city-twin/backend/tests/test_eval.py) (8 passing).
>
> **Anchor result:** on `trafo_trip_radial`, topology-aware localized shedding
> (greedy) restores security in 16 s for ~6.6× lower cost than do-nothing; on
> meshed-corridor faults greedy can't fully recover — the exact gap a learned
> planner targets. This package *is* the GridWorld dataset-generation core:
> `generate_dataset` emits `(node, edge, global, action)` tensors + outcome
> labels per the research plan.
> **Next (research, beyond roadmap):** train the action-conditioned graph world
> model on these trajectories and add it as a `LearnedController`.

**The single most impressive artifact you can build.** Converts "the AI gives
advice" into "the AI beats baseline X by Y% on metric Z."

**Proves:** you can think about an AI system as something to *measure*, not just
demo — exactly the rigor that separates a flagship from a toy.

**Build:**
- `eval/` — a **headless** scenario runner (no FastAPI, no SSE) that steps the
  simulator deterministically through a scripted disturbance and lets a
  pluggable *controller* act each cycle.
- Controllers implementing one interface:
  - `DoNothingController` — baseline floor.
  - `GreedyRuleController` — deterministic heuristics (ramp nearest gen, shed
    smallest load) — the "is the LLM even worth it?" bar.
  - `LLMController` — wraps the existing `ReasoningEngine`.
  - (stretch) `MPCController` — short-horizon optimal setpoints.
- **Scored metrics:** total load shed (MWh), max & integrated frequency
  deviation, # limit violations, time-to-stable, # reversible vs. irreversible
  actions. Output a comparison table + plots.
- This requires the simulator to be driveable in-process without the server —
  a small refactor that also makes Milestone 3's tests possible. Build it here.

**Interview defense:** what makes a grid-control decision "good"; why these
baselines; how you keep runs deterministic (seed the stochastic wind/solar).

---

## Milestone 3 — Persistence, Tests, CI (platform) — ✅ SHIPPED

> SQLite persistence in [`storage/`](../city-twin/backend/storage/): telemetry
> time-series, the decision audit trail (upsert by id), and every eval run;
> wired into the sim loop (1 s cadence) with `/history/telemetry`,
> `/history/decisions`, `/history/eval`, `/history/stats` endpoints, and a
> `--db` flag on the eval CLI. Test suite grown from 0 → **38 passing** across
> physics, decisions, contingency, eval, storage, and protection
> ([tests/](../city-twin/backend/tests/)). GitHub Actions CI at
> [.github/workflows/ci.yml](../.github/workflows/ci.yml) runs pytest on push.
> README API table corrected to match the real routes.

**Table stakes for "flagship."** Everything currently evaporates on restart and
nothing is tested.

**Proves:** you ship production-shaped software, not just notebooks.

**Build:**
- **Persistence** — SQLite (zero-ops, upgradeable to Postgres/Timescale).
  Persist the decision log, alert history, and time-series telemetry; expose
  history + replay endpoints. The Foundry CSV export becomes one consumer of
  this store rather than a separate code path.
- **Tests** — `pytest` suite:
  - physics: power flow converges at nominal; frequency stays ~50/60 Hz at
    equilibrium; a gen dropout drops frequency; energy balance sanity.
  - decisions: risk classification boundaries; mode-policy state machine;
    revert restores pre-state.
  - contingency: a known weak line shows up as worst-case.
  - regression: the headless eval harness pinned to a baseline score.
- **CI** — GitHub Actions: lint + typecheck + pytest on push. Badge in README.
- Fix the README/endpoint drift (`/inject-fault` vs actual `/fault`, etc.)
  while here.

**Interview defense:** why SQLite-first; what you'd change for true
multi-operator; your testing strategy for a stochastic simulation.

---

## Milestone 4 — Cascading-Failure Dynamics (physics) — ✅ SHIPPED

> [`physics/protection.py`](../city-twin/backend/physics/protection.py):
> inverse-time overcurrent relays (`t = base/(loading_ratio − 1)`) with credit
> accumulation and reset. Integrated into the simulator
> ([swing.py](../city-twin/backend/physics/swing.py)) as an opt-in
> (`protection_enabled`, default off — no regressions); the live server enables
> it via `GRID_PROTECTION=1`, exposed at `/protection/events`. Overloads now
> auto-trip and cascade emergently — validated in
> [tests/test_protection.py](../city-twin/backend/tests/test_protection.py)
> (6 passing, incl. a multi-element cascade from a single seed fault). Closes
> the predictive loop: M1's N-1 ranking now foretells the cascades M4 produces.

**Makes contingency analysis *matter*.** Add a protection model so sustained
overloads auto-trip and failures propagate on their own.

**Proves:** you can model emergent system behavior, and it makes the N-1
predictions visibly pay off ("the engine warned about exactly this cascade").

**Build:**
- `physics/protection.py` — overcurrent/overload relays with inverse-time
  curves: an element loaded past its limit trips after a delay proportional to
  severity.
- Wire into the sim loop so a single seed fault can trigger a genuine cascade.
- The contingency engine's pre-event ranking can now be validated against what
  actually cascades — closing the predictive loop.

**Interview defense:** inverse-time relay coordination; how you prevent
unrealistic instant total collapse; the link between N-1 ranking and observed
cascade paths.

---

## Milestone 5 — GridWorld Learned World Model (research) — ✅ SHIPPED

> The research payoff the whole arc points at. [`research/`](../city-twin/backend/research/):
> a supervised task (predict grid security `H` steps ahead) built from the M2
> trajectories, with honest splits (by-trajectory, no leakage; held-out fault
> family for generalization), numpy baselines (persistence, logistic), a
> topology-blind MLP, and an action-conditioned message-passing **GNN** in pure
> PyTorch ([world_model.py](../city-twin/backend/research/world_model.py)). A
> `LearnedController` ([controller.py](../city-twin/backend/research/controller.py))
> ranks candidate actions by predicted security — the counterfactual planner.
> Train/benchmark CLI: `python -m research.train --data <dir>`. Tested in
> [tests/test_research.py](../city-twin/backend/tests/test_research.py) (10
> passing; torch-gated parts `importorskip` so core CI stays torch-free).
>
> **Honest finding:** all learned models beat persistence by AUROC and rank
> unseen-family risk better (0.91–0.94 vs 0.89), but fixed-threshold calibration
> degrades under distribution shift, and at this short horizon the GNN does *not*
> beat the MLP — near-term security is largely aggregate-readable. The rigorous
> eval harness (incl. the split that reveals the calibration failure) is the
> deliverable, not a hero number. Next: harder topology-dependent targets
> (which element fails / cascade depth), longer horizons, held-out *assets*.
> See [research/README.md](../city-twin/backend/research/README.md).

## Sequencing & why this order

```
M1 Contingency ──┬──> M2 Eval (needs something hard to reason over + headless sim)
                 │
                 └──> M4 Cascade (validates M1's predictions)
M2 Eval ─────────────> M3 Tests/CI (eval harness IS the regression test)
```

1. **M1 first** — it's the spine; M2 and M4 both build on it, and it's the most
   credible single addition to a power-systems reviewer.
2. **M2 next** — forces the in-process/headless refactor that M3 needs, and is
   the highest-signal AI artifact.
3. **M3** — locks in quality; the eval harness becomes the regression test.
4. **M4** — the payoff lap; makes demos dramatic and validates M1.

## Out of scope (deliberately)
- Multi-tenant auth / RBAC — note it as "what I'd add for production," don't
  build it. Distracts from the technical core for a portfolio piece.
- grid-twin feature parity — frozen.
- UX polish — deferred; the current console is good enough to demo M1–M4.

# Energy Grid Digital Twin

![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=flat&logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.100+-009688?style=flat&logo=fastapi&logoColor=white)
![React](https://img.shields.io/badge/React-18.3-61DAFB?style=flat&logo=react&logoColor=black)
![TypeScript](https://img.shields.io/badge/TypeScript-5.7-3178C6?style=flat&logo=typescript&logoColor=white)
![OpenAI](https://img.shields.io/badge/OpenAI-GPT--4o-412991?style=flat&logo=openai&logoColor=white)
![D3](https://img.shields.io/badge/D3.js-v7-F9A03C?style=flat&logo=d3.js&logoColor=white)

> A physics based power grid digital twin: power system physics validated against IEEE benchmarks, real time state estimation, fast contingency analysis at scale, and an AI operator that can only act through a physics safety gate.

This is a full stack simulation of a synthetic 80 bus grid laid out over the Atlanta metro area, about 2,430 MW of generation, running in near real time. It couples genuine power system physics (a solver validated against the IEEE test systems) with real time state estimation, an autonomous decision layer whose every action is checked by a power flow before it runs, and a live React operator console. The topology and geography are illustrative; the network is not measured utility data, and the README is careful to label what is real, what is synthetic, and what is estimated.

## Highlights

Every claim below is backed by a benchmark, an analytical result, or a measurement. See [docs/ROADMAP.md](docs/ROADMAP.md) and the 129 test backend suite (9 torch gated research tests skip unless PyTorch is installed, so 120 run in CI).

- **An AI operator that cannot act unsafely.** A language model proposes corrective actions, but it never touches the grid directly. A deterministic physics verifier re solves the power flow plus an N-1 contingency screen for each action, and a rejection overrules even a human approval. When an action is vetoed, the model re proposes against the physics feedback and the alternative is re verified. See [Physics safety verifier](#physics-safety-verifier).
- **Validated physics, not plausible physics.** AC power flow matches the IEEE 9, 14, 30, 57, and 118 systems to roughly 1e-10, and the swing equation integrator matches the analytical single machine infinite bus oscillation to 0.017 percent. See [Physics validation](#physics-validation).
- **A real digital twin loop.** An Unscented Kalman Filter keeps a model synchronized to a noisy plant from partial sensing, denoises below sensor accuracy, reconstructs unmeasured rotor speeds, and flags anomalies when innovation squared spikes about 100 times. See [Digital twin](#digital-twin).
- **Contingency screening at scale.** LODF distribution factors screen all N-1 contingencies on a 2,869 bus grid in 152 ms, about 28,000 times faster than brute force and exact to machine precision for the DC model. See [Contingency screening](#contingency-screening-at-scale).
- **Three grids, one viewer.** Switch between the synthetic Atlanta grid, the real Georgia transmission topology from OpenStreetMap, and a grid you build yourself. The choice drives both the map and the asset graph. See [Three grids](#three-grids).
- **Renewables and inertia.** A System Frequency Response model shows how falling inertia pushes the rate of change of frequency past grid code limits, and how grid forming inverters restore stability. See [Renewables and inertia](#renewables-and-inertia).
- **Live ambient demand.** Total load follows a real recorded weekly profile (NREL RTS-GMLC), so voltages, loadings, and asset statuses evolve on their own through a daily ramp and an evening peak, with no manual fault injection required.

## What it does

- **Live physics simulation.** AC power flow is solved by Newton-Raphson every 100 ms of simulated time (every 5 RK4 steps), coupled with per generator rotor dynamics through RK4 integration of the swing equation. System frequency emerges from the physics rather than being scripted.
- **Autonomous decision engine.** Grid faults are classified by risk, corrective actions are proposed, and they execute under a configurable human in the loop policy. Every action passes a physics safety check first.
- **Asset ontology.** Each grid component is a typed object with typed relationships, which enables graph based impact propagation across the network.
- **AI reasoning layer.** GPT-4o reads live telemetry and produces structured, explainable operator guidance, with a fully offline cached fallback when no API key is present.
- **Interactive operator console.** A real time D3 topology view, an asset graph, an alert feed, a decision queue with approve and reject controls, and a multi turn chat.

## Physics safety verifier

The distinctive piece is the boundary between the AI and the grid. The model can suggest, but only physics can authorize.

Every proposed action is gated by a deterministic verifier ([`decisions/safety_verifier.py`](city-twin/backend/decisions/safety_verifier.py)) that runs on its own decoupled solver, and the loop closes back to the model when an action is rejected.

- **Two physics gates.** The action is applied to a copy of the operating point and re solved. First, the steady state AC power flow must converge and must not be materially less secure than the current state. Second, an N-1 contingency screen must show the action does not leave the grid more exposed to the next single failure. Most published language model plus grid systems verify only that a steady state solve converges.
- **Fail closed.** Any action the verifier cannot model, such as an unknown type or a malformed identifier, is rejected rather than silently certified, and a veto overrules even an operator pressing Approve.
- **Self correction.** When an action is vetoed, the rejection reason and the before and after severities are fed back to the model, which proposes a different action against that feedback. The alternative is then re verified. Each attempt and its verdict are recorded as a correction trace and shown in the console, which is the difference between a model that is merely gated by physics and one that corrects itself against physics.
- **Quantified screening fidelity.** The inline N-1 gate is screened, meaning only the worst few contingencies are AC verified, which keeps it fast enough to run on the decision path. [`research/verifier_eval.py`](city-twin/backend/research/verifier_eval.py) measures what that approximation costs: it replays a battery of benign and adversarial proposals through both the fast screened gate and an exhaustive variant that AC verifies every single contingency under the same security criterion. Across 219 proposals spanning settled and stressed operating points, the screened gate caught all 32 actions the exhaustive study rejects (100 percent catch rate, 0 percent false accept) and erred on the conservative side for 5 of them (2.7 percent false reject). It occasionally blocks a safe action but never waves through an unsafe one, which is the right asymmetry for a safety gate. This validates the screening approximation, not absolute safety correctness.

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                     React Frontend                       │
│  D3 Grid Topology │ Asset Graph    │ Operator Console    │
│  Decision Queue   │ AI Chat Panel  │ Generator Mix       │
└───────────────────────────┬─────────────────────────────┘
                            │ Server-Sent Events (SSE)
┌───────────────────────────▼─────────────────────────────┐
│                   FastAPI Backend                        │
│                                                          │
│  ┌─────────────────┐   ┌──────────────────────────────┐ │
│  │  Physics Engine  │   │   Autonomous Decision Engine │ │
│  │                 │    │                              │ │
│  │ AC Power Flow   │──▶ │ Risk Classifier              │ │
│  │ (Newton-Raphson)│    │ Physics Safety Verifier      │ │
│  │ Swing Equation  │    │ Mode Policy (SEMI/FULL_AUTO) │ │
│  │ (RK4, per-gen)  │    │ Action Executor + Audit Log  │ │
│  └─────────────────┘    └──────────────────────────────┘ │
│                                                          │
│  ┌─────────────────┐   ┌──────────────────────────────┐ │
│  │  Ontology Store  │   │     AI Reasoning Engine      │ │
│  │                 │    │                              │ │
│  │ Asset Objects   │    │ GPT-4o (structured outputs)  │ │
│  │ Typed Relations │    │ Grid-aware system prompt     │ │
│  │ BFS Propagation │    │ Multi-turn operator chat     │ │
│  │ Alert Manager   │    │ Offline cached fallback      │ │
│  └─────────────────┘    └──────────────────────────────┘ │
└──────────────────────────────────────────────────────────┘
```

## Three grids

The topology panel and the asset graph are two views of one selected grid. A single control switches the source, and both views follow it.

- **Synthetic Atlanta grid (default).** The live 80 bus simulation, drawn at real Atlanta coordinates over real OpenStreetMap infrastructure on a dark basemap, with landmarks such as Plant Vogtle, Hartsfield-Jackson, Buckhead, and Georgia Tech. The wiring is the synthetic model; the coordinates are real.
- **Real Georgia transmission.** Built from OpenStreetMap, this is the real Georgia transmission topology: 237 substations and 348 lines across several voltage classes, with source substations near real power plants. The topology and geography are real. The electrical parameters behind it (impedances, thermal ratings, dispatch) are estimated per voltage class, because the real values are protected infrastructure information and are not public. It is rendered both geographically and as its own ontology.
- **Custom grid builder.** Draw your own buses and lines, set the voltage class, load, and generation per bus, mark a slack, and the backend turns the drawing into a pandapower network, solves an AC power flow, and returns per bus and per line results plus a matching ontology. A grid that does not solve is shown honestly, with unsolved buses greyed out rather than reported as healthy.

## Physics simulation

- **80 bus synthetic topology** across three voltage levels: 400 kV transmission, 132 kV sub transmission, and 33 kV distribution. Line impedances use a tuned per unit base chosen for realistic loadings and solver convergence. The solver itself is validated separately on the real IEEE test systems (see [Physics validation](#physics-validation)).
- **12 generators** across 5 types (nuclear, hydro, gas peaker, wind, solar), each with distinct inertia constants, ramp rates, and stochastic behavior models.
- **Newton-Raphson AC power flow** solved through pandapower every 100 ms of simulated time, producing per bus voltages and angles and per line real and reactive flows.
- **RK4 swing equation** integrated per generator for rotor angle and speed, so system frequency is a result of the dynamics rather than an input.

## Physics validation

The simulation physics are validated against recognized benchmarks and analytical theory rather than assumed plausible. Run the full report with:

```bash
cd city-twin/backend
python -m physics.validation
```

AC power flow is validated against the standard IEEE test systems three independent ways: Newton-Raphson and fast decoupled solvers must converge to the same voltages (uniqueness implies correctness), nodal power must be conserved, and total losses must match published values.

| case | buses | NR vs FD (ΔV) | conservation | losses | published |
|------|------:|--------------:|-------------:|-------:|----------:|
| IEEE-9 | 9 | 4e-10 pu | 7e-9 MW | 4.96 MW | 5.0 |
| IEEE-14 | 14 | 3e-11 pu | 6e-9 MW | 13.39 MW | 13.4 |
| IEEE-30 | 30 | 3e-10 pu | 5e-9 MW | 2.44 MW | n/a |
| IEEE-57 | 57 | 3e-9 pu | 6e-8 MW | 30.29 MW | n/a |
| IEEE-118 | 118 | 1e-10 pu | 2e-7 MW | 133.17 MW | 133.0 |

Swing equation dynamics are validated against the analytical small signal oscillation frequency of a single machine infinite bus system, omega_n = sqrt(K_s / M). The simulated period of 13.9149 s versus the analytical 13.9125 s is a 0.017 percent error, and the period scales as the square root of inertia exactly as theory predicts.

Turbine governor primary frequency control ([physics/governor.py](city-twin/backend/physics/governor.py)) reproduces textbook behavior: after losing a 280 MW generator, the droop governors collectively pick up about 40 MW of primary response and reduce the steady state frequency deviation, leaving a residual offset for secondary control to remove. Enable it in the live simulator with `GRID_GOVERNOR=1`.

## Contingency screening at scale

Brute force N-1 screening re solves a power flow for every possible outage. The [`physics/lodf.py`](city-twin/backend/physics/lodf.py) module precomputes PTDF and LODF distribution factors so that all single branch outages are evaluated in one vectorized matrix expression, scaling to thousands of buses and exact for the DC model.

```bash
cd city-twin/backend
python -m physics.perf.benchmark --jax
```

| network | buses | branches | LODF screen | brute force | speedup |
|---------|------:|---------:|------------:|------------:|--------:|
| IEEE-118 | 118 | 186 | 0.03 ms | 132 ms | 4,159x |
| case300 | 300 | 411 | 1.1 ms | 1.1 s* | 1,022x |
| case1354pegase | 1354 | 1991 | 31 ms | 4.2 min* | 8,154x |
| case2869pegase | 2869 | 4582 | 152 ms (14 ms JAX jitted) | ~73 min* | 28,665x |

*Brute force projected from a sample of outages.* All 4,582 N-1 contingencies on a 2,869 bus grid are screened in 152 ms (14 ms with the optional JAX jitted path), agreeing with brute force re solves to about 1e-10.

A continuous version of this runs in the live app: for every line, transformer, and generator that could fail next, the grid is re solved and ranked by violation severity, using a fast DC screen followed by an AC verify of the worst cases on a decoupled network so it never blocks the real time loop. A live summary streams over SSE, and the full report is at `GET /contingencies`. It confirms the 400 kV core is N-1 secure while the 33 kV radial edges are the weak points.

## State estimation and bad data detection

A control room never measures the true state; it estimates the state from a redundant, noisy, occasionally faulty measurement set. [`physics/state_estimation.py`](city-twin/backend/physics/state_estimation.py) implements the EMS standard weighted least squares state estimator (state is bus angles, measurements are branch flows and bus injections) with chi squared bad data detection and largest normalized residual identification.

```bash
cd city-twin/backend
python -m physics.state_estimation
```

On IEEE-118 with a measurement redundancy of 2.6, the estimate denoises (flow RMSE 0.008 pu versus 0.02 pu sensor noise), clean data passes the chi squared test, and a single injected gross error is both detected (objective 636, well above the 234 threshold) and localized to the exact measurement (normalized residual 21).

## Digital twin

The defining property of a digital twin is a model kept synchronized to a physical asset from noisy, partial sensing. This is demonstrated end to end with a dual simulator loop ([`twin/`](city-twin/backend/twin/)):

```bash
cd city-twin/backend
python -m twin.demo
```

A physical plant runs ground truth multi machine swing dynamics ([classical_model.py](city-twin/backend/physics/classical_model.py), EMF behind transient reactance, Kron reduced from the validated IEEE-9 network) with process noise, and is never directly observed. A twin receives only noisy, partial rotor angle measurements (PMU like) and tracks the plant's full state with an Unscented Kalman Filter whose process model is the same swing dynamics.

| property | result |
|---|---|
| Converged angle RMSE | 0.0016 rad, better than the 0.01 rad sensor noise (the filter denoises) |
| Unmeasured rotor speed RMSE | 0.013 rad/s, reconstructed from dynamics since speeds are never measured |
| Partial observability (2 of 3 angles) | still tracks the unsensed machine and all speeds |
| Statistical consistency | normalized innovation squared near 3, equal to the measurement count, correctly tuned |
| Anomaly detection | on an unmodeled plant event, innovation squared spikes about 100 times (3 to 320) |

This is the loop where the twin tracks reality and flags divergence: nonlinear Bayesian estimation over real power system dynamics, validated against an IEEE benchmark.

## Renewables and inertia

The defining stability problem of the energy transition is that inverter coupled renewables carry no rotating inertia, so as they displace synchronous machines the system frequency falls faster and deeper after a loss. [`physics/frequency_response.py`](city-twin/backend/physics/frequency_response.py) models this with the standard aggregated System Frequency Response model and shows how grid forming inverters, which add synthetic inertia and fast droop, restore stability.

```bash
cd city-twin/backend
python -m physics.frequency_response
```

For a 12 percent generation loss, the initial rate of change of frequency reproduces the analytical value by construction, and the full transient is validated against an independent higher order RK4 reference integrator with nadir agreement under 0.001 Hz.

| scenario | inertia H | RoCoF | nadir | grid code (1 Hz/s) |
|----------|----------:|------:|------:|:------------------:|
| High inertia (all synchronous) | 6.0 | 0.60 Hz/s | 59.09 Hz | ok |
| Low inertia (high renewables) | 2.0 | 1.80 Hz/s | 58.58 Hz | breach |
| Low inertia plus grid forming | 4.5 | 0.80 Hz/s | 59.48 Hz | ok |

## Autonomous decision engine

- **Risk classification** across four levels: ADVISORY (under 10 MW impact), CONTROLLED (under 50 MW), CRITICAL (under 100 MW or non reversible), and EMERGENCY (over 100 MW or islanding).
- **Two operating modes.** In SEMI_AUTO, advisory decisions auto execute, controlled actions get a 15 second countdown, and critical or emergency actions require explicit operator approval. In FULL_AUTO, all decisions auto execute with a short display window for manual override.
- **Action types:** LOAD_SHED, GEN_SETPOINT, LINE_SWITCH, TRANSFORMER_TAP, ISLANDING.
- **Physics safety gate.** Every action passes the verifier described in [Physics safety verifier](#physics-safety-verifier) before it runs.
- **Outcome monitoring.** Pre and post state snapshots evaluate whether each decision achieved its intended effect.
- **Audit trail.** An append only decision log records timestamps, risk levels, approval method, outcomes, the physics verdict, and the self correction trace for each decision.

## Asset ontology

- Asset hierarchy: GridSystem to Region to Substation to Generator or LoadBus.
- Typed relationships: POWERS, CONNECTED_TO, FEEDS, PART_OF, MONITORS.
- BFS alert propagation, so a fault on a substation propagates impact scores to all downstream buses, lines, and districts.
- Per asset alert thresholds across four severity levels: INFO, WARNING, CRITICAL, EMERGENCY.

## AI reasoning layer

- GPT-4o is called with full grid telemetry context and a structured output schema that enforces typed proposed actions.
- The reasoning history is shown in the console for explainability and auditability.
- A multi turn chat lets operators ask natural language questions about the current grid state, with answers rendered through a dependency free, escape safe Markdown renderer.
- A graceful offline fallback uses pre written cached responses when no API key is present, so the physics, decision engine, and console all work without a key.

## Research extension: learned world model

Beyond the live console, the backend includes an analysis and research layer (see [research/README.md](city-twin/backend/research/README.md) for the full design and the honestly reported findings).

A headless, deterministic evaluation harness ([`eval/`](city-twin/backend/eval/)) replays seeded fault scenarios under pluggable control policies (`do_nothing`, a topology aware `greedy_rule`, and `llm`) that all act through the same executor as the live engine, and scores them on grid stability metrics. The same machinery records graph tensors with outcome labels, which form the training corpus for a learned grid world model.

```bash
cd city-twin/backend
python -m eval.run_eval                                   # compare controllers across scenarios
python -m eval.generate_dataset --out data/gridworld_v1   # GNN ready trajectory dataset
```

The research extension ([`research/`](city-twin/backend/research/)) trains action conditioned graph models on those trajectories to predict near term grid security, benchmarking a message passing GNN against topology blind and persistence baselines with honest by trajectory and held out fault family splits. An action conditioned dynamics model predicts the next state with the action injected at the acted node, beats the persistence baseline on the dynamic angle quantities, and an action ablation confirms it causally uses interventions (angle generalization significant by a trajectory bootstrap, 90 percent confidence interval from +3.4 percent to +12.1 percent, even on a held out fault family). The honest finding is that line loading prediction stays persistence hard, so a physics informed flow head that decodes loading from predicted angles through the DC line flow law is provided as an open problem rather than a solved one: it reaches +90 percent against persistence with true angles (an invertibility check) but stays below persistence with the model's own angles. The full writeup, including what does not work, is in [research/README.md](city-twin/backend/research/README.md).

## Operator console

- **Grid topology panel.** A geographic map of the selected grid (synthetic, real Georgia, or custom), with a builder for the custom case, plus a fault injector for the live grid.
- **Asset graph panel.** A live force directed D3 graph of grid objects and their typed relationships, following the same source selection as the topology panel.
- **Decision queue.** Pending decisions with a risk badge, the proposed action, a countdown timer where applicable, the physics verdict, the self correction trace, and approve, reject, and revert controls.
- **Alert feed.** A real time stream of threshold violations with severity color coding.
- **Generator mix.** Live bar and pie charts of current dispatch by generator type.
- **Analytics.** The digital twin tracking view and related charts.

## Technology stack

### Backend

| Layer | Technology | Purpose |
|-------|-----------|---------|
| Web framework | FastAPI and Uvicorn | Async REST API and SSE streaming |
| Power flow | pandapower | Newton-Raphson AC power flow solver |
| Numerics | NumPy, NetworkX | Matrix math and graph traversal |
| JAX (grid-twin) | JAX (CPU mode) | Accelerated DC power flow and swing dynamics |
| AI reasoning | OpenAI GPT-4o | Structured decision outputs and operator chat |
| AI (grid-twin) | Anthropic Claude | Alternative reasoning backend |
| Validation | Pydantic v2 | Strict schema enforcement throughout |
| Config | python-dotenv | Environment variable management |

### Frontend

| Layer | Technology | Purpose |
|-------|-----------|---------|
| Framework | React 18.3 and TypeScript 5.7 | Component driven UI with full type safety |
| Build | Vite 6 | Fast dev server and optimized production builds |
| Visualization | D3.js v7 | Force directed graphs and topology rendering |
| Maps | Leaflet | Geographic rendering on a dark basemap |
| Charts | Recharts | Generation mix charts |
| Animation | Framer Motion | Transitions for alerts and decisions |
| Layout | react-grid-layout | Draggable, resizable operator panels |
| Styling | TailwindCSS | Utility first CSS |
| Streaming | Server-Sent Events | Real time grid state without WebSocket overhead |

## Getting started

### Prerequisites

- Python 3.11 or newer
- Node.js 18 or newer
- An OpenAI API key for the live AI features (optional; the app runs fully offline without one)

### 1. Backend

```bash
cd city-twin/backend

python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate

pip install -r requirements.txt

cp .env.example .env
# Edit .env and add your OpenAI API key:
# OPENAI_API_KEY=your-api-key-here

uvicorn main:app --reload --port 8000
```

The API is then available at `http://localhost:8000`, with auto generated docs at `http://localhost:8000/docs`.

### 2. Frontend

```bash
cd city-twin/frontend
npm install
npm run dev
```

The UI is then available at `http://localhost:5173`.

### 3. Offline mode

The reasoning engine falls back to cached responses when no API key is configured. All physics, state estimation, contingency analysis, and decision engine features work fully offline; only the live language model reasoning needs a key.

### Tests and CI

```bash
cd city-twin/backend
pip install -r requirements-dev.txt
pytest -q       # 129 tests across physics, validation, twin, lodf, state estimation,
                # frequency response, decisions, safety verifier (including N-1 and
                # self correction), verifier eval, api, contingency, eval, storage,
                # protection, custom grid, real grid, and research
                # (9 torch gated tests skip without torch)
```

CI runs lint (`ruff`), the full pytest suite, and a frontend type check and build (`tsc && vite build`) on every push ([.github/workflows/ci.yml](.github/workflows/ci.yml)).

## Project structure

```
Energy-Grid-Digital-Twin/
├── city-twin/                   # Primary app, 80-bus Atlanta metro grid
│   ├── backend/
│   │   ├── main.py              # FastAPI server, SSE stream, API endpoints
│   │   ├── physics/             # Power flow, swing dynamics, LODF, state estimation,
│   │   │                        #   contingency, frequency response, real Georgia grid,
│   │   │                        #   custom grid solver, protection, generators
│   │   ├── ontology/            # GridAsset schemas, in-memory asset graph, alerts
│   │   ├── decisions/           # Risk classifier, safety verifier, action executor,
│   │   │                        #   autonomous engine, decision log, outcome monitor
│   │   ├── reasoning/           # GPT-4o integration and cached fallbacks
│   │   ├── chat/                # Multi-turn conversational engine and storage
│   │   ├── twin/                # UKF digital-twin loop
│   │   ├── eval/                # Deterministic controller evaluation harness
│   │   ├── research/            # Learned world model and verifier evaluation
│   │   └── storage/             # SQLite persistence
│   └── frontend/
│       └── src/                 # React components, hooks, types
│
└── grid-twin/                   # Reference implementation, IEEE 9-bus test system
```

## API reference

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/stream` | GET (SSE) | Real time grid state stream, one frame per 100 ms of simulated time, with a live contingency summary |
| `/fault` | POST | Inject a fault into the simulation |
| `/restore` | POST | Reset the simulation to its initial state |
| `/contingencies` | GET | Ranked N-1 contingency report (`?refresh=true` to recompute) |
| `/decisions/pending` | GET | List pending decisions |
| `/decisions/log` | GET | Full decision audit trail with physics verdicts |
| `/decisions/{id}/approve` | POST | Approve a pending decision (still subject to the physics gate) |
| `/decisions/{id}/reject` | POST | Reject a pending decision |
| `/decisions/{id}/revert` | POST | Revert an executed decision |
| `/verify-action` | POST | Run the physics safety check on an action without executing it |
| `/mode` | GET/POST | Get or switch autonomous mode (SEMI or FULL_AUTO) |
| `/ontology` | GET | Synthetic grid asset graph |
| `/real-grid` | GET | Real Georgia transmission grid (OSM topology, DC solution) |
| `/real-grid/ontology` | GET | Asset graph over the real Georgia grid |
| `/custom-grid/simulate` | POST | Solve a user built grid and return per bus and per line state plus its ontology |
| `/custom-grid/ontology` | GET | Asset graph of the most recently simulated custom grid |
| `/alerts` | GET | Recent threshold violation alerts |
| `/history/telemetry` | GET | Persisted telemetry time series |
| `/history/decisions` | GET | Persisted decision audit trail |
| `/chat/threads` | GET/POST | List or create chat threads |
| `/chat/threads/{id}/messages` | GET/POST | Read or send messages to the AI |
| `/twin/run` | GET | Run the UKF digital twin loop and return the tracking time series |
| `/perf/lodf` | GET | Benchmark LODF fast N-1 screening on a network (`?case=`) |
| `/frequency-response` | GET | RoCoF and nadir under varying inertia and grid forming (`?disturbance=`) |
| `/protection/events` | GET | Relay trip cascade log (enable with `GRID_PROTECTION=1`) |
| `/demo` | POST | Start the built in demo scenario |
| `/health` | GET | Liveness, simulated time, and pending decision count |

## Grid metrics

| Parameter | Value |
|-----------|-------|
| Buses | 80 |
| Voltage levels | 400 kV, 132 kV, 33 kV |
| Generators | 12 (nuclear, hydro, gas, wind, solar) |
| Total capacity | about 2,430 MW |
| Modeled load | about 1,800 MW |
| Transmission lines | 91 |
| Transformers | 21 |
| Physics tick | 20 ms (RK4) |
| Stream emit rate | 100 ms |
| Power flow method | Newton-Raphson AC |
| Dynamics method | RK4 swing equation |

## Two implementations

`city-twin/` is the primary app: the full 80 bus Atlanta metro simulation with the decision engine, ontology, reasoning, and chat systems, using OpenAI GPT-4o.

`grid-twin/` is a frozen reference implementation of the IEEE 9 bus test system, the standard academic benchmark in power systems. It uses JAX for accelerated numerics and Anthropic Claude for reasoning, and is kept as a lighter reference and for comparing reasoning backends. All active development targets `city-twin/`.

## Security notes

- API keys are loaded only from `.env` files, which are excluded from version control. No secrets are hardcoded anywhere in the source.
- User submitted custom grid specifications are validated and coerced by Pydantic, and identifiers are parsed defensively, so they cannot reach a file, shell, or database sink.
- AI and user text is rendered through React with auto escaping and a dependency free Markdown renderer that never injects raw HTML.
- These are development servers and are not production hardened. CORS is restricted to `localhost:5173`, and the servers bind to localhost. Add authentication before exposing them on any network.

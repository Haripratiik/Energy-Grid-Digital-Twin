# Atlanta Metro Grid Digital Twin

![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=flat&logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.100+-009688?style=flat&logo=fastapi&logoColor=white)
![React](https://img.shields.io/badge/React-18.3-61DAFB?style=flat&logo=react&logoColor=black)
![TypeScript](https://img.shields.io/badge/TypeScript-5.7-3178C6?style=flat&logo=typescript&logoColor=white)
![OpenAI](https://img.shields.io/badge/OpenAI-GPT--4o-412991?style=flat&logo=openai&logoColor=white)
![D3](https://img.shields.io/badge/D3.js-v7-F9A03C?style=flat&logo=d3.js&logoColor=white)

> Physics-accurate power grid digital twin with autonomous AI decision engine, Foundry-style ontology, and real-time React dashboard

A full-stack, physics-accurate power grid digital twin built to demonstrate Palantir-style operational intelligence — autonomous decision-making, real-time telemetry, ontology-driven asset modeling, and AI-powered operator assistance.

Built as a technical showcase of the patterns Palantir uses across their **Foundry**, **AIP**, and **Ontology** products, applied to critical infrastructure operations.

---

## What This Is

This project simulates the Atlanta metropolitan power grid (80 buses, ~2,430 MW capacity) at near-real-time with:

- **Live physics simulation** — AC power flow solved via Newton-Raphson every 200ms, coupled with per-generator swing equation dynamics (RK4 integration)
- **Autonomous decision engine** — classifies faults by risk level, proposes operator actions, and executes them with configurable human-in-the-loop approval
- **Foundry-style ontology** — every grid asset is a typed object with typed relationships, enabling BFS-based impact propagation
- **AI reasoning layer** — GPT-4o interprets grid anomalies and generates structured, explainable operator guidance
- **Interactive operator console** — real-time D3 topology visualization, alert feed, decision queue with approve/reject, and multi-turn AI chat

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────┐
│                     React Frontend                       │
│  D3 Grid Topology │ Ontology Graph │ Operator Console   │
│  Decision Queue   │ AI Chat Panel  │ Generator Mix      │
└───────────────────────────┬─────────────────────────────┘
                            │ Server-Sent Events (SSE)
┌───────────────────────────▼─────────────────────────────┐
│                   FastAPI Backend                        │
│                                                         │
│  ┌─────────────────┐   ┌──────────────────────────────┐ │
│  │  Physics Engine  │   │    Autonomous Decision Engine│ │
│  │                 │   │                              │ │
│  │ AC Power Flow   │──▶│ Risk Classifier              │ │
│  │ (Newton-Raphson)│   │ Mode Policy (SEMI/FULL_AUTO) │ │
│  │ Swing Equation  │   │ Action Executor              │ │
│  │ (RK4, per-gen)  │   │ Decision Log (audit trail)   │ │
│  └─────────────────┘   └──────────────────────────────┘ │
│                                                         │
│  ┌─────────────────┐   ┌──────────────────────────────┐ │
│  │ Ontology Store  │   │     AI Reasoning Engine      │ │
│  │                 │   │                              │ │
│  │ Asset Objects   │   │ GPT-4o (structured outputs)  │ │
│  │ Typed Relations │   │ Grid-aware system prompt     │ │
│  │ BFS Propagation │   │ Multi-turn operator chat     │ │
│  │ Alert Manager   │   │ Offline cached fallback      │ │
│  └─────────────────┘   └──────────────────────────────┘ │
└─────────────────────────────────────────────────────────┘
```

---

## Project Structure

```
PalantirNextSteps/
├── city-twin/               # Primary application — 80-bus Atlanta metro grid
│   ├── backend/
│   │   ├── main.py          # FastAPI server, SSE stream, API endpoints
│   │   ├── physics/
│   │   │   ├── network.py         # 80-bus topology (400kV / 132kV / 33kV)
│   │   │   ├── swing.py           # RK4 swing equation + AC power flow coupling
│   │   │   ├── ac_powerflow.py    # pandapower Newton-Raphson solver
│   │   │   ├── fault_handler.py   # Fault injection (generator, line, load, transformer)
│   │   │   └── generators/        # Per-type generator models
│   │   │       ├── nuclear.py     # High-inertia base-load
│   │   │       ├── hydro.py       # Hydro with water dynamics
│   │   │       ├── gas.py         # Fast-ramp peaker
│   │   │       ├── wind.py        # Ornstein-Uhlenbeck stochastic model
│   │   │       └── solar.py       # Stochastic solar model
│   │   ├── ontology/
│   │   │   ├── model.py           # GridAsset, OntologyLink, GridAlert schemas
│   │   │   └── store.py           # In-memory ontology graph + alert manager
│   │   ├── decisions/
│   │   │   ├── models.py          # GridDecision, RiskLevel, AutonomousMode
│   │   │   ├── autonomous_engine.py  # Mode policy and approval logic
│   │   │   ├── risk_classifier.py    # Risk scoring algorithm
│   │   │   ├── action_executor.py    # Decision action runner
│   │   │   ├── decision_log.py       # Append-only audit trail
│   │   │   └── outcome_monitor.py    # Pre/post state snapshot comparison
│   │   ├── reasoning/
│   │   │   ├── engine.py          # GPT-4o integration with structured outputs
│   │   │   └── cached_responses.py  # Offline demo fallback responses
│   │   ├── chat/
│   │   │   ├── engine.py          # Multi-turn conversational AI engine
│   │   │   └── store.py           # Thread-based message storage
│   │   ├── export_foundry_datasets.py  # CSV exporter for Foundry upload
│   │   └── requirements.txt
│   └── frontend/
│       ├── src/
│       │   ├── App.tsx            # Root component, resizable 4-panel layout
│       │   ├── components/        # All UI components (see below)
│       │   ├── hooks/             # Custom React hooks for SSE, decisions, ontology
│       │   ├── types/             # TypeScript interfaces
│       │   └── data/              # Static grid data and map presets
│       ├── package.json
│       └── vite.config.ts
│
└── grid-twin/               # Reference implementation — IEEE 9-bus test system
    ├── backend/             # JAX-based physics, Anthropic Claude reasoning
    ├── frontend/            # Identical stack, simplified UI
    ├── README.md
    └── USER_GUIDE.md
```

---

## Technology Stack

### Backend

| Layer | Technology | Purpose |
|-------|-----------|---------|
| Web Framework | **FastAPI** + Uvicorn | Async REST API + SSE streaming |
| Power Flow | **pandapower** | Newton-Raphson AC power flow solver |
| Numerics | **NumPy**, **NetworkX** | Matrix math, graph traversal |
| JAX (grid-twin) | **JAX** (CPU mode) | Accelerated DC power flow + swing dynamics |
| AI Reasoning | **OpenAI GPT-4o** | Structured decision outputs, operator chat |
| AI (grid-twin) | **Anthropic Claude** | Alternative reasoning backend |
| Data Validation | **Pydantic v2** | Strict schema enforcement throughout |
| Config | **python-dotenv** | Environment variable management |

### Frontend

| Layer | Technology | Purpose |
|-------|-----------|---------|
| Framework | **React 18.3** + **TypeScript 5.7** | Component-driven UI with full type safety |
| Build | **Vite 6.0** | Fast dev server, optimized production builds |
| Visualization | **D3.js v7.9** | Force-directed graphs, physics topology |
| Charts | **Recharts** | Generation mix bar/pie charts |
| Animation | **Framer Motion** | Smooth transitions for alerts and decisions |
| Layout | **react-resizable-panels** | Draggable panel layout for operator console |
| Styling | **TailwindCSS 3.4** | Utility-first CSS |
| Streaming | **Server-Sent Events** | Real-time grid state without WebSocket overhead |

---

## Key Features

### Physics Simulation
- **80-bus grid topology** modeled on the Atlanta metro area with three voltage levels: 400kV transmission, 132kV sub-transmission, 33kV distribution
- **12 generators** across 5 types (nuclear, hydro, gas peaker, wind, solar) each with distinct inertia constants, ramp rates, and stochastic behavior
- **Newton-Raphson AC power flow** solved via pandapower every 200ms — produces per-bus voltages, angles, and line MW/Mvar flows
- **RK4 swing equation** for each generator in parallel, modeling rotor angle and speed deviation — frequency emerges naturally from physics

### Autonomous Decision Engine
- **Risk classification** across 4 levels: `ADVISORY` (< 10 MW impact), `CONTROLLED` (< 50 MW), `CRITICAL` (< 100 MW or non-reversible), `EMERGENCY` (> 100 MW or islanding)
- **Two operating modes:**
  - `SEMI_AUTO` — ADVISORY decisions auto-execute; CONTROLLED actions have a 15-second countdown window; CRITICAL/EMERGENCY require explicit operator approval
  - `FULL_AUTO` — all decisions auto-execute with a 3-second display window for manual override
- **Action types:** `LOAD_SHED`, `GEN_SETPOINT`, `LINE_SWITCH`, `TRANSFORMER_TAP`, `ISLANDING`
- **Outcome monitoring** — captures pre/post state snapshots to evaluate whether a decision achieved its intended effect
- **Audit trail** — append-only decision log with timestamps, risk levels, approval method, and outcomes

### Foundry-Style Ontology
- Asset hierarchy: `GridSystem → Region → Substation → Generator / LoadBus`
- **Typed relationships:** `POWERS`, `CONNECTED_TO`, `FEEDS`, `PART_OF`, `MONITORS`
- **Resource IDs (RIDs)** in Palantir format: `ri.city-grid.main.object-type.identifier`
- **BFS alert propagation** — a fault on a substation propagates impact scores to downstream buses, lines, and districts
- Alert thresholds per asset type with severity levels (`INFO`, `WARNING`, `CRITICAL`, `EMERGENCY`)

### AI Reasoning Layer
- GPT-4o called with full grid telemetry context and a structured output schema (`DecisionResponse`) enforcing JSON-typed proposed actions
- Reasoning history displayed in the operator console for full explainability
- Multi-turn chat interface lets operators ask natural language questions about grid state
- Graceful offline fallback to pre-written cached responses if API is unavailable

### Interactive Operator Console
- **Grid Topology panel** — D3 force-directed graph of all 80 buses and 91 transmission lines; nodes color-coded by voltage, pulsing animation on fault
- **Ontology Graph panel** — live force-directed visualization of asset objects and their typed relationships
- **Decision Queue** — pending decisions with risk level badge, proposed actions, countdown timer, and approve/reject/revert controls
- **Alert Feed** — real-time stream of threshold violations with severity color coding
- **Generator Mix** — live bar and pie charts of dispatch by generator type
- **Fault Injector** — inject any of 4 fault types (`GEN_DROPOUT`, `LINE_TRIP`, `LOAD_SPIKE`, `TRAFO_TRIP`) onto any target asset

---

## Getting Started

### Prerequisites

- Python 3.11+
- Node.js 18+
- An OpenAI API key (GPT-4o)

### 1. Backend Setup (City-Twin)

```bash
cd city-twin/backend

# Create and activate virtual environment
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env and add your OpenAI API key:
# OPENAI_API_KEY=sk-...

# Start the server
uvicorn main:app --reload --port 8000
```

The API will be available at `http://localhost:8000`.
API docs (auto-generated): `http://localhost:8000/docs`

### 2. Frontend Setup (City-Twin)

```bash
cd city-twin/frontend

# Install dependencies
npm install

# Start the dev server
npm run dev
```

The UI will be available at `http://localhost:5173`.

### 3. Running Without an API Key (Demo Mode)

The reasoning engine automatically falls back to cached responses if no API key is set. All physics simulation and decision engine features work fully offline — only the AI reasoning requires a key.

---

## API Reference

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/stream` | GET (SSE) | Real-time grid state stream (100ms ticks) |
| `/inject-fault` | POST | Inject a fault into the simulation |
| `/decisions` | GET | List pending decisions |
| `/decisions/{id}/approve` | POST | Approve a pending decision |
| `/decisions/{id}/reject` | POST | Reject a pending decision |
| `/decisions/{id}/revert` | POST | Revert an executed decision |
| `/decisions/log` | GET | Full decision audit trail |
| `/decisions/mode` | POST | Switch autonomous mode (SEMI/FULL_AUTO) |
| `/ontology` | GET | Full ontology graph (objects + relationships) |
| `/ontology/alerts` | GET | Current alert states per asset |
| `/chat/threads` | GET | List chat threads |
| `/chat/threads/{id}/message` | POST | Send a message to the AI |
| `/reasoning/trigger` | POST | Manually trigger a reasoning cycle |
| `/reasoning/history` | GET | Reasoning history log |
| `/generators` | GET | Current generator states |
| `/demo/start` | POST | Start the built-in demo scenario |
| `/restore` | POST | Reset simulation to initial state |

---

## Grid Metrics

| Parameter | Value |
|-----------|-------|
| Grid topology | 80 buses |
| Voltage levels | 400kV / 132kV / 33kV |
| Generators | 12 (nuclear, hydro, gas, wind, solar) |
| Total capacity | ~2,430 MW |
| Modeled load | ~1,800 MW |
| Transmission lines | 91 |
| Transformers | 21 |
| Simulation tick | 20ms (physics) / 100ms (stream emit) |
| Power flow method | Newton-Raphson AC |
| Dynamics method | RK4 swing equation |

---

## Palantir Product Mapping

This project is explicitly designed to demonstrate the same architectural patterns that Palantir uses in production:

| This Project | Palantir Product | What It Demonstrates |
|---|---|---|
| Ontology Store (RIDs, typed objects, relationships) | **Foundry Ontology** | Object-oriented data model over operational assets |
| Decision Engine (risk classification, approval workflow) | **AIP / Action Framework** | Human-in-the-loop AI action governance |
| Reasoning Engine (GPT-4o structured outputs) | **AIP Logic** | LLM integrated into operational workflows |
| SSE stream → React dashboard | **Foundry Workshop** | Live operational views over ontology data |
| Foundry export CSVs | **Foundry Datasets** | Uploadable datasets for ontology bootstrapping |
| BFS alert propagation | **Ontology propagation rules** | Computed properties and impact analysis |
| Audit trail + outcome monitoring | **AIP Action audit log** | Governance and traceability for AI-driven actions |

---

## Two Implementations

### `city-twin/` — Primary (Recommended)
The full-featured 80-bus Atlanta metro simulation with all components. Uses OpenAI GPT-4o for reasoning.

### `grid-twin/` — Reference Implementation
A simplified IEEE 9-bus test system — the standard benchmark used in power systems research. Uses JAX for accelerated numerics and Anthropic Claude for reasoning. Useful as a simpler entry point or for comparing reasoning backends. Includes a full `USER_GUIDE.md`.

---

## Security Notes

- **API keys** are loaded exclusively via `.env` files, which are excluded from version control by `.gitignore`
- **No secrets** are hardcoded in source code
- The backends are development servers — not production-hardened (no auth, no rate limiting). Do not expose them publicly without adding authentication
- CORS is configured for `localhost:5173` only

---

## License

MIT

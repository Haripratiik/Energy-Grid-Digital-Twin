# Energy Grid Digital Twin

![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=flat&logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.100+-009688?style=flat&logo=fastapi&logoColor=white)
![React](https://img.shields.io/badge/React-18.3-61DAFB?style=flat&logo=react&logoColor=black)
![TypeScript](https://img.shields.io/badge/TypeScript-5.7-3178C6?style=flat&logo=typescript&logoColor=white)
![OpenAI](https://img.shields.io/badge/OpenAI-GPT--4o-412991?style=flat&logo=openai&logoColor=white)
![D3](https://img.shields.io/badge/D3.js-v7-F9A03C?style=flat&logo=d3.js&logoColor=white)

> Physics-accurate power grid digital twin with an autonomous AI decision engine, real-time ontology graph, and a live React operator dashboard.

A full-stack simulation of the Atlanta metropolitan power grid — 80 buses, ~2,430 MW of generation capacity — running at near-real-time with actual power systems physics, an autonomous AI decision layer, and an interactive operator console.

---

## What This Is

This project models a large-scale urban power grid with:

- **Live physics simulation** — AC power flow solved via Newton-Raphson every 200ms, coupled with per-generator rotor dynamics using RK4 swing equation integration
- **Autonomous decision engine** — classifies grid faults by risk level, proposes corrective actions, and executes them with configurable human-in-the-loop approval
- **Asset ontology** — every grid component is a typed object with typed relationships, enabling graph-based impact propagation across the network
- **AI reasoning layer** — GPT-4o interprets live grid telemetry and generates structured, explainable operator guidance
- **Interactive operator console** — real-time D3 topology visualization, alert feed, decision queue with approve/reject controls, and multi-turn AI chat

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────┐
│                     React Frontend                       │
│  D3 Grid Topology │ Asset Graph    │ Operator Console   │
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
│  │  Ontology Store  │   │     AI Reasoning Engine      │ │
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
Energy-Grid-Digital-Twin/
├── city-twin/                   # Primary app — 80-bus Atlanta metro grid
│   ├── backend/
│   │   ├── main.py              # FastAPI server, SSE stream, API endpoints
│   │   ├── physics/
│   │   │   ├── network.py             # 80-bus topology (400kV / 132kV / 33kV)
│   │   │   ├── swing.py               # RK4 swing equation + AC power flow coupling
│   │   │   ├── ac_powerflow.py        # pandapower Newton-Raphson solver
│   │   │   ├── fault_handler.py       # Fault injection (generator, line, load, transformer)
│   │   │   └── generators/            # Per-type generator models
│   │   │       ├── nuclear.py         # High-inertia base-load
│   │   │       ├── hydro.py           # Hydro with water dynamics
│   │   │       ├── gas.py             # Fast-ramp gas peaker
│   │   │       ├── wind.py            # Ornstein-Uhlenbeck stochastic wind model
│   │   │       └── solar.py           # Stochastic solar generation model
│   │   ├── ontology/
│   │   │   ├── model.py               # GridAsset, OntologyLink, GridAlert schemas
│   │   │   └── store.py               # In-memory asset graph + alert manager
│   │   ├── decisions/
│   │   │   ├── models.py              # GridDecision, RiskLevel, AutonomousMode
│   │   │   ├── autonomous_engine.py   # Mode policy and approval logic
│   │   │   ├── risk_classifier.py     # Risk scoring algorithm
│   │   │   ├── action_executor.py     # Decision action runner
│   │   │   ├── decision_log.py        # Append-only audit trail
│   │   │   └── outcome_monitor.py     # Pre/post state snapshot comparison
│   │   ├── reasoning/
│   │   │   ├── engine.py              # GPT-4o integration with structured outputs
│   │   │   └── cached_responses.py    # Offline demo fallback responses
│   │   ├── chat/
│   │   │   ├── engine.py              # Multi-turn conversational AI engine
│   │   │   └── store.py               # Thread-based message storage
│   │   └── requirements.txt
│   └── frontend/
│       ├── src/
│       │   ├── App.tsx                # Root component, resizable 4-panel layout
│       │   ├── components/            # All UI components
│       │   ├── hooks/                 # Custom React hooks (SSE, decisions, ontology)
│       │   ├── types/                 # TypeScript interfaces
│       │   └── data/                  # Static grid data and map presets
│       ├── package.json
│       └── vite.config.ts
│
└── grid-twin/                   # Reference implementation — IEEE 9-bus test system
    ├── backend/                 # JAX-based physics, Anthropic Claude reasoning
    ├── frontend/                # Same stack, simplified UI
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
| Visualization | **D3.js v7.9** | Force-directed graphs, grid topology rendering |
| Charts | **Recharts** | Generation mix bar/pie charts |
| Animation | **Framer Motion** | Smooth transitions for alerts and decisions |
| Layout | **react-resizable-panels** | Draggable panel layout for operator console |
| Styling | **TailwindCSS 3.4** | Utility-first CSS |
| Streaming | **Server-Sent Events** | Real-time grid state without WebSocket overhead |

---

## Key Features

### Physics Simulation
- **80-bus grid topology** modeled on the Atlanta metro area across three voltage levels: 400kV transmission, 132kV sub-transmission, 33kV distribution
- **12 generators** across 5 types (nuclear, hydro, gas peaker, wind, solar) — each with distinct inertia constants, ramp rates, and stochastic behavior models
- **Newton-Raphson AC power flow** solved via pandapower every 200ms, producing per-bus voltages, angles, and line MW/Mvar flows
- **RK4 swing equation** integrated per-generator, modeling rotor angle and speed deviation — system frequency emerges naturally from the physics

### Autonomous Decision Engine
- **Risk classification** across 4 levels: `ADVISORY` (< 10 MW impact), `CONTROLLED` (< 50 MW), `CRITICAL` (< 100 MW or non-reversible), `EMERGENCY` (> 100 MW or islanding)
- **Two operating modes:**
  - `SEMI_AUTO` — ADVISORY decisions auto-execute; CONTROLLED actions have a 15-second countdown; CRITICAL/EMERGENCY require explicit operator approval
  - `FULL_AUTO` — all decisions auto-execute with a 3-second display window for manual override
- **Action types:** `LOAD_SHED`, `GEN_SETPOINT`, `LINE_SWITCH`, `TRANSFORMER_TAP`, `ISLANDING`
- **Outcome monitoring** — captures pre/post state snapshots to evaluate whether each decision achieved its intended effect
- **Audit trail** — append-only decision log with timestamps, risk levels, approval method, and outcomes

### Asset Ontology
- Asset hierarchy: `GridSystem → Region → Substation → Generator / LoadBus`
- **Typed relationships:** `POWERS`, `CONNECTED_TO`, `FEEDS`, `PART_OF`, `MONITORS`
- **BFS alert propagation** — a fault on a substation propagates impact scores to all downstream buses, lines, and districts
- Alert thresholds defined per asset type with four severity levels: `INFO`, `WARNING`, `CRITICAL`, `EMERGENCY`

### AI Reasoning Layer
- GPT-4o called with full grid telemetry context and a structured output schema (`DecisionResponse`) that enforces typed proposed actions
- Full reasoning history displayed in the operator console for explainability and auditability
- Multi-turn chat interface lets operators ask natural language questions about current grid state
- Graceful offline fallback to pre-written cached responses if the API is unavailable

### Interactive Operator Console
- **Grid Topology panel** — D3 force-directed graph of all 80 buses and 91 transmission lines; nodes color-coded by voltage level, pulsing animation on active fault
- **Asset Graph panel** — live force-directed visualization of grid objects and their typed relationships
- **Decision Queue** — pending decisions with risk badge, proposed actions list, countdown timer, and approve/reject/revert controls
- **Alert Feed** — real-time stream of threshold violations with severity color coding
- **Generator Mix** — live bar and pie charts of current dispatch by generator type
- **Fault Injector** — inject any of 4 fault types (`GEN_DROPOUT`, `LINE_TRIP`, `LOAD_SPIKE`, `TRAFO_TRIP`) onto any target asset

---

## Getting Started

### Prerequisites

- Python 3.11+
- Node.js 18+
- An OpenAI API key (GPT-4o)

### 1. Backend Setup

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

API available at `http://localhost:8000`
Auto-generated API docs at `http://localhost:8000/docs`

### 2. Frontend Setup

```bash
cd city-twin/frontend

# Install dependencies
npm install

# Start the dev server
npm run dev
```

UI available at `http://localhost:5173`

### 3. Demo Mode (No API Key Required)

The reasoning engine automatically falls back to cached responses if no API key is configured. All physics simulation and decision engine features work fully offline — only the AI reasoning requires a key.

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
| `/ontology` | GET | Full asset graph (objects + relationships) |
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
| Buses | 80 |
| Voltage levels | 400kV / 132kV / 33kV |
| Generators | 12 (nuclear, hydro, gas, wind, solar) |
| Total capacity | ~2,430 MW |
| Modeled load | ~1,800 MW |
| Transmission lines | 91 |
| Transformers | 21 |
| Physics tick | 20ms (RK4) |
| Stream emit rate | 100ms |
| Power flow method | Newton-Raphson AC |
| Dynamics method | RK4 swing equation |

---

## Two Implementations

### `city-twin/` — Primary (Recommended)
The full-featured 80-bus Atlanta metro simulation with the complete decision engine, ontology, reasoning, and chat systems. Uses OpenAI GPT-4o.

### `grid-twin/` — Reference Implementation
A simplified IEEE 9-bus test system — the standard academic benchmark in power systems engineering. Uses JAX for accelerated numerics and Anthropic Claude for reasoning. Good as a lighter entry point or for comparing AI reasoning backends. Includes a full `USER_GUIDE.md`.

---

## Security Notes

- API keys are loaded exclusively via `.env` files, which are excluded from version control via `.gitignore`
- No secrets are hardcoded anywhere in the source code
- These are development servers — not production-hardened. Do not expose them publicly without adding authentication and rate limiting
- CORS is configured for `localhost:5173` only

---

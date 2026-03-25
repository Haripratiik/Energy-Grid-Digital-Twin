# Energy Grid Digital Twin — Palantir AIP/Foundry Demo

A production-grade **Energy Grid Digital Twin** demonstrating Palantir-style
operational intelligence architecture: **Foundry (ontology/data ops) + AIP (LLM
agent reasoning) + Gotham-style alert/action feed**.

## Architecture

```
                       ┌──────────────────────────────────┐
                       │         REACT FRONTEND           │
                       │  GridTopology │ Ontology │ Console│
                       └──────┬────────┬──────────┬───────┘
                         SSE  │  REST  │   REST   │
                       ┌──────▼────────▼──────────▼───────┐
                       │          FASTAPI BACKEND          │
                       │                                   │
                       │  ┌─────────┐  ┌──────────────┐   │
                       │  │ Physics │  │   Ontology    │   │
                       │  │ Engine  │──│    Store      │   │
                       │  │ (JAX)   │  │  (Foundry)   │   │
                       │  └────┬────┘  └──────┬───────┘   │
                       │       │              │           │
                       │  ┌────▼──────────────▼───────┐   │
                       │  │   Alert Manager (Gotham)   │   │
                       │  └────────────┬──────────────┘   │
                       │               │                   │
                       │  ┌────────────▼──────────────┐   │
                       │  │  Reasoning Engine (AIP)    │   │
                       │  │  Anthropic Claude Sonnet   │   │
                       │  └───────────────────────────┘   │
                       └──────────────────────────────────┘
```

## Palantir Product Mapping

```
Component                       Maps to Palantir Product
────────────────────────────────────────────────────────
Ontology layer (store.py)       Foundry Ontology
Physics → ontology sync         Foundry data pipeline
LLM reasoning engine            AIP Logic / AIP Agent Studio
Alert feed                      Gotham event/threat tracking
Operator console                Foundry Workshop application
BFS propagation                 Ontology Object Explorer
```

## Physics

The simulator solves DC power flow on the IEEE 9-bus test system via the nodal
susceptance (B-matrix) method using JAX, coupled with swing equation rotor
dynamics integrated via 4th-order Runge-Kutta at 10ms timesteps. System
frequency is derived from the mean rotor speed deviation across all online
generators.

## Why This Architecture Matters

Palantir's core commercial thesis is that their Foundry Ontology acts as the
"operating system for decisions" — turning raw sensor telemetry into governed,
AI-queryable business objects. This demo embodies that thesis: raw physics
telemetry is ingested into a typed ontology of real-world grid assets, enabling
an LLM agent (GRID-AI) to reason over governed objects with full operational
context rather than hallucinating in a vacuum. The alert feed mirrors Gotham's
threat tracking UX, and the operator console mirrors a Foundry Workshop
application. This is the exact pattern Palantir deploys for bp's Vertex
platform and utility grid monitoring contracts.

## How to Run

### Backend

```bash
cd grid-twin/backend
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

Set your Anthropic API key in `backend/.env`:
```
ANTHROPIC_API_KEY=sk-ant-...
```

### Frontend

```bash
cd grid-twin/frontend
npm install
npm run dev
```

Open `http://localhost:5173` in your browser.

## Demo Scenario

Click **RUN DEMO SCENARIO** in the header bar to execute a pre-scripted cascade
failure sequence: load surge → line overload → protection relay trip → cascade
imminent → GRID-AI auto-analysis → angle instability. Click **RESTORE** to
watch the system recover.

# Grid Twin: IEEE 9-Bus Reference

A compact reference implementation of the digital twin idea on the IEEE 9-bus test system, the standard academic benchmark in power systems. It pairs a JAX based physics core with an ontology layer, an alert and action feed, and an LLM reasoning engine, and serves a live operator console.

This is the frozen reference. The primary, full featured application is [`city-twin/`](../city-twin/). Grid Twin is kept as a lighter example and as a way to compare reasoning backends (it uses Anthropic Claude, while city-twin uses OpenAI GPT-4o).

## Architecture

```
                       ┌──────────────────────────────────┐
                       │         REACT FRONTEND            │
                       │  GridTopology │ Ontology │ Console │
                       └──────┬────────┬──────────┬────────┘
                         SSE  │  REST  │   REST   │
                       ┌──────▼────────▼──────────▼────────┐
                       │          FASTAPI BACKEND          │
                       │                                   │
                       │  ┌─────────┐  ┌──────────────┐    │
                       │  │ Physics │  │   Ontology    │   │
                       │  │ Engine  │──│    Store      │   │
                       │  │ (JAX)   │  │ (object graph)│   │
                       │  └────┬────┘  └──────┬───────┘    │
                       │       │              │            │
                       │  ┌────▼──────────────▼───────┐    │
                       │  │       Alert Manager        │   │
                       │  └────────────┬──────────────┘    │
                       │               │                   │
                       │  ┌────────────▼──────────────┐    │
                       │  │      Reasoning Engine      │    │
                       │  │   Anthropic Claude Sonnet  │    │
                       │  └───────────────────────────┘    │
                       └──────────────────────────────────┘
```

## Physics

The simulator solves DC power flow on the IEEE 9-bus test system through the nodal susceptance (B matrix) method using JAX, coupled with swing equation rotor dynamics integrated by fourth order Runge-Kutta at 10 ms timesteps. System frequency is derived from the mean rotor speed deviation across all online generators.

## Why the ontology matters

Raw physics telemetry is ingested into a typed ontology of grid assets, so the LLM reasoning agent reasons over governed objects with full operational context rather than over loose numbers. The alert feed tracks threshold violations as events, and the operator console presents the live state, the asset graph, and the reasoning output together.

## How to run

### Backend

```bash
cd grid-twin/backend
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

Set your Anthropic API key in `backend/.env`:

```
ANTHROPIC_API_KEY=your-anthropic-api-key
```

### Frontend

```bash
cd grid-twin/frontend
npm install
npm run dev
```

Open `http://localhost:5173` in your browser.

## Demo scenario

Click Run Demo Scenario in the header to execute a pre scripted cascade sequence: a load surge, a line overload, a protection relay trip, a cascade warning, an automatic AI analysis, and angle instability. Click Restore to watch the system recover.

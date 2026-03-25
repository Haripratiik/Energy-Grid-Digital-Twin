# Energy Grid Digital Twin — User Guide

---

## What Is This?

This is a **real-time power grid simulator** built as a Palantir FDSE portfolio
demo. It models the **IEEE 9-bus test system** — a standard benchmark network
used by power engineers worldwide — and wraps it in a Palantir-style
operational intelligence architecture.

The point of this demo is to show three things simultaneously:

1. You can build real, physics-accurate simulations (not toy animations)
2. You understand how Palantir's product stack works architecturally
3. You know how to deploy an LLM agent that reasons over governed data objects,
   not just a chatbot floating in a vacuum

---

## Before You Start

### Prerequisites

- Python 3.11+
- Node.js 18+
- An Anthropic API key (optional — works without one using cached responses)

### One-Time Setup

**Backend:**
```
cd grid-twin/backend
pip install -r requirements.txt
```

**Frontend:**
```
cd grid-twin/frontend
npm install
```

**API Key (optional):**

Open `grid-twin/backend/.env` and replace the placeholder:
```
ANTHROPIC_API_KEY=sk-ant-your-key-here
```

If you leave the placeholder, the app still works — GRID-AI will use a
pre-written cached response for the demo scenario.

---

## Running the App

You need two terminals open at the same time.

**Terminal 1 — Start the backend:**
```
cd grid-twin/backend
uvicorn main:app --reload --port 8000
```

You should see:
```
INFO: Simulation loop started
INFO: Uvicorn running on http://127.0.0.1:8000
```

**Terminal 2 — Start the frontend:**
```
cd grid-twin/frontend
npm run dev
```

You should see:
```
VITE ready in 554ms
Local: http://localhost:5173/
```

**Then open your browser to:** `http://localhost:5173`

---

## The Interface — A Tour

The app is divided into three vertical panels and a header bar.

```
┌─────────────────────────────────────────────────────────────────┐
│  HEADER — title, sim clock, live frequency, connection status   │
├─────────────────────┬──────────────┬────────────────────────────┤
│                     │              │  System Metrics (live)     │
│  PANEL 1            │  PANEL 2     │  ─────────────────────     │
│  Grid Topology      │  Foundry     │  Alert Feed                │
│  (D3 physics viz)   │  Ontology    │  ─────────────────────     │
│                     │  Graph       │  GRID-AI Reasoning         │
│  [Fault Injector]   │              │                            │
└─────────────────────┴──────────────┴────────────────────────────┘
```

---

### The Header Bar

| Element | What it shows |
|---|---|
| Title | "Grid Twin · Palantir AIP · IEEE 9-Bus" |
| Sim Clock | How many simulation seconds have elapsed (HH:MM:SS) |
| Frequency | System frequency in Hz — **green** = normal, **yellow** = warning, **red** = critical |
| Status Dot | Connection to backend — green = live, yellow = reconnecting, red = disconnected |
| RUN DEMO SCENARIO | Starts the pre-scripted cascade failure sequence |

---

### Panel 1 — Grid Topology

This is the live physics visualization. It shows the actual IEEE 9-bus network
as a graph.

**What you're looking at:**

- **Hexagonal nodes** (Bus 1, 2, 3) are generators — sized roughly by power
  output. Color means health: green = nominal, yellow = rotor angle warning,
  red = near instability, gray = offline.

- **Circular nodes with labels** (Bus 5, 6, 8) are load buses — they consume
  power. The number inside shows current MW demand.

- **Small circles** (Bus 4, 7, 8, 9) are junction/transmission buses with no
  direct load or generation.

- **Lines between nodes** are transmission lines. Their thickness and color
  show how loaded they are:
  - Thin + green = lightly loaded (under 60%)
  - Thicker + yellow = getting stressed (60–80%)
  - Thick + red = overloaded (80%+)
  - Dashed + gray = tripped (disconnected from network)

**The Fault Injector (bottom of Panel 1):**

This lets you manually break things:

| Fault Type | What it does |
|---|---|
| `LINE_TRIP` | Disconnects a transmission line (simulates a protection relay operating) |
| `GEN_DROPOUT` | Takes a generator offline (simulates a generator trip) and redistributes its load proportionally by inertia |
| `LOAD_SPIKE` | Adds MW demand to a load bus (simulates a demand surge event) |

Select the fault type, pick a target from the dropdown, set a magnitude (for
load spikes), and click **INJECT**. Click **RESTORE NOMINAL** to reset
everything.

---

### Panel 2 — Foundry Ontology Graph

This panel represents the **Palantir Foundry Ontology layer** — the same
concept Palantir deploys for utilities, oil & gas companies, and supply chains.

Instead of showing raw sensor data, it shows the grid modeled as **typed
objects with typed relationships**. The LLM agent (GRID-AI) reads this graph,
not raw telemetry.

**Object types (shown by shape):**

| Shape | Type | What it represents |
|---|---|---|
| Large circle | GridSystem | The whole IEEE 9-bus network |
| Rounded square | Substation | A physical substation grouping (A, B, or C) |
| Diamond | Generator | An individual generator |
| Small circle (gray) | TransmissionLine | A transmission line |
| Small circle (yellow) | LoadBus | A load or junction bus |

**Node colors show status:**
- Normal type color = NOMINAL
- Yellow = DEGRADED
- Red = CRITICAL or OVERLOADED
- Gray/faded = TRIPPED

**Click any node** to see its full property dictionary — the exact properties
the LLM agent sees when it reasons about that object.

The graph is force-directed (nodes push apart from each other). You can drag
nodes to rearrange.

---

### Panel 3 — Operator Console

Three stacked sub-panels:

**Top: System Metrics**

Six live readouts updated every 100ms:
- System frequency (Hz) — color coded to deviation from 60Hz
- Total generation (MW)
- Total load (MW)
- Generation surplus/deficit
- Active alert count
- Simulation elapsed time

**Middle: Alert Feed**

Every time a physics threshold is crossed, an alert appears here, sliding in
from the right with a color-coded severity badge:

| Color | Severity | Example |
|---|---|---|
| Blue | INFO | A line was manually tripped |
| Yellow | WARNING | A line is over 80% thermal loading |
| Red (pulsing) | CRITICAL | Cascade imminent, angle instability |

Click any **asset chip** inside an alert (e.g. "Line 5-6") to highlight that
asset in Panel 1.

Alert types and their meanings:

| Alert | Trigger | Meaning |
|---|---|---|
| `LINE_OVERLOAD` | Line flow > 80% of thermal limit | Line is getting dangerously loaded |
| `CASCADE_IMMINENT` | 2+ lines simultaneously overloaded | Multiple overloads suggest cascade failure is starting |
| `ANGLE_INSTABILITY` | Generator rotor angle diverges > 60° from reference | Generator is losing synchronism — may slip poles |
| `FREQ_DEVIATION` | Frequency deviates > 0.5 Hz from 60Hz | Generation/load imbalance is growing |
| `FREQ_CRITICAL` | Frequency deviates > 1.0 Hz | Serious imbalance — load shedding required |
| `LINE_TRIPPED` | A line was disconnected | Network topology changed |

**Bottom: GRID-AI (AIP Layer)**

This is the LLM reasoning panel. It represents **Palantir AIP** — their AI
logic layer that sits on top of the ontology.

- **Idle state:** Shows "Monitoring ontology for anomalies..." and a **QUERY
  GRID-AI** button. Click it anytime for a manual analysis.

- **Auto-trigger:** When a CRITICAL alert fires, GRID-AI automatically analyzes
  the situation. The dot in the header pulses green while it's working.

- **Response format:** GRID-AI always responds in exactly three sections:
  - **SITUATION** — 2 sentences, what's happening and severity
  - **IMMEDIATE ACTIONS** — up to 3 numbered actions naming specific assets
  - **RISK ASSESSMENT** — probability of cascade failure and time horizon

- **History:** The last 5 reasoning calls are collapsible below the response.

---

## The Demo Scenario

Click **RUN DEMO SCENARIO** in the header bar to run this pre-scripted sequence:

| Time | Event | What to watch |
|---|---|---|
| t=0s | System starts at nominal | All green, 60.0 Hz |
| t=4s | Load spike +80 MW at Bus 5 | Line 4-5 loading climbs, frequency dips slightly |
| t=8s | Line 5-6 hits overload threshold | WARNING alert fires, line turns yellow/red |
| t=12s | Line 6-7 trips (protection relay) | Line goes gray and dashed, loads redistribute |
| t=14s | Lines 5-6 and 8-9 both overloaded | CASCADE_IMMINENT CRITICAL fires, GRID-AI auto-triggers |
| t=16s | GRID-AI streams response | Watch the reasoning panel — it names specific assets and actions |
| t=22s | Generator 3 rotor angle diverges | ANGLE_INSTABILITY fires |
| t=28s | Demo pauses | Click RESTORE to watch the system recover |

After clicking **RESTORE**, the grid resets to nominal and you can inject your
own faults.

---

## How the Physics Works

The simulation runs a real power engineering model, not an animation.

**DC Power Flow (every 100ms):**

The network is modeled as a susceptance matrix (B-matrix). Given the current
generator bus angles and load demands, the system solves:

```
B_reduced × θ = P_inject
```

This is a standard linear algebra solve (via JAX on CPU) that gives the voltage
angle at every bus. From those angles, you get power flow on every line:

```
P_line = (θ_from - θ_to) / X_line   [in per-unit, × 100 to get MW]
```

**Swing Equation (10ms timestep, RK4):**

Generator rotor dynamics are governed by:

```
M × d²δ/dt² + D × dδ/dt = P_mechanical - P_electrical
```

Where δ is the rotor angle, ω = dδ/dt is rotor speed, M is inertia (10, 6, 3
MJ/MVA for generators 1–3), and D=1 is the damping coefficient. The simulation
uses 4th-order Runge-Kutta integration. When P_m ≠ P_e (e.g. after a fault),
the rotor accelerates or decelerates, which shifts bus angles, which changes
line flows — the cascade mechanism.

**System frequency:**

```
f = 60.0 + mean(ω) / (2π)   [Hz]
```

**Why it stays stable normally:** At startup, P_m = P_e for every generator
exactly (computed from the initial power flow solution). There's no imbalance,
so ω stays at zero and the frequency stays at 60 Hz. Faults break this
equilibrium.

---

## Architecture Summary

```
Physics Engine (JAX)
    │  solves every 10ms
    ▼
Ontology Store (Foundry layer)
    │  updates typed objects, propagates status
    ▼
Alert Manager (Gotham layer)
    │  evaluates thresholds, emits alerts
    ▼
Reasoning Engine (AIP layer)
    │  LLM reads ontology + alerts, produces operator guidance
    ▼
SSE Stream → React Frontend
    │
    ├── Panel 1: D3 Grid Topology (live physics viz)
    ├── Panel 2: D3 Ontology Graph (Foundry objects)
    └── Panel 3: Metrics + Alert Feed + GRID-AI (Gotham + AIP)
```

| Code Layer | Maps to Palantir Product |
|---|---|
| `physics/` | The raw sensor/telemetry layer |
| `ontology/store.py` | Foundry Ontology |
| `ontology/store.py` (update loop) | Foundry data pipeline |
| `ontology/store.py` (BFS propagation) | Ontology Object Explorer |
| `ontology/store.py` (AlertManager) | Gotham event/threat tracking |
| `reasoning/engine.py` | AIP Logic / AIP Agent Studio |
| `components/OperatorConsole.tsx` | Foundry Workshop application |

---

## API Reference

The backend exposes these REST/SSE endpoints:

| Method | Path | Description |
|---|---|---|
| `GET` | `/stream` | SSE — emits `GridState` JSON every 100ms |
| `POST` | `/fault` | Inject a fault `{ type, target_rid, magnitude_mw }` |
| `POST` | `/restore` | Reset grid to nominal state |
| `GET` | `/ontology` | Full Foundry ontology object graph |
| `GET` | `/ontology/propagation?alert_id=X` | BFS subgraph for a given alert |
| `GET` | `/alerts?limit=50` | Recent alerts |
| `POST` | `/reasoning` | Trigger GRID-AI analysis manually |
| `POST` | `/demo` | Start the demo scenario |
| `GET` | `/health` | `{ status, sim_time_s, uptime_s }` |

---

## Troubleshooting

**"Connection" dot is yellow or red:**

The frontend can't reach the backend. Make sure `uvicorn` is running on port
8000. Check that nothing else is using that port.

**GRID-AI says "Anthropic API call failed":**

Your API key is missing or invalid. Open `backend/.env`, add your key, and
restart the backend. The app will fall back to the cached demo response if the
key is absent.

**Physics looks unrealistic after many faults:**

The simulator clamps extreme rotor angles to ±180° to prevent numerical
overflow. Click **RESTORE NOMINAL** to reset to a clean initial state.

**TPU warning in the backend log:**

```
Unable to initialize backend 'tpu': UNIMPLEMENTED: LoadPjrtPlugin is not implemented on windows yet.
```

This is harmless. JAX is correctly falling back to CPU mode as intended.

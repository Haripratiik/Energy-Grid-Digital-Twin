import os
import asyncio
import json
import logging
import time
import warnings
from contextlib import asynccontextmanager
from typing import Optional

warnings.filterwarnings("ignore", message=".*numba.*")

logging.getLogger("physics.ac_powerflow").setLevel(logging.ERROR)
logging.getLogger("pandapower").setLevel(logging.ERROR)
logging.getLogger("openai._base_client").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)

from dotenv import load_dotenv
from fastapi import FastAPI, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from ontology.model import GridAlert
from ontology.store import AlertManager, OntologyStore
from physics.contingency import ContingencyAnalyzer, ContingencyReport
from physics.fault_handler import FaultHandler, FaultRequest, FaultType
from physics.swing import GridSimulator, GridState
from storage import GridStore
from reasoning.engine import ReasoningEngine
from decisions.models import AutonomousMode, ProposedAction
from decisions.autonomous_engine import AutonomousEngine
from chat.store import ChatStore, ChatMessage
from chat.engine import ChatEngine

load_dotenv()

logging.basicConfig(level=logging.INFO)
logging.getLogger("pandapower.auxiliary").setLevel(logging.ERROR)
logger = logging.getLogger(__name__)

simulator: GridSimulator
fault_handler: FaultHandler
ontology_store: OntologyStore
alert_manager: AlertManager
reasoning_engine: ReasoningEngine
autonomous_engine: AutonomousEngine
chat_store: ChatStore
chat_engine: ChatEngine
contingency_analyzer: ContingencyAnalyzer
store: GridStore

_broadcast_queues: list[asyncio.Queue] = []
_sim_task: Optional[asyncio.Task] = None
_demo_running: bool = False
_demo_phase: Optional[str] = None
_last_auto_reasoning: float = 0.0

# N-1 contingency analysis runs off the physics tick on a throttled cadence.
CONTINGENCY_INTERVAL_S: float = 3.0
_latest_contingency: Optional[ContingencyReport] = None
_last_contingency_run: float = 0.0
_contingency_running: bool = False

# Telemetry / decisions are persisted on a throttled cadence.
PERSIST_INTERVAL_S: float = 1.0
_last_persist_run: float = 0.0


def _contingency_summary() -> Optional[dict]:
    """Compact summary merged into the SSE stream (full report via /contingencies)."""
    if _latest_contingency is None:
        return None
    r = _latest_contingency
    worst = r.worst
    return {
        "base_secure": r.base_secure,
        "n_insecure": r.n_insecure,
        "n_screened": r.n_screened,
        "worst": None if worst is None else {
            "contingency_id": worst.contingency_id,
            "label": worst.label,
            "outcome": worst.outcome.value,
            "severity": worst.severity,
        },
    }


def _sim_tick():
    """Run one simulation step (CPU-bound, called in thread)."""
    return simulator.step()


async def _run_contingency(state: GridState) -> None:
    """Run N-1 analysis in a worker thread; store the latest report."""
    global _latest_contingency, _contingency_running
    _contingency_running = True
    loop = asyncio.get_event_loop()
    try:
        _latest_contingency = await loop.run_in_executor(
            None, contingency_analyzer.analyze, state,
        )
    except Exception:
        logger.exception("Contingency analysis failed")
    finally:
        _contingency_running = False


async def simulation_loop() -> None:
    global _last_contingency_run
    loop = asyncio.get_event_loop()
    while True:
        state = await loop.run_in_executor(None, _sim_tick)
        if state is not None:
            new_alerts = alert_manager.evaluate(state)
            all_alerts = alert_manager.alerts
            # Keep the simulator's computed ontology_dirty (true only on real
            # topology changes) so the frontend refetches the ontology on
            # changes, not every tick.
            state = state.model_copy(update={
                "active_alerts": [a.model_dump() for a in all_alerts[-30:]],
            })
            ontology_store.update_from_physics_state(state)

            autonomous_engine.tick(state)

            if not _demo_running:
                for alert in new_alerts:
                    if alert.severity in ("CRITICAL", "WARNING"):
                        asyncio.create_task(autonomous_engine.on_alert(
                            alert.type, alert.severity, state, alert.id
                        ))
                        break

            now = time.time()
            if not _contingency_running and now - _last_contingency_run >= CONTINGENCY_INTERVAL_S:
                _last_contingency_run = now
                asyncio.create_task(_run_contingency(state))

            global _last_persist_run
            if now - _last_persist_run >= PERSIST_INTERVAL_S:
                _last_persist_run = now
                try:
                    store.record_telemetry(state, run_id="live")
                    for d in autonomous_engine.decision_log.get_all(50):
                        store.record_decision(d.model_dump(mode="json"))
                except Exception:
                    logger.exception("Persistence write failed")

            data = state.model_dump(mode="json")
            data["contingency"] = _contingency_summary()
            payload = json.dumps(data)
            dead: list[asyncio.Queue] = []
            for q in _broadcast_queues:
                try:
                    q.put_nowait(payload)
                except asyncio.QueueFull:
                    dead.append(q)
            for q in dead:
                _broadcast_queues.remove(q)

        await asyncio.sleep(0.05)


async def run_demo_scenario() -> None:
    global _demo_running, _demo_phase
    _demo_running = True
    _demo_phase = "Restoring nominal state"
    logger.info("DEMO SCENARIO: Starting")

    simulator.restore()
    alert_manager._alerts.clear()
    alert_manager._last_fired.clear()
    autonomous_engine.decision_log.clear()
    await asyncio.sleep(4.0)

    _demo_phase = "Injecting load spike — Bus 14 (+100 MW)"
    logger.info("DEMO t=4s: LOAD_SPIKE on Bus 14, +100 MW")
    fault_handler.apply(FaultRequest(
        type=FaultType.LOAD_SPIKE,
        target_rid="ri.city-grid.main.load-bus.14",
        magnitude_mw=100.0,
    ))
    await asyncio.sleep(6.0)

    _demo_phase = "Transformer 3 tripped"
    logger.info("DEMO t=10s: TRAFO_TRIP on transformer 3")
    fault_handler.apply(FaultRequest(
        type=FaultType.TRAFO_TRIP,
        target_rid="ri.city-grid.main.transformer.3",
    ))
    await asyncio.sleep(4.0)

    _demo_phase = "GRID-AI analysing cascade scenario"
    logger.info("DEMO t=14s: Triggering GRID-AI analysis")
    state = simulator.get_state()
    reasoning_engine._demo_mode = True
    result = reasoning_engine.analyze(state, None, "AUTO_CRITICAL", "demo-cascade")
    reasoning_engine._demo_mode = False

    from decisions.models import GridDecision
    from decisions.risk_classifier import RiskClassifier
    from decisions.outcome_monitor import OutcomeMonitor
    pre_snap = OutcomeMonitor.capture_snapshot(state)
    for pa_dict in result.proposed_actions:
        pa = ProposedAction(**pa_dict)
        risk = RiskClassifier.classify(pa)
        decision = GridDecision(
            risk_level=risk,
            action=pa,
            triggered_by_alert_id="demo-cascade",
            pre_state_snapshot=pre_snap,
        )
        autonomous_engine._apply_mode_policy(decision)
        autonomous_engine.decision_log.record(decision)

    _demo_phase = "Decisions queued — monitoring response"
    await asyncio.sleep(8.0)

    _demo_phase = "Line 12 tripped — cascading event"
    logger.info("DEMO t=22s: LINE_TRIP on line index 12")
    fault_handler.apply(FaultRequest(
        type=FaultType.LINE_TRIP,
        target_rid="ri.city-grid.main.transmission-line.12",
    ))
    await asyncio.sleep(8.0)

    _demo_phase = "Complete — use RESTORE to recover"
    logger.info("DEMO SCENARIO: Complete. Click RESTORE to recover.")
    await asyncio.sleep(5.0)
    _demo_running = False
    _demo_phase = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global simulator, fault_handler, ontology_store, alert_manager
    global reasoning_engine, autonomous_engine, chat_store, chat_engine, _sim_task
    global contingency_analyzer, store

    simulator = GridSimulator(
        protection_enabled=os.getenv("GRID_PROTECTION", "0") == "1",
        governor_enabled=os.getenv("GRID_GOVERNOR", "0") == "1",
    )
    fault_handler = FaultHandler(simulator)
    ontology_store = OntologyStore()
    alert_manager = AlertManager()
    contingency_analyzer = ContingencyAnalyzer()
    store = GridStore(os.getenv("GRID_DB_PATH", "grid_twin.db"))

    api_key = os.getenv("OPENAI_API_KEY", "")
    demo_mode = not api_key or api_key == "your-api-key-here"
    reasoning_engine = ReasoningEngine(api_key, demo_mode=demo_mode)
    autonomous_engine = AutonomousEngine(simulator, reasoning_engine)
    chat_store = ChatStore()
    chat_engine = ChatEngine(api_key, demo_mode=demo_mode)

    _sim_task = asyncio.create_task(simulation_loop())
    logger.info("Simulation loop started (city-twin v2)")

    yield

    if _sim_task:
        _sim_task.cancel()
        try:
            await _sim_task
        except asyncio.CancelledError:
            pass
    try:
        store.close()
    except Exception:
        pass


app = FastAPI(title="City-Twin Grid API v2", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- SSE Stream ---

@app.get("/stream")
async def stream_state(request: Request):
    queue: asyncio.Queue = asyncio.Queue(maxsize=50)
    _broadcast_queues.append(queue)

    async def event_generator():
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    payload = await asyncio.wait_for(queue.get(), timeout=1.0)
                    yield f"data: {payload}\n\n"
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            if queue in _broadcast_queues:
                _broadcast_queues.remove(queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# --- Fault Injection ---

@app.post("/fault")
async def inject_fault(req: FaultRequest):
    msg = fault_handler.apply(req)
    return {"status": "ok", "message": msg}


@app.post("/restore")
async def restore():
    global _demo_running, _demo_phase
    simulator.restore()
    alert_manager._alerts.clear()
    alert_manager._last_fired.clear()
    autonomous_engine.decision_log.clear()
    _demo_running = False
    _demo_phase = None
    return {"status": "ok", "message": "System restored to nominal conditions"}


# --- Ontology ---

@app.get("/ontology")
async def get_ontology():
    return ontology_store.get_ontology()


@app.get("/ontology/propagation")
async def get_propagation(alert_id: str = Query(...)):
    return ontology_store.get_propagation(alert_id, alert_manager.alerts)


# --- Contingency Analysis (N-1) ---

@app.get("/contingencies")
async def get_contingencies(
    limit: int = Query(25, ge=1, le=200),
    refresh: bool = Query(False),
):
    """Latest N-1 contingency report. Pass ?refresh=true to recompute now."""
    global _latest_contingency
    if refresh or _latest_contingency is None:
        loop = asyncio.get_event_loop()
        _latest_contingency = await loop.run_in_executor(
            None, contingency_analyzer.analyze, simulator.get_state(),
        )
    report = _latest_contingency
    data = report.model_dump(mode="json")
    data["results"] = data["results"][:limit]
    return data


# --- History (persisted) ---

@app.get("/history/telemetry")
async def history_telemetry(
    run_id: str = Query("live"),
    limit: int = Query(500, ge=1, le=5000),
):
    return store.telemetry_history(run_id=run_id, limit=limit)


@app.get("/history/decisions")
async def history_decisions(limit: int = Query(100, ge=1, le=500)):
    return store.decision_history(limit=limit)


@app.get("/history/eval")
async def history_eval(
    scenario_id: Optional[str] = Query(None),
    limit: int = Query(200, ge=1, le=1000),
):
    return store.eval_runs(scenario_id=scenario_id, limit=limit)


@app.get("/history/stats")
async def history_stats():
    return store.counts()


# --- Alerts ---

@app.get("/alerts")
async def get_alerts(limit: int = Query(50, ge=1, le=200)):
    alerts = alert_manager.alerts
    return alerts[-limit:]


# --- Reasoning ---

class ReasoningRequest(BaseModel):
    query: str = ""


@app.post("/reasoning")
async def trigger_reasoning(req: Optional[ReasoningRequest] = None):
    state = simulator.get_state()
    user_query = (req.query.strip() if req and req.query else None) or None
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(
        None, reasoning_engine.analyze,
        state, None, "MANUAL", None, user_query,
    )
    return result


# --- Chat ---

class ChatMessageRequest(BaseModel):
    content: str


@app.get("/chat/threads")
async def list_chat_threads():
    return chat_store.list_threads()


@app.post("/chat/threads")
async def create_chat_thread():
    thread = chat_store.create_thread()
    return {"id": thread.id, "title": thread.title, "created_at": thread.created_at.isoformat()}


@app.get("/chat/threads/{thread_id}/messages")
async def get_chat_messages(thread_id: str):
    messages = chat_store.get_messages(thread_id)
    if messages is None:
        return {"error": "Thread not found"}
    return [m.model_dump(mode="json") for m in messages]


@app.post("/chat/threads/{thread_id}/messages")
async def send_chat_message(thread_id: str, req: ChatMessageRequest):
    thread = chat_store.get_thread(thread_id)
    if thread is None:
        return {"error": "Thread not found"}

    user_msg = ChatMessage(role="user", content=req.content)
    chat_store.add_message(thread_id, user_msg)

    state = simulator.get_state()
    history = chat_store.get_messages(thread_id) or []
    loop = asyncio.get_event_loop()
    assistant_msg = await loop.run_in_executor(
        None, chat_engine.respond, req.content, history[:-1], state,
    )
    chat_store.add_message(thread_id, assistant_msg)

    return assistant_msg.model_dump(mode="json")


@app.delete("/chat/threads/{thread_id}")
async def delete_chat_thread(thread_id: str):
    if chat_store.delete_thread(thread_id):
        return {"status": "ok"}
    return {"error": "Thread not found"}


# --- Decision Engine ---

@app.get("/mode")
async def get_mode():
    return {"mode": autonomous_engine.mode.value}


class ModeRequest(BaseModel):
    mode: str


@app.post("/mode")
async def set_mode(req: ModeRequest):
    try:
        autonomous_engine.mode = AutonomousMode(req.mode)
        return {"status": "ok", "mode": autonomous_engine.mode.value}
    except ValueError:
        return {"status": "error", "message": f"Invalid mode: {req.mode}"}


@app.get("/decisions/pending")
async def get_pending_decisions():
    return autonomous_engine.decision_log.get_pending()


@app.get("/decisions/log")
async def get_decision_log(limit: int = Query(100, ge=1, le=500)):
    return autonomous_engine.decision_log.get_all(limit)


class VerifyActionRequest(BaseModel):
    action_type: str
    target_rid: str
    parameters: dict = {}
    estimated_impact_mw: float = 0.0
    reversible: bool = True


@app.post("/verify-action")
async def verify_action(req: VerifyActionRequest):
    """Physics safety check: would this action keep the grid secure? (re-solves power flow)"""
    from decisions.models import ProposedAction

    try:
        pa = ProposedAction(
            action_type=req.action_type, target_rid=req.target_rid,
            parameters=req.parameters, rationale="manual check", confidence=1.0,
            estimated_impact_mw=req.estimated_impact_mw, reversible=req.reversible,
        )
    except Exception as exc:  # noqa: BLE001
        return {"error": f"invalid action: {exc}"}

    state = simulator.get_state()
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(
        None, autonomous_engine._verifier.verify, state, pa,
    )
    return result.model_dump()


@app.post("/decisions/{decision_id}/approve")
async def approve_decision(decision_id: str):
    success = autonomous_engine.approve(decision_id)
    if success:
        return {"status": "ok", "message": "Decision approved and executed"}
    return {"status": "error", "message": "Decision not found or not pending"}


@app.post("/decisions/{decision_id}/reject")
async def reject_decision(decision_id: str):
    success = autonomous_engine.reject(decision_id)
    if success:
        return {"status": "ok", "message": "Decision rejected"}
    return {"status": "error", "message": "Decision not found or not pending"}


@app.post("/decisions/{decision_id}/revert")
async def revert_decision(decision_id: str):
    success = autonomous_engine.revert(decision_id)
    if success:
        return {"status": "ok", "message": "Decision reverted"}
    return {"status": "error", "message": "Cannot revert — not executed or not reversible"}


# --- Topology (static) ---

@app.get("/topology")
async def get_topology():
    """Static line/transformer connectivity for geographic + schematic rendering."""
    from physics.network import LINES, TRANSFORMERS

    return {
        "lines": [
            {"index": i, "from_bus": ln.from_bus, "to_bus": ln.to_bus,
             "voltage_kv": ln.voltage_kv}
            for i, ln in enumerate(LINES)
        ],
        "transformers": [
            {"index": i, "from_bus": t.from_bus, "to_bus": t.to_bus,
             "from_kv": t.from_kv, "to_kv": t.to_kv}
            for i, t in enumerate(TRANSFORMERS)
        ],
    }


# --- Generators ---

@app.get("/generators")
async def get_generators():
    return [g.to_dict() for g in simulator.generators]


# --- Protection (emergent cascades) ---

@app.get("/protection/events")
async def get_protection_events():
    """Chronological relay-trip log. Enable with GRID_PROTECTION=1."""
    return {
        "enabled": simulator._protection is not None,
        "events": simulator.protection_events,
    }


# --- Digital Twin (UKF state estimation) ---

@app.get("/twin/run")
async def twin_run(
    steps: int = Query(600, ge=50, le=1500),
    anomaly_step: Optional[int] = Query(400),
    measured: str = Query("0,1,2", description="comma-separated machine indices sensed"),
):
    """Run the plant/twin UKF synchronization loop and return its time series."""
    from twin.digital_twin import DigitalTwin, TwinConfig

    try:
        meas = tuple(int(x) for x in measured.split(",") if x.strip() != "")
    except ValueError:
        meas = (0, 1, 2)
    cfg = TwinConfig(measured_machines=meas or (0, 1, 2))
    dt = DigitalTwin(cfg)

    loop = asyncio.get_event_loop()
    step_list, summary = await loop.run_in_executor(
        None, lambda: dt.run(n_steps=steps, anomaly_step=anomaly_step),
    )
    return {
        "summary": summary.model_dump(),
        "anomaly_step": anomaly_step,
        "dt_s": cfg.dt,
        "steps": [s.model_dump() for s in step_list],
    }


# --- Performance (fast N-1 screening) ---

@app.get("/perf/lodf")
async def perf_lodf(case: str = Query("ieee118")):
    """Benchmark LODF fast N-1 screening vs brute force on a benchmark network."""
    import pandapower.networks as nw
    from physics.perf.benchmark import benchmark_case

    loaders = {
        "ieee118": ("IEEE-118", nw.case118),
        "case300": ("case300", nw.case300),
        "case1354": ("case1354pegase", nw.case1354pegase),
        "case2869": ("case2869pegase", nw.case2869pegase),
    }
    label, fn = loaders.get(case, loaders["ieee118"])
    loop = asyncio.get_event_loop()
    row = await loop.run_in_executor(None, lambda: benchmark_case(label, fn))
    return row.model_dump()


# --- Frequency response (inertia / grid-forming) ---

@app.get("/frequency-response")
async def frequency_response(disturbance: float = Query(0.12, gt=0.0, le=0.5)):
    """RoCoF / nadir under high inertia, low inertia (renewables), and grid-forming."""
    from physics.frequency_response import compare_inertia_scenarios
    return [r.model_dump() for r in compare_inertia_scenarios(disturbance)]


# --- WLS state estimation + bad-data detection ---

@app.get("/estimate")
async def estimate(
    case: str = Query("ieee118"),
    bad: bool = Query(False, description="inject a gross measurement error"),
    noise: float = Query(0.02, gt=0.0, le=0.2),
):
    """Run WLS state estimation on a benchmark grid; optionally inject bad data."""
    import pandapower.networks as nw
    from physics.lodf import DCSystem
    from physics.state_estimation import DCStateEstimator

    loaders = {
        "ieee14": ("IEEE-14", nw.case14),
        "ieee30": ("IEEE-30", nw.case30),
        "ieee118": ("IEEE-118", nw.case118),
    }
    label, fn = loaders.get(case, loaders["ieee118"])

    def run_se():
        dc = DCSystem.from_pandapower(fn())
        est = DCStateEstimator(dc)
        bad_idx = est.n_meas // 3 if bad else None
        z, sigma = est.simulate_measurements(
            noise_pu=noise, seed=1, bad_index=bad_idx, bad_error_pu=0.6,
        )
        result = est.estimate(z, sigma)
        return {"case": label, "injected_bad_index": bad_idx, "result": result.model_dump()}

    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, run_se)


# --- Demo ---

@app.post("/demo")
async def run_demo():
    if _demo_running:
        return {"status": "error", "message": "Demo is already running"}
    asyncio.create_task(run_demo_scenario())
    return {"status": "ok", "message": "Demo scenario started"}


@app.get("/demo/status")
async def demo_status():
    return {"active": _demo_running, "phase": _demo_phase}


# --- Health ---

@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "sim_time_s": simulator.sim_time,
        "mode": autonomous_engine.mode.value,
        "pending_decisions": len(autonomous_engine.decision_log.get_pending()),
    }

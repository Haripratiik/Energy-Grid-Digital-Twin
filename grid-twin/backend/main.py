import os

os.environ["JAX_PLATFORM_NAME"] = "cpu"
os.environ["JAX_ENABLE_X64"] = "true"

import asyncio
import json
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Optional

from dotenv import load_dotenv
from fastapi import FastAPI, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from ontology.model import GridAlert
from ontology.store import AlertManager, OntologyStore
from physics.fault_handler import FaultHandler, FaultRequest, FaultType
from physics.simulator import GridSimulator, GridState
from reasoning.engine import ReasoningEngine, ReasoningResult

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

simulator: GridSimulator
fault_handler: FaultHandler
ontology_store: OntologyStore
alert_manager: AlertManager
reasoning_engine: ReasoningEngine

_broadcast_queues: list[asyncio.Queue] = []
_sim_task: Optional[asyncio.Task] = None
_demo_running: bool = False
_last_auto_reasoning: float = 0.0


async def simulation_loop() -> None:
    global _demo_running
    while True:
        state = simulator.step()
        if state is not None:
            new_alerts = alert_manager.evaluate(state)
            all_alerts = alert_manager.alerts
            state = state.model_copy(update={
                "active_alerts": [a.model_dump() for a in all_alerts[-20:]],
                "ontology_dirty": True,
            })
            ontology_store.update_from_physics_state(state)

            import time as _time
            now = _time.time()
            for alert in new_alerts:
                if alert.severity == "CRITICAL" and not _demo_running and (now - _last_auto_reasoning) > 10.0:
                    _last_auto_reasoning = now
                    try:
                        propagation = ontology_store.get_propagation(alert.id, all_alerts)
                        result = reasoning_engine.analyze(
                            state, propagation, "AUTO_CRITICAL", alert.id
                        )
                        logger.info("Auto-triggered GRID-AI reasoning for alert %s", alert.id)
                    except Exception:
                        logger.exception("Auto reasoning failed")
                    break

            payload = state.model_dump_json()
            dead: list[asyncio.Queue] = []
            for q in _broadcast_queues:
                try:
                    q.put_nowait(payload)
                except asyncio.QueueFull:
                    dead.append(q)
            for q in dead:
                _broadcast_queues.remove(q)

        await asyncio.sleep(0.01)


async def run_demo_scenario() -> None:
    global _demo_running
    _demo_running = True
    logger.info("DEMO SCENARIO: Starting")

    simulator.restore()
    await asyncio.sleep(4.0)

    logger.info("DEMO t=4s: LOAD_SPIKE on Bus 5, +80 MW")
    fault_handler.apply(FaultRequest(
        type=FaultType.LOAD_SPIKE,
        target_rid="ri.grid-asset.main.load-bus.5",
        magnitude_mw=80.0,
    ))
    await asyncio.sleep(8.0)

    logger.info("DEMO t=12s: LINE_TRIP on line 6-7")
    fault_handler.apply(FaultRequest(
        type=FaultType.LINE_TRIP,
        target_rid="ri.grid-asset.main.transmission-line.6-7",
    ))
    await asyncio.sleep(2.0)

    logger.info("DEMO t=14s: Triggering cached GRID-AI response")
    state = simulator.get_state()
    propagation = ontology_store.get_propagation("demo", alert_manager.alerts)
    reasoning_engine._demo_mode = True
    reasoning_engine.analyze(state, propagation, "AUTO_CRITICAL", "demo-cascade")
    reasoning_engine._demo_mode = False

    await asyncio.sleep(14.0)
    logger.info("DEMO SCENARIO: Complete. Click RESTORE to recover.")
    _demo_running = False


@asynccontextmanager
async def lifespan(app: FastAPI):
    global simulator, fault_handler, ontology_store, alert_manager, reasoning_engine, _sim_task

    simulator = GridSimulator()
    fault_handler = FaultHandler(simulator)
    ontology_store = OntologyStore()
    alert_manager = AlertManager()

    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    reasoning_engine = ReasoningEngine(api_key, demo_mode=(not api_key or api_key == "your-api-key-here"))

    _sim_task = asyncio.create_task(simulation_loop())
    logger.info("Simulation loop started")

    yield

    if _sim_task:
        _sim_task.cancel()
        try:
            await _sim_task
        except asyncio.CancelledError:
            pass


app = FastAPI(title="Grid Twin API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


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


@app.post("/fault")
async def inject_fault(req: FaultRequest):
    msg = fault_handler.apply(req)
    return {"status": "ok", "message": msg}


@app.post("/restore")
async def restore():
    simulator.restore()
    alert_manager._alerts.clear()
    alert_manager._last_fired.clear()
    return {"status": "ok", "message": "System restored to nominal conditions"}


@app.get("/ontology")
async def get_ontology():
    return ontology_store.get_ontology()


@app.get("/ontology/propagation")
async def get_propagation(alert_id: str = Query(...)):
    return ontology_store.get_propagation(alert_id, alert_manager.alerts)


@app.get("/alerts")
async def get_alerts(limit: int = Query(50, ge=1, le=200)):
    alerts = alert_manager.alerts
    return alerts[-limit:]


class ReasoningRequest(BaseModel):
    query: str = ""


@app.post("/reasoning")
async def trigger_reasoning(req: ReasoningRequest = None):
    state = simulator.get_state()
    alerts = alert_manager.alerts
    propagation = None
    if alerts:
        propagation = ontology_store.get_propagation(alerts[-1].id, alerts)
    result = reasoning_engine.analyze(state, propagation, "MANUAL")
    return result


@app.post("/demo")
async def run_demo():
    asyncio.create_task(run_demo_scenario())
    return {"status": "ok", "message": "Demo scenario started"}


@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "sim_time_s": simulator.sim_time if simulator else 0,
        "uptime_s": simulator.sim_time if simulator else 0,
    }

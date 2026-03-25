"""
In-Memory Ontology Store & Alert Manager
=========================================
Maintains the Palantir Foundry-style ontology graph for the IEEE 9-bus digital
twin.  Every physics tick, ``OntologyStore.update_from_physics_state`` syncs
simulator telemetry into typed ``GridAsset`` nodes while propagating status
through the containment hierarchy.

``AlertManager`` evaluates post-power-flow conditions and emits deduplicated
``GridAlert`` objects for the operator console.
"""

from __future__ import annotations

import math
import uuid
from collections import deque
from datetime import datetime, timezone
from typing import TYPE_CHECKING

import networkx as nx

from physics.ieee9bus import BUSES, GENERATORS, LINES
from .model import (
    GridAlert,
    GridAsset,
    OntologyEdge,
    OntologyLink,
    OntologyResponse,
    PropagationResponse,
)

if TYPE_CHECKING:
    from physics.simulator import GridState

# ---------------------------------------------------------------------------
# Topology constants
# ---------------------------------------------------------------------------

_SUBSTATION_BUS_MAP: dict[str, list[int]] = {
    "A": [1, 4, 9],
    "B": [2, 7, 8],
    "C": [3, 5, 6],
}

_BUS_TO_SUBSTATION: dict[int, str] = {
    bus_id: sub_key
    for sub_key, bus_ids in _SUBSTATION_BUS_MAP.items()
    for bus_id in bus_ids
}

_GEN_BUS_IDS: set[int] = {g.bus_id for g in GENERATORS}

_LOAD_BUS_IDS: list[int] = [b.id for b in BUSES if b.id not in _GEN_BUS_IDS]

_STATUS_SEVERITY: dict[str, int] = {
    "NOMINAL": 0,
    "DEGRADED": 1,
    "OVERLOADED": 2,
    "TRIPPED": 3,
    "CRITICAL": 4,
}


def _worst_status(*statuses: str) -> str:
    return max(statuses, key=lambda s: _STATUS_SEVERITY.get(s, 0))


def _rid_grid() -> str:
    return "ri.grid-asset.main.grid-system.ieee9"


def _rid_sub(key: str) -> str:
    return f"ri.grid-asset.main.substation.{key}"


def _rid_gen(bus_id: int) -> str:
    return f"ri.grid-asset.main.generator.{bus_id}"


def _rid_line(from_bus: int, to_bus: int) -> str:
    return f"ri.grid-asset.main.transmission-line.{from_bus}-{to_bus}"


def _rid_load(bus_id: int) -> str:
    return f"ri.grid-asset.main.load-bus.{bus_id}"


# ---------------------------------------------------------------------------
# OntologyStore
# ---------------------------------------------------------------------------

class OntologyStore:
    """Full ontology graph for the IEEE 9-bus test system."""

    def __init__(self) -> None:
        self._assets: dict[str, GridAsset] = {}
        self._graph: nx.Graph = nx.Graph()
        self._build_initial_ontology()

    # ------------------------------------------------------------------
    # Initial graph construction
    # ------------------------------------------------------------------

    def _build_initial_ontology(self) -> None:
        now = datetime.now(timezone.utc)

        grid_rid = _rid_grid()
        sub_links: list[OntologyLink] = [
            OntologyLink(target_rid=_rid_sub(k), link_type="hasSubstation")
            for k in _SUBSTATION_BUS_MAP
        ]
        self._put(GridAsset(
            rid=grid_rid,
            object_type="GridSystem",
            display_name="IEEE 9-Bus Grid System",
            properties={"standard": "IEEE", "bus_count": 9},
            links=sub_links,
            status="NOMINAL",
            last_updated=now,
        ))

        for sub_key, bus_ids in _SUBSTATION_BUS_MAP.items():
            sub_rid = _rid_sub(sub_key)
            links: list[OntologyLink] = []
            for bid in bus_ids:
                if bid in _GEN_BUS_IDS:
                    links.append(OntologyLink(
                        target_rid=_rid_gen(bid), link_type="hostsGenerator",
                    ))
                else:
                    links.append(OntologyLink(
                        target_rid=_rid_load(bid), link_type="hostsLoad",
                    ))
            self._put(GridAsset(
                rid=sub_rid,
                object_type="Substation",
                display_name=f"Substation {sub_key}",
                properties={"bus_ids": bus_ids},
                links=links,
                status="NOMINAL",
                last_updated=now,
            ))

        for gen in GENERATORS:
            self._put(GridAsset(
                rid=_rid_gen(gen.bus_id),
                object_type="Generator",
                display_name=f"Generator {gen.bus_id} (Bus {gen.bus_id})",
                properties={
                    "bus_id": gen.bus_id,
                    "p_max_mw": gen.p_max_mw,
                    "inertia_M": gen.inertia_M,
                    "damping_D": gen.damping_D,
                    "rotor_angle_deg": 0.0,
                    "rotor_speed_rad_s": 0.0,
                    "mechanical_power_mw": gen.p_mech_mw,
                    "electrical_power_mw": 0.0,
                    "online": True,
                },
                links=[],
                status="NOMINAL",
                last_updated=now,
            ))

        for bus in BUSES:
            if bus.id in _GEN_BUS_IDS:
                continue
            self._put(GridAsset(
                rid=_rid_load(bus.id),
                object_type="LoadBus",
                display_name=f"{'Load' if bus.bus_type == 'load' else 'Junction'} Bus {bus.id}",
                properties={
                    "bus_id": bus.id,
                    "bus_type": bus.bus_type,
                    "voltage_angle_deg": 0.0,
                    "power_load_mw": bus.p_load_mw,
                    "power_generation_mw": 0.0,
                },
                links=[],
                status="NOMINAL",
                last_updated=now,
            ))

        for line in LINES:
            from_sub = _BUS_TO_SUBSTATION[line.from_bus]
            to_sub = _BUS_TO_SUBSTATION[line.to_bus]
            self._put(GridAsset(
                rid=_rid_line(line.from_bus, line.to_bus),
                object_type="TransmissionLine",
                display_name=f"Line {line.from_bus}-{line.to_bus}",
                properties={
                    "from_bus": line.from_bus,
                    "to_bus": line.to_bus,
                    "x_pu": line.x_pu,
                    "r_pu": line.r_pu,
                    "limit_mw": line.limit_mw,
                    "flow_mw": 0.0,
                    "flow_pct_of_limit": 0.0,
                    "tripped": False,
                },
                links=[
                    OntologyLink(
                        target_rid=_rid_sub(from_sub), link_type="connectsFrom",
                    ),
                    OntologyLink(
                        target_rid=_rid_sub(to_sub), link_type="connectsTo",
                    ),
                ],
                status="NOMINAL",
                last_updated=now,
            ))

        self._rebuild_nx_graph()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _put(self, asset: GridAsset) -> None:
        self._assets[asset.rid] = asset

    def _rebuild_nx_graph(self) -> None:
        """Build an undirected NetworkX graph from all ontology links."""
        g = nx.Graph()
        for asset in self._assets.values():
            g.add_node(asset.rid)
            for link in asset.links:
                g.add_edge(asset.rid, link.target_rid, link_type=link.link_type)
        self._graph = g

    # ------------------------------------------------------------------
    # Physics sync
    # ------------------------------------------------------------------

    def update_from_physics_state(self, state: GridState) -> None:
        """Sync all asset properties and statuses from the latest physics tick."""
        now = datetime.now(timezone.utc)

        gen_statuses: dict[int, str] = {}
        for gs in state.generators:
            rid = _rid_gen(gs.bus_id)
            asset = self._assets.get(rid)
            if asset is None:
                continue

            if not gs.online:
                status = "TRIPPED"
            elif abs(gs.rotor_angle_deg) > 60.0:
                status = "CRITICAL"
            elif abs(gs.rotor_angle_deg) > 45.0:
                status = "DEGRADED"
            else:
                status = "NOMINAL"

            gen_statuses[gs.bus_id] = status
            self._put(asset.model_copy(update={
                "properties": {
                    **asset.properties,
                    "rotor_angle_deg": gs.rotor_angle_deg,
                    "rotor_speed_rad_s": gs.rotor_speed_rad_s,
                    "mechanical_power_mw": gs.mechanical_power_mw,
                    "electrical_power_mw": gs.electrical_power_mw,
                    "online": gs.online,
                },
                "status": status,
                "last_updated": now,
            }))

        for bs in state.buses:
            rid = _rid_load(bs.id)
            asset = self._assets.get(rid)
            if asset is None:
                continue
            self._put(asset.model_copy(update={
                "properties": {
                    **asset.properties,
                    "voltage_angle_deg": bs.voltage_angle_deg,
                    "power_load_mw": bs.power_load_mw,
                    "power_generation_mw": bs.power_generation_mw,
                },
                "last_updated": now,
            }))

        line_statuses: dict[str, str] = {}
        for ls in state.lines:
            from_bus, to_bus = (int(x) for x in ls.id.split("-"))
            rid = _rid_line(from_bus, to_bus)
            asset = self._assets.get(rid)
            if asset is None:
                continue

            if ls.tripped:
                status = "TRIPPED"
            elif ls.flow_pct_of_limit > 0.80:
                status = "OVERLOADED"
            else:
                status = "NOMINAL"

            line_statuses[ls.id] = status
            self._put(asset.model_copy(update={
                "properties": {
                    **asset.properties,
                    "flow_mw": ls.flow_mw,
                    "flow_pct_of_limit": ls.flow_pct_of_limit,
                    "tripped": ls.tripped,
                },
                "status": status,
                "last_updated": now,
            }))

        for sub_key, bus_ids in _SUBSTATION_BUS_MAP.items():
            child_statuses: list[str] = []
            for bid in bus_ids:
                if bid in _GEN_BUS_IDS:
                    child_statuses.append(gen_statuses.get(bid, "NOMINAL"))
                else:
                    load_asset = self._assets.get(_rid_load(bid))
                    child_statuses.append(
                        load_asset.status if load_asset else "NOMINAL"
                    )
            for ls in state.lines:
                from_bus, to_bus = (int(x) for x in ls.id.split("-"))
                if from_bus in bus_ids or to_bus in bus_ids:
                    child_statuses.append(line_statuses.get(ls.id, "NOMINAL"))

            sub_rid = _rid_sub(sub_key)
            sub_asset = self._assets[sub_rid]
            self._put(sub_asset.model_copy(update={
                "status": _worst_status(*child_statuses) if child_statuses else "NOMINAL",
                "last_updated": now,
            }))

        sub_statuses = [
            self._assets[_rid_sub(k)].status for k in _SUBSTATION_BUS_MAP
        ]
        grid_asset = self._assets[_rid_grid()]
        self._put(grid_asset.model_copy(update={
            "status": _worst_status(*sub_statuses) if sub_statuses else "NOMINAL",
            "last_updated": now,
        }))

    # ------------------------------------------------------------------
    # Query interface
    # ------------------------------------------------------------------

    def get_asset(self, rid: str) -> GridAsset | None:
        return self._assets.get(rid)

    def get_ontology(self) -> OntologyResponse:
        """Return the complete ontology graph as nodes + edges."""
        edges: list[OntologyEdge] = []
        for asset in self._assets.values():
            for link in asset.links:
                edges.append(OntologyEdge(
                    source_rid=asset.rid,
                    target_rid=link.target_rid,
                    link_type=link.link_type,
                ))
        return OntologyResponse(
            nodes=list(self._assets.values()),
            edges=edges,
        )

    def get_propagation(
        self,
        alert_id: str,
        alerts: list[GridAlert],
    ) -> PropagationResponse:
        """BFS 2-hop propagation from the assets affected by *alert_id*."""
        alert = next((a for a in alerts if a.id == alert_id), None)
        if alert is None:
            return PropagationResponse(
                affected_nodes=[], affected_edges=[], propagation_order=[],
            )

        seed_rids: set[str] = set(alert.affected_asset_rids)

        visited: list[str] = []
        visited_set: set[str] = set()
        frontier: list[tuple[str, int]] = [(rid, 0) for rid in seed_rids if rid in self._graph]

        while frontier:
            current_rid, depth = frontier.pop(0)
            if current_rid in visited_set:
                continue
            visited_set.add(current_rid)
            visited.append(current_rid)
            if depth < 2:
                for neighbor in self._graph.neighbors(current_rid):
                    if neighbor not in visited_set:
                        frontier.append((neighbor, depth + 1))

        affected_edges: list[OntologyEdge] = []
        for asset_rid in visited:
            asset = self._assets.get(asset_rid)
            if asset is None:
                continue
            for link in asset.links:
                if link.target_rid in visited_set:
                    affected_edges.append(OntologyEdge(
                        source_rid=asset_rid,
                        target_rid=link.target_rid,
                        link_type=link.link_type,
                    ))

        return PropagationResponse(
            affected_nodes=visited,
            affected_edges=affected_edges,
            propagation_order=visited,
        )


# ---------------------------------------------------------------------------
# AlertManager
# ---------------------------------------------------------------------------

_OVERLOAD_THRESHOLD = 0.80
_ANGLE_INSTABILITY_DEG = 60.0
_FREQ_DEVIATION_HZ = 0.5
_FREQ_CRITICAL_HZ = 1.0
_DEDUP_WINDOW_S = 2.0
_MAX_ALERTS = 50


class AlertManager:
    """Evaluates post-power-flow conditions and emits deduplicated GridAlerts."""

    def __init__(self) -> None:
        self._alerts: deque[GridAlert] = deque(maxlen=_MAX_ALERTS)
        self._last_fired: dict[str, float] = {}

    @property
    def alerts(self) -> list[GridAlert]:
        return list(self._alerts)

    def evaluate(self, state: GridState) -> list[GridAlert]:
        """Check all alert conditions against the current grid state.

        Returns the list of *newly generated* alerts for this tick.
        """
        new_alerts: list[GridAlert] = []
        now = datetime.now(timezone.utc)
        sim_t = state.sim_time_s

        overloaded_lines: list[str] = []
        for ls in state.lines:
            from_bus, to_bus = (int(x) for x in ls.id.split("-"))
            line_rid = _rid_line(from_bus, to_bus)

            if ls.tripped:
                alert = self._maybe_emit(
                    alert_type="LINE_TRIPPED",
                    severity="INFO",
                    rids=[line_rid],
                    sim_t=sim_t,
                    wall_t=now,
                    sensor_values={"flow_mw": ls.flow_mw},
                )
                if alert:
                    new_alerts.append(alert)

            if ls.flow_pct_of_limit > _OVERLOAD_THRESHOLD and not ls.tripped:
                overloaded_lines.append(line_rid)
                alert = self._maybe_emit(
                    alert_type="LINE_OVERLOAD",
                    severity="WARNING",
                    rids=[line_rid],
                    sim_t=sim_t,
                    wall_t=now,
                    sensor_values={
                        "flow_mw": ls.flow_mw,
                        "flow_pct": ls.flow_pct_of_limit,
                    },
                )
                if alert:
                    new_alerts.append(alert)

        if len(overloaded_lines) >= 2:
            alert = self._maybe_emit(
                alert_type="CASCADE_IMMINENT",
                severity="CRITICAL",
                rids=overloaded_lines,
                sim_t=sim_t,
                wall_t=now,
                sensor_values={"overloaded_count": float(len(overloaded_lines))},
            )
            if alert:
                new_alerts.append(alert)

        ref_angle = 0.0
        for gs in state.generators:
            if gs.bus_id == 1:
                ref_angle = gs.rotor_angle_deg
                break

        for gs in state.generators:
            if abs(gs.rotor_angle_deg - ref_angle) > _ANGLE_INSTABILITY_DEG:
                gen_rid = _rid_gen(gs.bus_id)
                alert = self._maybe_emit(
                    alert_type="ANGLE_INSTABILITY",
                    severity="CRITICAL",
                    rids=[gen_rid],
                    sim_t=sim_t,
                    wall_t=now,
                    sensor_values={
                        "rotor_angle_deg": gs.rotor_angle_deg,
                        "delta_from_ref_deg": gs.rotor_angle_deg - ref_angle,
                    },
                )
                if alert:
                    new_alerts.append(alert)

        freq_dev = abs(state.system_frequency_hz - 60.0)
        if freq_dev > _FREQ_CRITICAL_HZ:
            alert = self._maybe_emit(
                alert_type="FREQ_CRITICAL",
                severity="CRITICAL",
                rids=[_rid_grid()],
                sim_t=sim_t,
                wall_t=now,
                sensor_values={"system_frequency_hz": state.system_frequency_hz},
            )
            if alert:
                new_alerts.append(alert)
        elif freq_dev > _FREQ_DEVIATION_HZ:
            alert = self._maybe_emit(
                alert_type="FREQ_DEVIATION",
                severity="WARNING",
                rids=[_rid_grid()],
                sim_t=sim_t,
                wall_t=now,
                sensor_values={"system_frequency_hz": state.system_frequency_hz},
            )
            if alert:
                new_alerts.append(alert)

        return new_alerts

    # ------------------------------------------------------------------
    # Deduplication
    # ------------------------------------------------------------------

    def _dedup_key(self, alert_type: str, rids: list[str]) -> str:
        return f"{alert_type}::{','.join(sorted(rids))}"

    def _maybe_emit(
        self,
        *,
        alert_type: str,
        severity: str,
        rids: list[str],
        sim_t: float,
        wall_t: datetime,
        sensor_values: dict[str, float],
    ) -> GridAlert | None:
        key = self._dedup_key(alert_type, rids)
        last_t = self._last_fired.get(key)
        if last_t is not None and (sim_t - last_t) < _DEDUP_WINDOW_S:
            return None

        alert = GridAlert(
            id=str(uuid.uuid4()),
            type=alert_type,
            severity=severity,  # type: ignore[arg-type]
            affected_asset_rids=rids,
            timestamp_sim=sim_t,
            timestamp_wall=wall_t,
            sensor_values=sensor_values,
        )
        self._alerts.append(alert)
        self._last_fired[key] = sim_t
        return alert

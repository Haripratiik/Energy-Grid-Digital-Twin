"""
In-Memory Ontology Store & Alert Manager
=========================================
Maintains the object-graph ontology for the city-scale 80-bus,
3-voltage-tier digital twin.  Every physics tick,
``OntologyStore.update_from_physics_state`` syncs simulator telemetry into typed
``GridAsset`` nodes while propagating status through the containment hierarchy:

    GridSystem ─► Region ─► Substation ─► Generator / LoadBus
                                 ▲
                  TransmissionLine / Transformer

``AlertManager`` evaluates post-power-flow conditions and emits deduplicated
``GridAlert`` objects for the operator console.
"""

from __future__ import annotations

import uuid
from collections import deque
from datetime import datetime, timezone
from typing import TYPE_CHECKING

import networkx as nx

from physics.network import (
    BUSES,
    GENERATORS_CONFIG,
    LINES,
    NOMINAL_FREQ_HZ,
    SLACK_BUS,
    TRANSFORMERS,
)
from .model import (
    GridAlert,
    GridAsset,
    OntologyEdge,
    OntologyLink,
    OntologyResponse,
    PropagationResponse,
)

if TYPE_CHECKING:
    from physics.swing import GridState

# ---------------------------------------------------------------------------
# Topology constants
# ---------------------------------------------------------------------------

_REGION_TIERS: dict[str, float] = {
    "hv": 400.0,
    "mv": 132.0,
    "lv": 33.0,
}

_GEN_BUS_IDS: set[int] = {g["bus_id"] for g in GENERATORS_CONFIG}
_GEN_CONFIG_BY_BUS: dict[int, dict] = {g["bus_id"]: g for g in GENERATORS_CONFIG}
_BUS_BY_ID = {b.id: b for b in BUSES}

_STATUS_SEVERITY: dict[str, int] = {
    "NOMINAL": 0,
    "DEGRADED": 1,
    "OVERLOADED": 2,
    "TRIPPED": 3,
    "CRITICAL": 4,
}


def _worst_status(*statuses: str) -> str:
    return max(statuses, key=lambda s: _STATUS_SEVERITY.get(s, 0))


# ---------------------------------------------------------------------------
# RID helpers
# ---------------------------------------------------------------------------

def _rid_grid() -> str:
    return "ri.city-grid.main.grid-system.city"


def _rid_region(tier: str) -> str:
    return f"ri.city-grid.main.region.{tier}"


def _rid_substation(bus_id: int) -> str:
    return f"ri.city-grid.main.substation.{bus_id}"


def _rid_generator(bus_id: int) -> str:
    return f"ri.city-grid.main.generator.{bus_id}"


def _rid_line(index: int) -> str:
    return f"ri.city-grid.main.transmission-line.{index}"


def _rid_transformer(index: int) -> str:
    return f"ri.city-grid.main.transformer.{index}"


def _rid_load(bus_id: int) -> str:
    return f"ri.city-grid.main.load-bus.{bus_id}"


# ---------------------------------------------------------------------------
# OntologyStore
# ---------------------------------------------------------------------------

class OntologyStore:
    """Full ontology graph for the city-scale 80-bus power network."""

    def __init__(self) -> None:
        self._assets: dict[str, GridAsset] = {}
        self._graph: nx.Graph = nx.Graph()
        self._build_initial_ontology()

    # ------------------------------------------------------------------
    # Initial graph construction
    # ------------------------------------------------------------------

    def _build_initial_ontology(self) -> None:
        now = datetime.now(timezone.utc)

        hv_buses = [b for b in BUSES if b.voltage_kv == 400.0]
        mv_buses = [b for b in BUSES if b.voltage_kv == 132.0]
        lv_buses = [b for b in BUSES if b.voltage_kv == 33.0]
        tier_buses: dict[str, list] = {"hv": hv_buses, "mv": mv_buses, "lv": lv_buses}

        # ── GridSystem ────────────────────────────────────────────────
        self._put(GridAsset(
            rid=_rid_grid(),
            object_type="GridSystem",
            display_name="City-Scale Grid System",
            properties={
                "bus_count": len(BUSES),
                "voltage_tiers_kv": [400, 132, 33],
                "total_gen_capacity_mw": sum(g["capacity_mw"] for g in GENERATORS_CONFIG),
                "total_load_mw": sum(b.p_load_mw for b in BUSES),
            },
            links=[
                OntologyLink(target_rid=_rid_region(t), link_type="hasRegion")
                for t in tier_buses
            ],
            status="NOMINAL",
            last_updated=now,
        ))

        # ── Regions ───────────────────────────────────────────────────
        _tier_label = {"hv": "400 kV HV", "mv": "132 kV MV", "lv": "33 kV LV"}
        for tier, buses in tier_buses.items():
            self._put(GridAsset(
                rid=_rid_region(tier),
                object_type="Region",
                display_name=f"{_tier_label[tier]} Region",
                properties={
                    "voltage_kv": _REGION_TIERS[tier],
                    "bus_count": len(buses),
                },
                links=[
                    OntologyLink(
                        target_rid=_rid_substation(b.id), link_type="hasSubstation",
                    )
                    for b in buses
                ],
                status="NOMINAL",
                last_updated=now,
            ))

        # ── Substations (one per bus) ─────────────────────────────────
        for bus in BUSES:
            links: list[OntologyLink] = []
            if bus.id in _GEN_BUS_IDS:
                links.append(OntologyLink(
                    target_rid=_rid_generator(bus.id), link_type="hostsGenerator",
                ))
            if bus.id not in _GEN_BUS_IDS:
                links.append(OntologyLink(
                    target_rid=_rid_load(bus.id), link_type="hostsLoad",
                ))
            self._put(GridAsset(
                rid=_rid_substation(bus.id),
                object_type="Substation",
                display_name=f"Substation {bus.id} – {bus.name}",
                properties={
                    "bus_id": bus.id,
                    "voltage_kv": bus.voltage_kv,
                    "bus_name": bus.name,
                },
                links=links,
                status="NOMINAL",
                last_updated=now,
            ))

        # ── Generators ────────────────────────────────────────────────
        for cfg in GENERATORS_CONFIG:
            bus_id = cfg["bus_id"]
            bus = _BUS_BY_ID[bus_id]
            self._put(GridAsset(
                rid=_rid_generator(bus_id),
                object_type="Generator",
                display_name=f"{cfg['gen_type'].title()} Gen @ Bus {bus_id} ({bus.name})",
                properties={
                    "bus_id": bus_id,
                    "gen_type": cfg["gen_type"],
                    "capacity_mw": cfg["capacity_mw"],
                    "p_mech_mw": cfg["p_mech_mw"],
                    "output_mw": 0.0,
                    "online": True,
                    "rotor_angle_deg": 0.0,
                },
                links=[],
                status="NOMINAL",
                last_updated=now,
            ))

        # ── Transmission lines ────────────────────────────────────────
        for i, line in enumerate(LINES):
            self._put(GridAsset(
                rid=_rid_line(i),
                object_type="TransmissionLine",
                display_name=(
                    f"Line {line.from_bus}\u2192{line.to_bus}"
                    f" ({line.voltage_kv:.0f} kV)"
                ),
                properties={
                    "index": i,
                    "from_bus": line.from_bus,
                    "to_bus": line.to_bus,
                    "voltage_kv": line.voltage_kv,
                    "limit_mw": line.limit_mw,
                    "flow_mw": 0.0,
                    "loading_pct": 0.0,
                    "tripped": False,
                },
                links=[
                    OntologyLink(
                        target_rid=_rid_substation(line.from_bus),
                        link_type="connectsFrom",
                    ),
                    OntologyLink(
                        target_rid=_rid_substation(line.to_bus),
                        link_type="connectsTo",
                    ),
                ],
                status="NOMINAL",
                last_updated=now,
            ))

        # ── Transformers ──────────────────────────────────────────────
        for i, xf in enumerate(TRANSFORMERS):
            self._put(GridAsset(
                rid=_rid_transformer(i),
                object_type="Transformer",
                display_name=(
                    f"Xfmr {xf.from_bus}\u2192{xf.to_bus}"
                    f" ({xf.from_kv:.0f}/{xf.to_kv:.0f} kV)"
                ),
                properties={
                    "index": i,
                    "from_bus": xf.from_bus,
                    "to_bus": xf.to_bus,
                    "from_kv": xf.from_kv,
                    "to_kv": xf.to_kv,
                    "rating_mva": xf.rating_mva,
                    "loading_pct": 0.0,
                },
                links=[
                    OntologyLink(
                        target_rid=_rid_substation(xf.from_bus),
                        link_type="connectsHV",
                    ),
                    OntologyLink(
                        target_rid=_rid_substation(xf.to_bus),
                        link_type="connectsLV",
                    ),
                ],
                status="NOMINAL",
                last_updated=now,
            ))

        # ── Load buses (all non-generator buses) ──────────────────────
        for bus in BUSES:
            if bus.id in _GEN_BUS_IDS:
                continue
            self._put(GridAsset(
                rid=_rid_load(bus.id),
                object_type="LoadBus",
                display_name=f"Load Bus {bus.id} – {bus.name}",
                properties={
                    "bus_id": bus.id,
                    "bus_type": bus.bus_type,
                    "p_load_mw": bus.p_load_mw,
                    "voltage_pu": 1.0,
                },
                links=[],
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

        # ── Generators ────────────────────────────────────────────────
        gen_statuses: dict[int, str] = {}
        for gs in state.generators:
            rid = _rid_generator(gs.bus_id)
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
                    "gen_type": gs.gen_type,
                    "output_mw": gs.electrical_power_mw,
                    "online": gs.online,
                    "rotor_angle_deg": gs.rotor_angle_deg,
                },
                "status": status,
                "last_updated": now,
            }))

        # ── Lines ─────────────────────────────────────────────────────
        line_statuses: dict[str, str] = {}
        for ls in state.lines:
            rid = ls.id
            asset = self._assets.get(rid)
            if asset is None:
                continue

            if ls.tripped:
                status = "TRIPPED"
            elif ls.flow_pct_of_limit > 0.80:
                status = "OVERLOADED"
            else:
                status = "NOMINAL"

            line_statuses[rid] = status
            self._put(asset.model_copy(update={
                "properties": {
                    **asset.properties,
                    "flow_mw": ls.flow_mw,
                    "loading_pct": round(ls.flow_pct_of_limit * 100.0, 2),
                    "tripped": ls.tripped,
                },
                "status": status,
                "last_updated": now,
            }))

        # ── Transformers ──────────────────────────────────────────────
        trafo_statuses: dict[str, str] = {}
        for ts in state.transformers:
            rid = ts.id
            asset = self._assets.get(rid)
            if asset is None:
                continue

            if ts.status == "tripped":
                status = "TRIPPED"
            elif ts.loading_pct > 90.0:
                status = "OVERLOADED"
            else:
                status = "NOMINAL"

            trafo_statuses[rid] = status
            self._put(asset.model_copy(update={
                "properties": {
                    **asset.properties,
                    "loading_pct": ts.loading_pct,
                },
                "status": status,
                "last_updated": now,
            }))

        # ── Load buses ────────────────────────────────────────────────
        for bs in state.buses:
            rid = _rid_load(bs.id)
            asset = self._assets.get(rid)
            if asset is None:
                continue
            self._put(asset.model_copy(update={
                "properties": {
                    **asset.properties,
                    "p_load_mw": bs.power_load_mw,
                    "voltage_pu": bs.voltage_magnitude_pu,
                },
                "last_updated": now,
            }))

        # ── Status propagation: Substations ───────────────────────────
        sub_statuses: dict[int, str] = {}
        for bus in BUSES:
            children: list[str] = []

            if bus.id in _GEN_BUS_IDS:
                children.append(gen_statuses.get(bus.id, "NOMINAL"))

            load_asset = self._assets.get(_rid_load(bus.id))
            if load_asset is not None:
                children.append(load_asset.status)

            for i in range(len(LINES)):
                ln = LINES[i]
                if ln.from_bus == bus.id or ln.to_bus == bus.id:
                    children.append(line_statuses.get(_rid_line(i), "NOMINAL"))

            for i in range(len(TRANSFORMERS)):
                xf = TRANSFORMERS[i]
                if xf.from_bus == bus.id or xf.to_bus == bus.id:
                    children.append(trafo_statuses.get(_rid_transformer(i), "NOMINAL"))

            sub_status = _worst_status(*children) if children else "NOMINAL"
            sub_statuses[bus.id] = sub_status

            sub_rid = _rid_substation(bus.id)
            sub_asset = self._assets[sub_rid]
            self._put(sub_asset.model_copy(update={
                "status": sub_status,
                "last_updated": now,
            }))

        # ── Status propagation: Regions ───────────────────────────────
        region_statuses: dict[str, str] = {}
        for tier, kv in _REGION_TIERS.items():
            tier_subs = [sub_statuses[b.id] for b in BUSES if b.voltage_kv == kv]
            region_status = _worst_status(*tier_subs) if tier_subs else "NOMINAL"
            region_statuses[tier] = region_status

            region_asset = self._assets[_rid_region(tier)]
            self._put(region_asset.model_copy(update={
                "status": region_status,
                "last_updated": now,
            }))

        # ── Status propagation: GridSystem ────────────────────────────
        all_region = list(region_statuses.values())
        grid_status = _worst_status(*all_region) if all_region else "NOMINAL"
        grid_asset = self._assets[_rid_grid()]
        self._put(grid_asset.model_copy(update={
            "status": grid_status,
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
        frontier: list[tuple[str, int]] = [
            (rid, 0) for rid in seed_rids if rid in self._graph
        ]

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

_LINE_OVERLOAD_THRESHOLD = 0.80     # fraction of thermal limit
_TRAFO_OVERLOAD_PCT = 90.0          # percentage of MVA rating
_ANGLE_INSTABILITY_DEG = 60.0
_FREQ_DEVIATION_HZ = 0.5
_FREQ_CRITICAL_HZ = 1.0
_VOLTAGE_LOW_PU = 0.95
_VOLTAGE_CRITICAL_PU = 0.90
_DEDUP_WINDOW_S = 2.0
_MAX_ALERTS = 100


def _rid_short(rid: str) -> str:
    """Convert 'ri.city-grid.main.transmission-line.12' to 'Line 12'."""
    parts = rid.rsplit(".", 2)
    kind = parts[-2] if len(parts) >= 2 else ""
    ident = parts[-1] if parts else rid
    labels = {
        "transmission-line": "Line",
        "generator": "Gen",
        "load-bus": "Bus",
        "substation": "Sub",
        "transformer": "Trafo",
        "grid-system": "Grid",
    }
    return f"{labels.get(kind, kind)} {ident}"


def _alert_summary(alert_type: str, sv: dict[str, float], rids: list[str]) -> str:
    """Build a one-line operator-readable summary for the given alert type."""
    first = _rid_short(rids[0]) if rids else "Unknown"

    if alert_type == "LINE_OVERLOAD":
        return f"{first} at {sv.get('loading_pct', 0):.0f}% thermal limit ({sv.get('flow_mw', 0):.0f} MW)"
    if alert_type == "LINE_TRIPPED":
        return f"{first} has tripped — removed from service"
    if alert_type == "CASCADE_IMMINENT":
        n = int(sv.get("overloaded_count", 0))
        return f"Cascade risk: {n} lines overloaded simultaneously"
    if alert_type == "TRAFO_OVERLOAD":
        return f"{first} at {sv.get('loading_pct', 0):.0f}% loading — approaching thermal limit"
    if alert_type == "GEN_OFFLINE":
        bus = int(sv.get("bus_id", 0))
        return f"Generator on Bus {bus} went offline"
    if alert_type == "ANGLE_INSTABILITY":
        delta = sv.get("delta_from_ref_deg", 0)
        return f"{first} rotor angle {delta:+.1f}° from reference — stability at risk"
    if alert_type == "FREQ_CRITICAL":
        hz = sv.get("system_frequency_hz", 60.0)
        return f"Frequency critical at {hz:.3f} Hz ({hz - 60.0:+.3f} Hz deviation)"
    if alert_type == "FREQ_DEVIATION":
        hz = sv.get("system_frequency_hz", 60.0)
        return f"Frequency drifting: {hz:.3f} Hz ({hz - 60.0:+.3f} Hz deviation)"
    if alert_type == "VOLTAGE_CRITICAL":
        bus = int(sv.get("bus_id", 0))
        pu = sv.get("voltage_pu", 0)
        return f"Bus {bus} voltage critical at {pu:.3f} pu"
    if alert_type == "VOLTAGE_LOW":
        bus = int(sv.get("bus_id", 0))
        pu = sv.get("voltage_pu", 0)
        return f"Bus {bus} voltage low at {pu:.3f} pu"
    return f"{alert_type} on {first}"


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

        # ── Line alerts ───────────────────────────────────────────────
        overloaded_line_rids: list[str] = []
        for ls in state.lines:
            line_rid = ls.id

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

            if ls.flow_pct_of_limit > _LINE_OVERLOAD_THRESHOLD and not ls.tripped:
                overloaded_line_rids.append(line_rid)
                alert = self._maybe_emit(
                    alert_type="LINE_OVERLOAD",
                    severity="WARNING",
                    rids=[line_rid],
                    sim_t=sim_t,
                    wall_t=now,
                    sensor_values={
                        "flow_mw": ls.flow_mw,
                        "loading_pct": ls.flow_pct_of_limit * 100.0,
                    },
                )
                if alert:
                    new_alerts.append(alert)

        if len(overloaded_line_rids) >= 2:
            alert = self._maybe_emit(
                alert_type="CASCADE_IMMINENT",
                severity="CRITICAL",
                rids=overloaded_line_rids,
                sim_t=sim_t,
                wall_t=now,
                sensor_values={"overloaded_count": float(len(overloaded_line_rids))},
            )
            if alert:
                new_alerts.append(alert)

        # ── Transformer alerts ────────────────────────────────────────
        for ts in state.transformers:
            trafo_rid = ts.id
            if ts.loading_pct > _TRAFO_OVERLOAD_PCT:
                alert = self._maybe_emit(
                    alert_type="TRAFO_OVERLOAD",
                    severity="WARNING",
                    rids=[trafo_rid],
                    sim_t=sim_t,
                    wall_t=now,
                    sensor_values={"loading_pct": ts.loading_pct},
                )
                if alert:
                    new_alerts.append(alert)

        # ── Generator alerts ──────────────────────────────────────────
        ref_angle = 0.0
        for gs in state.generators:
            if gs.bus_id == SLACK_BUS:
                ref_angle = gs.rotor_angle_deg
                break

        for gs in state.generators:
            gen_rid = _rid_generator(gs.bus_id)

            if not gs.online:
                alert = self._maybe_emit(
                    alert_type="GEN_OFFLINE",
                    severity="WARNING",
                    rids=[gen_rid],
                    sim_t=sim_t,
                    wall_t=now,
                    sensor_values={"bus_id": float(gs.bus_id)},
                )
                if alert:
                    new_alerts.append(alert)

            delta = abs(gs.rotor_angle_deg - ref_angle)
            if delta > _ANGLE_INSTABILITY_DEG:
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

        # ── Frequency alerts ──────────────────────────────────────────
        freq_dev = abs(state.system_frequency_hz - NOMINAL_FREQ_HZ)
        grid_rid = _rid_grid()

        if freq_dev > _FREQ_CRITICAL_HZ:
            alert = self._maybe_emit(
                alert_type="FREQ_CRITICAL",
                severity="CRITICAL",
                rids=[grid_rid],
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
                rids=[grid_rid],
                sim_t=sim_t,
                wall_t=now,
                sensor_values={"system_frequency_hz": state.system_frequency_hz},
            )
            if alert:
                new_alerts.append(alert)

        # ── Voltage alerts ────────────────────────────────────────────
        for bs in state.buses:
            vm = bs.voltage_magnitude_pu
            sub_rid = _rid_substation(bs.id)

            if vm < _VOLTAGE_CRITICAL_PU:
                alert = self._maybe_emit(
                    alert_type="VOLTAGE_CRITICAL",
                    severity="CRITICAL",
                    rids=[sub_rid],
                    sim_t=sim_t,
                    wall_t=now,
                    sensor_values={"voltage_pu": vm, "bus_id": float(bs.id)},
                )
                if alert:
                    new_alerts.append(alert)
            elif vm < _VOLTAGE_LOW_PU:
                alert = self._maybe_emit(
                    alert_type="VOLTAGE_LOW",
                    severity="WARNING",
                    rids=[sub_rid],
                    sim_t=sim_t,
                    wall_t=now,
                    sensor_values={"voltage_pu": vm, "bus_id": float(bs.id)},
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
            summary=_alert_summary(alert_type, sensor_values, rids),
        )
        self._alerts.append(alert)
        self._last_fired[key] = sim_t
        return alert

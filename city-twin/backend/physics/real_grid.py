"""Real Georgia transmission grid, built from OpenStreetMap.

This replaces the hand-built 80-bus model's *topology* with the **actual**
Atlanta-area transmission network: real substations, real transmission lines,
and their real voltage classes (115 / 230 / 500 kV — Georgia Power's true
levels), as mapped in OpenStreetMap.

What is real vs. estimated (honest):
* **Real** — node locations (substations), line routes & connectivity, voltage
  classes, geography.
* **Estimated** — line impedances (from route length × standard per-km values
  for the voltage class), thermal ratings (typical values per class), and the
  load / generation allocation. These are *necessarily* modelled: the actual
  electrical parameters and real-time dispatch are CEII (Critical Energy
  Infrastructure Information) and not publicly available for any grid.

A linear (DC) power flow is solved on the real topology to produce per-line
flows and loadings — robust for a large connected network.
"""

from __future__ import annotations

import json
import math
import os
from collections import Counter

import numpy as np
from pydantic import BaseModel

_GEOJSON = os.path.join(
    os.path.dirname(__file__), "..", "..", "frontend", "public", "atlanta_grid_infra.geojson"
)

# Standard estimates by voltage class.
_X_OHM_PER_KM = 0.4                       # typical overhead line reactance
_THERMAL_MW = {500: 2600.0, 230: 700.0, 115: 200.0}
_BASE_MVA = 100.0
_TOTAL_LOAD_MW = 11000.0                  # ~Atlanta-metro peak order of magnitude


class RealBus(BaseModel):
    id: int
    lat: float
    lon: float
    voltage_kv: int
    is_source: bool
    load_mw: float


class RealLine(BaseModel):
    from_id: int
    to_id: int
    voltage_kv: int
    length_km: float
    flow_mw: float = 0.0
    loading_pct: float = 0.0


class RealGrid(BaseModel):
    buses: list[RealBus]
    lines: list[RealLine]
    n_buses: int
    n_lines: int
    source: str = "OpenStreetMap (real Georgia transmission topology)"


def _haversine_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    R = 6371.0
    lat1, lon1, lat2, lon2 = map(math.radians, [a[0], a[1], b[0], b[1]])
    dlat, dlon = lat2 - lat1, lon2 - lon1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * R * math.asin(math.sqrt(h))


def _hv(v) -> int:
    try:
        return max(int(x) for x in str(v).replace(" ", "").split(";") if x.isdigit())
    except ValueError:
        return 0


def build_real_grid() -> RealGrid:
    with open(os.path.abspath(_GEOJSON)) as fh:
        geo = json.load(fh)
    feats = geo.get("features", [])

    def _points(power: str) -> list[tuple[float, float]]:
        # OSM tags substations/plants as either Point or Polygon; we only snap to
        # Point geometries (matching the LineString guard used for lines below).
        return [(f["geometry"]["coordinates"][1], f["geometry"]["coordinates"][0])
                for f in feats
                if f.get("properties", {}).get("power") == power
                and f.get("geometry", {}).get("type") == "Point"]

    subs = _points("substation")
    plants = _points("plant")
    lines_raw = [f for f in feats if f.get("properties", {}).get("power") == "line"]

    # No usable substation data → return an empty grid rather than crashing.
    if not subs:
        return RealGrid(buses=[], lines=[], n_buses=0, n_lines=0)

    def nearest(lat: float, lon: float) -> tuple[int, float]:
        best, bd = -1, 9e9
        for i, (slat, slon) in enumerate(subs):
            d = (slat - lat) ** 2 + (slon - lon) ** 2
            if d < bd:
                bd, best = d, i
        return best, math.sqrt(bd)

    # Build transmission edges by snapping line endpoints to substations.
    parent = list(range(len(subs)))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    raw_edges: list[tuple[int, int, int, float]] = []
    THR = 0.05  # ~5 km
    for f in lines_raw:
        kv = _hv(f["properties"].get("voltage", ""))
        if kv < 115000 or f["geometry"]["type"] != "LineString":
            continue
        c = f["geometry"]["coordinates"]
        if len(c) < 2:
            continue
        a, da = nearest(c[0][1], c[0][0])
        b, db = nearest(c[-1][1], c[-1][0])
        if a == b or da > THR or db > THR:
            continue
        length = sum(_haversine_km((c[i][1], c[i][0]), (c[i + 1][1], c[i + 1][0]))
                     for i in range(len(c) - 1))
        raw_edges.append((a, b, kv // 1000, max(length, 0.5)))
        parent[find(a)] = find(b)

    # Largest connected component.
    comp = Counter(find(i) for i in range(len(subs)))
    root = comp.most_common(1)[0][0]
    keep = [i for i in range(len(subs)) if find(i) == root]
    reindex = {old: new for new, old in enumerate(keep)}
    n = len(keep)

    # Per-bus voltage = highest incident line voltage (default 115).
    bus_kv = [115] * n
    edges: list[tuple[int, int, int, float]] = []
    for a, b, kv, length in raw_edges:
        if find(a) != root:
            continue
        ai, bi = reindex[a], reindex[b]
        edges.append((ai, bi, kv, length))
        bus_kv[ai] = max(bus_kv[ai], kv)
        bus_kv[bi] = max(bus_kv[bi], kv)

    # Generation sources: substations nearest the real power plants, plus the
    # highest-voltage hubs (bulk-transmission import points).
    source = [False] * n
    for plat, plon in plants:
        bi, _ = nearest(plat, plon)
        if find(bi) == root:
            source[reindex[bi]] = True
    for i in range(n):
        if bus_kv[i] >= 500:
            source[i] = True

    # Loads: distribution-tier (115 kV) buses carry most demand.
    weight = [1.0 if bus_kv[i] < 230 else (0.4 if bus_kv[i] < 500 else 0.05) for i in range(n)]
    nonsrc_w = sum(weight[i] for i in range(n) if not source[i]) or 1.0
    load = [0.0] * n
    for i in range(n):
        if not source[i]:
            load[i] = _TOTAL_LOAD_MW * weight[i] / nonsrc_w

    # --- DC power flow on the real topology ---
    A = np.zeros((len(edges), n))
    b_branch = np.zeros(len(edges))
    for k, (ai, bi, kv, length) in enumerate(edges):
        A[k, ai], A[k, bi] = 1.0, -1.0
        z_base = (kv ** 2) / _BASE_MVA
        x_pu = max(1e-4, _X_OHM_PER_KM * length / z_base)
        b_branch[k] = 1.0 / x_pu

    # Injections (pu): sources share generation to balance load.
    P = -np.array(load) / _BASE_MVA
    total_load = sum(load)
    src_idx = [i for i in range(n) if source[i]]
    if src_idx:
        per = total_load / len(src_idx) / _BASE_MVA
        for i in src_idx:
            P[i] += per

    slack = max(range(n), key=lambda i: (bus_kv[i], sum(1 for e in edges if i in (e[0], e[1]))))
    keep_idx = [i for i in range(n) if i != slack]
    Bbus = A.T @ (b_branch[:, None] * A)
    theta = np.zeros(n)
    try:
        theta[keep_idx] = np.linalg.solve(Bbus[np.ix_(keep_idx, keep_idx)], P[keep_idx])
    except np.linalg.LinAlgError:
        theta = np.zeros(n)
    flow = b_branch * (A @ theta) * _BASE_MVA   # MW

    buses = [RealBus(id=i, lat=subs[keep[i]][0], lon=subs[keep[i]][1],
                     voltage_kv=bus_kv[i], is_source=source[i], load_mw=round(load[i], 1))
             for i in range(n)]
    lines = []
    for k, (ai, bi, kv, length) in enumerate(edges):
        limit = _THERMAL_MW.get(kv, 200.0)
        lines.append(RealLine(from_id=ai, to_id=bi, voltage_kv=kv,
                              length_km=round(length, 1), flow_mw=round(float(flow[k]), 1),
                              loading_pct=round(abs(float(flow[k])) / limit * 100.0, 1)))
    return RealGrid(buses=buses, lines=lines, n_buses=n, n_lines=len(lines))


def build_real_ontology() -> dict:
    """An ontology graph (same schema as the synthetic one) over the REAL Georgia
    transmission grid: real substations and source plants as objects, real lines
    as links, status from the DC-snapshot loadings. Real topology; the electrical
    parameters behind the status are estimated (CEII — not public)."""
    from datetime import datetime, timezone

    from ontology.model import GridAsset, OntologyEdge, OntologyLink, OntologyResponse

    grid = build_real_grid()
    now = datetime.now(timezone.utc)

    worst: dict[int, float] = {b.id: 0.0 for b in grid.buses}
    for ln in grid.lines:
        worst[ln.from_id] = max(worst[ln.from_id], ln.loading_pct)
        worst[ln.to_id] = max(worst[ln.to_id], ln.loading_pct)

    def status_for(pct: float) -> str:
        if pct > 100.0:
            return "OVERLOADED"
        if pct > 80.0:
            return "DEGRADED"
        return "NOMINAL"

    sys_rid = "ri.real-grid.georgia.system"
    src_rids = [f"ri.real-grid.georgia.substation.{b.id}" for b in grid.buses if b.is_source]
    nodes: list[GridAsset] = [
        GridAsset(
            rid=sys_rid, object_type="GridSystem",
            display_name="Georgia Transmission (OSM)",
            properties={
                "source": grid.source, "substations": grid.n_buses, "lines": grid.n_lines,
                "note": "real topology & geography · electrical params estimated (CEII)",
            },
            links=[OntologyLink(target_rid=r, link_type="hostsSource") for r in src_rids],
            status="NOMINAL", last_updated=now,
        )
    ]
    for b in grid.buses:
        rid = f"ri.real-grid.georgia.substation.{b.id}"
        nodes.append(GridAsset(
            rid=rid,
            object_type="Generator" if b.is_source else "Substation",
            display_name=(f"{b.voltage_kv}kV source {b.id}" if b.is_source
                          else f"{b.voltage_kv}kV sub {b.id}"),
            properties={
                "voltage_kv": b.voltage_kv, "lat": round(b.lat, 4), "lon": round(b.lon, 4),
                "is_source": b.is_source, "load_mw": b.load_mw,
                "max_line_loading_pct": round(worst[b.id], 1), "real_topology": True,
            },
            links=[], status=status_for(worst[b.id]), last_updated=now,
        ))

    edges = [
        OntologyEdge(
            source_rid=f"ri.real-grid.georgia.substation.{ln.from_id}",
            target_rid=f"ri.real-grid.georgia.substation.{ln.to_id}",
            link_type="connectsTo",
        )
        for ln in grid.lines
    ]
    return OntologyResponse(nodes=nodes, edges=edges).model_dump(mode="json")


if __name__ == "__main__":
    g = build_real_grid()
    loadings = [ln.loading_pct for ln in g.lines]
    print("Real Georgia transmission grid from OpenStreetMap:")
    print(f"  {g.n_buses} substations, {g.n_lines} transmission lines")
    kvc = Counter(ln.voltage_kv for ln in g.lines)
    print(f"  voltage classes (kV): {dict(sorted(kvc.items()))}")
    print(f"  sources: {sum(b.is_source for b in g.buses)}  total load: {sum(b.load_mw for b in g.buses):.0f} MW")
    print(f"  line loadings: min {min(loadings):.0f}% / mean {sum(loadings)/len(loadings):.0f}% / max {max(loadings):.0f}%")
    print(f"  overloaded (>100%): {sum(1 for x in loadings if x > 100)}")

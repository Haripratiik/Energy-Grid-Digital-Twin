"""Simulate a user-defined ("custom") grid.

This makes "build your own grid" real: a topology the user assembles in the
editor is turned into a **pandapower** network, an **AC power flow** is solved,
and per-bus / per-line state plus an **ontology** are returned. So a custom grid
is genuinely *simulated* — different hardware that produces a different ontology
— not just a redrawing of the fixed model.

Honest scope: this is an AC power-flow *snapshot* of the user's topology (not the
live swing-dynamics loop), and the line/transformer electrical parameters are
estimated per voltage class (standard practice — the real ones are non-public).
"""

from __future__ import annotations

import math
from datetime import datetime, timezone

from pydantic import BaseModel

# Thermal rating (MW) by voltage class, used to turn line flows into loadings.
_THERMAL_MW = {500: 2600.0, 345: 1200.0, 230: 700.0, 161: 400.0,
               132: 250.0, 115: 200.0, 69: 100.0, 33: 60.0}


def _rating_mw(kv: float) -> float:
    nearest = min(_THERMAL_MW, key=lambda k: abs(k - kv))
    return _THERMAL_MW[nearest]


class CustomBus(BaseModel):
    id: int
    voltage_kv: float = 132.0
    load_mw: float = 0.0
    gen_mw: float = 0.0
    is_slack: bool = False
    name: str = ""


class CustomLine(BaseModel):
    from_id: int
    to_id: int


class CustomGridSpec(BaseModel):
    buses: list[CustomBus] = []
    lines: list[CustomLine] = []


def _status_v(vm: float) -> str:
    dev = abs(vm - 1.0)
    return "CRITICAL" if dev > 0.10 else "DEGRADED" if dev > 0.05 else "NOMINAL"


def _status_load(pct: float) -> str:
    return "OVERLOADED" if pct > 100 else "DEGRADED" if pct > 80 else "NOMINAL"


def simulate_custom_grid(spec: CustomGridSpec) -> dict:
    """Build + AC-solve the custom grid; return {converged, message, buses, lines, ontology}."""
    if not spec.buses:
        return {"converged": False, "message": "Add at least one bus.",
                "buses": [], "lines": [], "ontology": {"nodes": [], "edges": []}}

    import pandapower as pp

    net = pp.create_empty_network(sn_mva=100.0)
    idx: dict[int, int] = {}
    kv_of: dict[int, float] = {}
    for b in spec.buses:
        kv = max(1.0, float(b.voltage_kv))
        kv_of[b.id] = kv
        idx[b.id] = pp.create_bus(net, vn_kv=kv, name=str(b.id))

    # Slack: explicit flag, else the largest generator, else the first bus.
    slack = next((b for b in spec.buses if b.is_slack), None)
    if slack is None:
        slack = max(spec.buses, key=lambda b: b.gen_mw)
    pp.create_ext_grid(net, idx[slack.id], vm_pu=1.0)

    for b in spec.buses:
        if b.load_mw > 0:
            pp.create_load(net, idx[b.id], p_mw=float(b.load_mw), q_mvar=float(b.load_mw) * 0.3)
        if b.gen_mw > 0 and b.id != slack.id:
            pp.create_gen(net, idx[b.id], p_mw=float(b.gen_mw), vm_pu=1.0,
                          min_p_mw=0.0, max_p_mw=float(b.gen_mw) * 1.5)

    # Branches: a line if the two ends share a voltage, else a transformer.
    branch_kind: list[tuple[CustomLine, str, int]] = []   # (line, "line"|"trafo", element index)
    for ln in spec.lines:
        if ln.from_id not in idx or ln.to_id not in idx or ln.from_id == ln.to_id:
            continue
        f_kv, t_kv = kv_of[ln.from_id], kv_of[ln.to_id]
        if abs(f_kv - t_kv) / max(f_kv, t_kv) < 0.1:
            kv = min(f_kv, t_kv)
            max_i_ka = _rating_mw(kv) / (3 ** 0.5 * kv)
            ei = pp.create_line_from_parameters(
                net, idx[ln.from_id], idx[ln.to_id], length_km=20.0,
                r_ohm_per_km=0.08, x_ohm_per_km=0.4, c_nf_per_km=0.0,
                max_i_ka=max(0.05, max_i_ka))
            branch_kind.append((ln, "line", ei))
        else:
            hi, lo = (ln.from_id, ln.to_id) if f_kv >= t_kv else (ln.to_id, ln.from_id)
            sn = _rating_mw(min(f_kv, t_kv))
            ei = pp.create_transformer_from_parameters(
                net, hv_bus=idx[hi], lv_bus=idx[lo], sn_mva=sn,
                vn_hv_kv=max(f_kv, t_kv), vn_lv_kv=min(f_kv, t_kv),
                vk_percent=12.0, vkr_percent=0.5, pfe_kw=0.0, i0_percent=0.0)
            branch_kind.append((ln, "trafo", ei))

    converged, message = False, ""
    for algo, kw in (("nr", {"init": "flat", "calculate_voltage_angles": True}),
                     ("gs", {"max_iteration": 300})):
        try:
            pp.runpp(net, algorithm=algo, **kw)
            converged = True
            break
        except Exception:
            continue
    if not converged:
        message = ("Power flow did not converge — make sure every bus connects "
                   "back to a slack/source and that generation can cover the load.")

    now = datetime.now(timezone.utc)
    gen_ids = {b.id for b in spec.buses if b.gen_mw > 0 or b.is_slack}

    isolated = 0
    buses_out = []
    for b in spec.buses:
        vm = float(net.res_bus.at[idx[b.id], "vm_pu"]) if (
            converged and idx[b.id] in net.res_bus.index) else float("nan")
        # A bus that did not solve — or that is isolated from any source, which
        # pandapower returns as NaN even on a "converged" run — must NOT be shown
        # as healthy. Report no voltage and UNKNOWN (the UI renders these grey).
        if math.isfinite(vm):
            va = float(net.res_bus.at[idx[b.id], "va_degree"])
            va = round(va, 2) if math.isfinite(va) else None
            buses_out.append({"id": b.id, "vm_pu": round(vm, 4), "va_deg": va,
                              "status": _status_v(vm), "is_gen": b.id in gen_ids,
                              "is_slack": b.id == slack.id})
        else:
            isolated += 1
            buses_out.append({"id": b.id, "vm_pu": None, "va_deg": None,
                              "status": "UNKNOWN", "is_gen": b.id in gen_ids,
                              "is_slack": b.id == slack.id})

    lines_out = []
    for ln, kind, ei in branch_kind:
        loading, flow = float("nan"), float("nan")
        if converged:
            tbl = net.res_line if kind == "line" else net.res_trafo
            if ei in tbl.index:
                loading = float(tbl.at[ei, "loading_percent"])
                flow = float(tbl.at[ei, "p_hv_mw" if kind == "trafo" else "p_from_mw"])
        if math.isfinite(loading):
            lines_out.append({"from_id": ln.from_id, "to_id": ln.to_id, "kind": kind,
                              "loading_pct": round(loading, 1),
                              "flow_mw": round(abs(flow), 1) if math.isfinite(flow) else 0.0,
                              "status": _status_load(loading)})
        else:
            lines_out.append({"from_id": ln.from_id, "to_id": ln.to_id, "kind": kind,
                              "loading_pct": 0.0, "flow_mw": 0.0, "status": "UNKNOWN"})

    if converged and isolated:
        message = (f"Solved, but {isolated} bus(es) are not connected to any source "
                   "— no voltage solution there. Connect them back to a generator/slack.")

    ontology = _custom_ontology(spec, buses_out, lines_out, slack.id, now)
    return {"converged": converged, "message": message,
            "buses": buses_out, "lines": lines_out, "ontology": ontology}


def _custom_ontology(spec, buses_out, lines_out, slack_id, now):
    from ontology.model import GridAsset, OntologyEdge, OntologyLink, OntologyResponse

    status_by_id = {b["id"]: b["status"] for b in buses_out}
    # A bus takes the most-severe status among itself and its incident lines, so a
    # heavily loaded line can escalate a bus but never mask a worse voltage signal.
    _sev = {"UNKNOWN": 0, "NOMINAL": 0, "DEGRADED": 1, "OVERLOADED": 2, "CRITICAL": 2}
    for ln in lines_out:
        for end in (ln["from_id"], ln["to_id"]):
            cur = status_by_id.get(end, "NOMINAL")
            if _sev.get(ln["status"], 0) > _sev.get(cur, 0):
                status_by_id[end] = ln["status"]

    bus_by_id = {b.id: b for b in spec.buses}
    sys_rid = "ri.custom-grid.system"
    gen_ids = [b["id"] for b in buses_out if b["is_gen"]]
    nodes = [GridAsset(
        rid=sys_rid, object_type="GridSystem", display_name="Custom Grid",
        properties={"buses": len(spec.buses), "lines": len(lines_out), "user_built": True},
        links=[OntologyLink(target_rid=f"ri.custom-grid.bus.{i}", link_type="hostsSource") for i in gen_ids],
        status="NOMINAL", last_updated=now,
    )]
    # The ontology status field is a fixed vocabulary; an unsolved/isolated bus
    # (UNKNOWN) maps to TRIPPED — de-energized — which the graph renders greyed-out.
    def _ont_status(s: str) -> str:
        return "TRIPPED" if s == "UNKNOWN" else s

    for b in buses_out:
        src = bus_by_id.get(b["id"])
        nodes.append(GridAsset(
            rid=f"ri.custom-grid.bus.{b['id']}",
            object_type="Generator" if b["is_gen"] else "Substation",
            display_name=(src.name if src and src.name else
                          (f"Gen {b['id']}" if b["is_gen"] else f"Bus {b['id']}")),
            properties={"voltage_kv": src.voltage_kv if src else 0,
                        "load_mw": src.load_mw if src else 0,
                        "gen_mw": src.gen_mw if src else 0,
                        "is_slack": b["is_slack"], "vm_pu": b["vm_pu"], "user_built": True},
            links=[], status=_ont_status(status_by_id.get(b["id"], "NOMINAL")), last_updated=now,
        ))
    edges = [OntologyEdge(source_rid=f"ri.custom-grid.bus.{ln['from_id']}",
                          target_rid=f"ri.custom-grid.bus.{ln['to_id']}",
                          link_type="connectsTo") for ln in lines_out]
    return OntologyResponse(nodes=nodes, edges=edges).model_dump(mode="json")

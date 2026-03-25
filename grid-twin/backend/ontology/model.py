"""
Ontology Data Models
====================
Pydantic v2 schemas for the Palantir Foundry-style ontology that wraps the
IEEE 9-bus digital twin.  Every physical asset is represented as a typed
``GridAsset`` node with directional ``OntologyLink`` edges.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel


class OntologyLink(BaseModel):
    target_rid: str
    link_type: str  # e.g. "hasSubstation", "connectedTo", "monitors"


class GridAsset(BaseModel):
    rid: str  # Resource ID — e.g. "ri.grid-asset.main.generator.1"
    object_type: Literal[
        "GridSystem", "Substation", "Generator", "TransmissionLine", "LoadBus"
    ]
    display_name: str
    properties: dict[str, Any]
    links: list[OntologyLink]
    status: Literal["NOMINAL", "DEGRADED", "OVERLOADED", "TRIPPED", "CRITICAL"]
    last_updated: datetime


class OntologyEdge(BaseModel):
    source_rid: str
    target_rid: str
    link_type: str


class OntologyResponse(BaseModel):
    nodes: list[GridAsset]
    edges: list[OntologyEdge]


class PropagationResponse(BaseModel):
    affected_nodes: list[str]
    affected_edges: list[OntologyEdge]
    propagation_order: list[str]


class GridAlert(BaseModel):
    id: str
    type: str
    severity: Literal["INFO", "WARNING", "CRITICAL"]
    affected_asset_rids: list[str]
    timestamp_sim: float
    timestamp_wall: datetime
    sensor_values: dict[str, float]
    acknowledged: bool = False

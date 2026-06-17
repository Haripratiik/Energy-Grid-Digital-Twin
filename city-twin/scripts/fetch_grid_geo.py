"""Fetch real Atlanta-metro power infrastructure from OpenStreetMap (Overpass).

Pulls actual transmission lines, substations, and power plants and writes a
compact GeoJSON used as the geographic backdrop in the operator console.

    python city-twin/scripts/fetch_grid_geo.py

Output: city-twin/frontend/public/atlanta_grid_infra.geojson
Data © OpenStreetMap contributors, ODbL.
"""

from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request

# Atlanta metro bounding box (S, W, N, E).
BBOX = (33.55, -84.66, 34.06, -84.05)
OVERPASS = "https://overpass-api.de/api/interpreter"

_QUERY = f"""
[out:json][timeout:60];
(
  way["power"="line"]({BBOX[0]},{BBOX[1]},{BBOX[2]},{BBOX[3]});
  way["power"="substation"]({BBOX[0]},{BBOX[1]},{BBOX[2]},{BBOX[3]});
  node["power"="substation"]({BBOX[0]},{BBOX[1]},{BBOX[2]},{BBOX[3]});
  way["power"="plant"]({BBOX[0]},{BBOX[1]},{BBOX[2]},{BBOX[3]});
  node["power"="plant"]({BBOX[0]},{BBOX[1]},{BBOX[2]},{BBOX[3]});
);
out geom;
"""

OUT = os.path.join(
    os.path.dirname(__file__), "..", "frontend", "public", "atlanta_grid_infra.geojson"
)


def _centroid(geometry: list[dict]) -> list[float]:
    lons = [p["lon"] for p in geometry]
    lats = [p["lat"] for p in geometry]
    return [sum(lons) / len(lons), sum(lats) / len(lats)]


def main() -> None:
    data = urllib.parse.urlencode({"data": _QUERY}).encode()
    req = urllib.request.Request(
        OVERPASS, data=data,
        headers={"User-Agent": "EnergyGridDigitalTwin/1.0 (research)",
                 "Accept": "application/json"},
    )
    print("Querying Overpass for Atlanta-metro power infrastructure…")
    with urllib.request.urlopen(req, timeout=90) as resp:
        osm = json.load(resp)

    features = []
    counts = {"line": 0, "substation": 0, "plant": 0}
    for el in osm.get("elements", []):
        ptype = el.get("tags", {}).get("power")
        tags = el.get("tags", {})
        props = {
            "power": ptype,
            "name": tags.get("name", ""),
            "voltage": tags.get("voltage", ""),
            "operator": tags.get("operator", ""),
        }
        if ptype == "line" and el["type"] == "way" and "geometry" in el:
            coords = [[p["lon"], p["lat"]] for p in el["geometry"]]
            features.append({"type": "Feature", "properties": props,
                             "geometry": {"type": "LineString", "coordinates": coords}})
            counts["line"] += 1
        elif ptype in ("substation", "plant"):
            if el["type"] == "node":
                pt = [el["lon"], el["lat"]]
            elif "geometry" in el:
                pt = _centroid(el["geometry"])
            else:
                continue
            features.append({"type": "Feature", "properties": props,
                             "geometry": {"type": "Point", "coordinates": pt}})
            counts[ptype] += 1

    fc = {
        "type": "FeatureCollection",
        "attribution": "© OpenStreetMap contributors (ODbL)",
        "bbox": list(BBOX),
        "features": features,
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(os.path.abspath(OUT), "w") as f:
        json.dump(fc, f)
    size_kb = os.path.getsize(OUT) / 1024
    print(f"Wrote {len(features)} features "
          f"(lines={counts['line']}, substations={counts['substation']}, plants={counts['plant']}) "
          f"-> {os.path.abspath(OUT)} ({size_kb:.0f} KB)")


if __name__ == "__main__":
    main()

"""
Export simulation data as CSV files suitable for uploading to Palantir Foundry.

Generates static topology + a time-series of simulation snapshots that you can
upload as Foundry datasets, then model in the Ontology.

Usage:
    cd city-twin/backend
    python export_foundry_datasets.py

Outputs go to ./foundry_export/
"""

import csv
import os
import time
import uuid
from datetime import datetime, timezone, timedelta

from physics.swing import GridSimulator
from physics.network import GENERATORS_CONFIG, BUSES, LINES, TRANSFORMERS
from ontology.store import AlertManager

OUT_DIR = os.path.join(os.path.dirname(__file__), "foundry_export")
os.makedirs(OUT_DIR, exist_ok=True)

SNAPSHOT_COUNT = 60
SNAPSHOT_INTERVAL_STEPS = 10


def export_buses():
    path = os.path.join(OUT_DIR, "grid_buses.csv")
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["bus_id", "voltage_kv", "p_load_mw", "q_load_mvar", "tier"])
        for b in BUSES:
            tier = "400kV" if b.voltage_kv >= 300 else "132kV" if b.voltage_kv >= 100 else "33kV"
            w.writerow([b.id, b.voltage_kv, b.p_load_mw, b.q_load_mvar, tier])
    print(f"  -> {path} ({len(BUSES)} rows)")


def export_generators():
    path = os.path.join(OUT_DIR, "grid_generators.csv")
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["gen_id", "bus_id", "gen_type", "capacity_mw", "p_mech_mw", "inertia_M", "damping_D", "ramp_rate_mw_per_s"])
        for g in GENERATORS_CONFIG:
            w.writerow([f"GEN-{g['bus_id']}", g["bus_id"], g["gen_type"], g["capacity_mw"],
                        g["p_mech_mw"], g["inertia_M"], g["damping_D"], g["ramp_rate_mw_per_s"]])
    print(f"  -> {path} ({len(GENERATORS_CONFIG)} rows)")


def export_lines():
    path = os.path.join(OUT_DIR, "grid_lines.csv")
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["line_id", "from_bus", "to_bus", "voltage_kv", "r_pu", "x_pu", "b_pu", "limit_mw"])
        for i, ln in enumerate(LINES):
            w.writerow([f"LINE-{i}", ln.from_bus, ln.to_bus, ln.voltage_kv, ln.r_pu, ln.x_pu, ln.b_pu, ln.limit_mw])
    print(f"  -> {path} ({len(LINES)} rows)")


def export_transformers():
    path = os.path.join(OUT_DIR, "grid_transformers.csv")
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["trafo_id", "from_bus", "to_bus", "rating_mva", "from_kv", "to_kv", "r_pu", "x_pu", "tap_ratio"])
        for i, t in enumerate(TRANSFORMERS):
            w.writerow([f"TRAFO-{i}", t.from_bus, t.to_bus, t.rating_mva, t.from_kv, t.to_kv, t.r_pu, t.x_pu, t.tap_ratio])
    print(f"  -> {path} ({len(TRANSFORMERS)} rows)")


def export_time_series():
    """Run simulator for N snapshots and export bus state + generator state + alerts."""
    sim = GridSimulator()
    alert_mgr = AlertManager()

    bus_path = os.path.join(OUT_DIR, "telemetry_bus_snapshots.csv")
    gen_path = os.path.join(OUT_DIR, "telemetry_generator_snapshots.csv")
    alert_path = os.path.join(OUT_DIR, "telemetry_alerts.csv")

    bus_f = open(bus_path, "w", newline="")
    gen_f = open(gen_path, "w", newline="")
    alert_f = open(alert_path, "w", newline="")

    bus_w = csv.writer(bus_f)
    gen_w = csv.writer(gen_f)
    alert_w = csv.writer(alert_f)

    bus_w.writerow(["snapshot_id", "timestamp", "sim_time_s", "bus_id", "voltage_kv", "voltage_pu",
                     "power_generation_mw", "power_load_mw", "status"])
    gen_w.writerow(["snapshot_id", "timestamp", "sim_time_s", "bus_id", "gen_type", "online",
                     "electrical_power_mw", "mechanical_power_mw", "rotor_angle_deg", "rotor_speed_rad_s"])
    alert_w.writerow(["alert_id", "timestamp", "type", "severity", "message", "bus_id", "sim_time_s"])

    base_time = datetime.now(timezone.utc)
    total_bus_rows = 0
    total_gen_rows = 0
    total_alert_rows = 0

    print(f"  Running {SNAPSHOT_COUNT} simulation snapshots...")

    for snap_idx in range(SNAPSHOT_COUNT):
        for _ in range(SNAPSHOT_INTERVAL_STEPS):
            state = sim.step()

        if state is None:
            continue

        snap_id = str(uuid.uuid4())[:8]
        ts = (base_time + timedelta(seconds=state.sim_time_s)).isoformat()

        for bus in state.buses:
            bus_w.writerow([snap_id, ts, round(state.sim_time_s, 2), bus.id, bus.voltage_kv,
                            round(bus.voltage_magnitude_pu, 4), round(bus.power_generation_mw, 2),
                            round(bus.power_load_mw, 2), bus.status])
            total_bus_rows += 1

        for gen in state.generators:
            gen_w.writerow([snap_id, ts, round(state.sim_time_s, 2), gen.bus_id, gen.gen_type,
                            gen.online, round(gen.electrical_power_mw, 2), round(gen.mechanical_power_mw, 2),
                            round(gen.rotor_angle_deg, 2), round(gen.rotor_speed_rad_s, 4)])
            total_gen_rows += 1

        new_alerts = alert_mgr.evaluate(state)
        for a in new_alerts:
            bus_id = ""
            if a.affected_asset_rids:
                parts = a.affected_asset_rids[0].split(".")
                bus_id = parts[-1] if parts else ""
            alert_w.writerow([a.id[:8], ts, a.type, a.severity, a.summary or "", bus_id, round(state.sim_time_s, 2)])
            total_alert_rows += 1

    bus_f.close()
    gen_f.close()
    alert_f.close()

    print(f"  -> {bus_path} ({total_bus_rows} rows)")
    print(f"  -> {gen_path} ({total_gen_rows} rows)")
    print(f"  -> {alert_path} ({total_alert_rows} rows)")


def export_atlanta_districts():
    """Export the Atlanta district metadata for geographic context."""
    path = os.path.join(OUT_DIR, "atlanta_districts.csv")
    districts = [
        ("Plant Vogtle", "Nuclear", "East", 1),
        ("Buford Dam", "Hydro", "North", 2),
        ("Buckhead", "Commercial/Residential", "North-Central", 28),
        ("Midtown", "Commercial Core", "Central", 71),
        ("Downtown", "CBD", "Central", 29),
        ("Hartsfield-Jackson", "Airport/Logistics", "South", 17),
        ("Perimeter", "Office/Tech", "North", 25),
        ("Decatur / Emory", "Medical/University", "East-Central", 37),
        ("Southside", "Residential/Industrial", "South", 43),
        ("West Industrial", "Manufacturing", "West", 9),
        ("Solar Fields", "Renewable Generation", "Far South", 5),
    ]
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["district_name", "type", "region", "primary_bus_id"])
        for d in districts:
            w.writerow(d)
    print(f"  -> {path} ({len(districts)} rows)")


if __name__ == "__main__":
    print("Exporting Foundry datasets...")
    print()
    print("[Static topology]")
    export_buses()
    export_generators()
    export_lines()
    export_transformers()
    export_atlanta_districts()
    print()
    print("[Time-series telemetry]")
    export_time_series()
    print()
    print(f"Done. Files in: {os.path.abspath(OUT_DIR)}")
    print()
    print("Upload these CSVs to Foundry as datasets, then define your Ontology:")
    print("  - Object type: GridBus        (from grid_buses.csv)")
    print("  - Object type: Generator      (from grid_generators.csv)")
    print("  - Object type: PowerLine      (from grid_lines.csv)")
    print("  - Object type: Transformer    (from grid_transformers.csv)")
    print("  - Object type: District       (from atlanta_districts.csv)")
    print("  - Object type: BusSnapshot    (from telemetry_bus_snapshots.csv)")
    print("  - Object type: GenSnapshot    (from telemetry_generator_snapshots.csv)")
    print("  - Object type: GridAlert      (from telemetry_alerts.csv)")

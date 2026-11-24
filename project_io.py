"""CSV/JSON boundaries. JSON arrays encode schedules and allowed modes in CSV."""
import csv
import json
from collections import defaultdict
from pathlib import Path

from generator import FreightNetwork, Service
from models.shipment import Shipment
from feasibility import feasibility_report

ROUTE_FIELDS = ("shipment_id", "status", "reason", "leg_index", "service_id", "origin",
                "destination", "mode", "departure", "arrival", "volume", "arrival_time")


def _write_csv(path, fields, rows):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def _read_csv(path):
    with Path(path).open(newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def write_routes(path, assignments):
    rows = []
    for record in assignments:
        shipment, route = record["shipment"], record["route"]
        common = {"shipment_id": shipment.shipment_id, "status": record["status"],
                  "reason": record["reason"] or "", "volume": shipment.volume,
                  "arrival_time": route["arrival_time"] if route is not None else ""}
        if route is None or not route["path"]:
            rows.append(common)
        else:
            for index, leg in enumerate(route["path"]):
                service = leg["service"]
                rows.append({**common, "leg_index": index, "service_id": service.service_id,
                             "origin": service.origin, "destination": service.destination,
                             "mode": service.mode, "departure": leg["departure"], "arrival": leg["arrival"]})
    _write_csv(path, ROUTE_FIELDS, rows)


def read_routes(path, network, shipments):
    lookup = {s.shipment_id: s for s in shipments}
    grouped = defaultdict(list)
    for row in _read_csv(path):
        grouped[row["shipment_id"]].append(row)
    assignments = []
    for shipment_id, rows in grouped.items():
        if shipment_id not in lookup:
            raise ValueError(f"Unknown shipment in routes: {shipment_id}")
        shipment = lookup[shipment_id]
        status, reason, final = rows[0]["status"], rows[0]["reason"] or None, rows[0]["arrival_time"]
        for row in rows:
            if ((row["status"], row["reason"] or None, row["arrival_time"]) != (status, reason, final)
                    or float(row["volume"]) != shipment.volume):
                raise ValueError("Inconsistent route rows.")
        if status == "unassigned":
            if len(rows) != 1 or rows[0]["service_id"] or final:
                raise ValueError("Unassigned route must contain one empty row.")
            route = None
        elif status == "assigned":
            path = []
            if rows[0]["service_id"]:
                rows.sort(key=lambda r: int(r["leg_index"]))
                for index, row in enumerate(rows):
                    if int(row["leg_index"]) != index:
                        raise ValueError("Route leg indices must be consecutive and unique.")
                    service = network.services[row["service_id"]]
                    if (row["origin"], row["destination"], row["mode"]) != (service.origin, service.destination, service.mode):
                        raise ValueError("Route service metadata mismatch.")
                    path.append({"service": service, "departure": float(row["departure"]),
                                 "arrival": float(row["arrival"])})
            elif len(rows) != 1:
                raise ValueError("Empty route must contain one row.")
            route = {"path": path, "arrival_time": float(final)}
        else:
            raise ValueError(f"Unknown route status: {status}")
        assignments.append({"shipment": shipment, "status": status, "route": route, "reason": reason})
    report = feasibility_report(network, assignments, shipments)
    if not report["valid"]:
        raise ValueError(f"Invalid imported routes: {report['errors'][:3]}")
    return assignments


def write_instance(directory, network, shipments, reference=None, metadata=None):
    directory = Path(directory)
    _write_csv(directory / "hubs.csv", ["hub_id"],
               ({"hub_id": hub} for hub in network.adjacency))
    fields = ["service_id", "origin", "destination", "mode", "travel_time", "cost", "emissions", "capacity", "departures"]
    _write_csv(directory / "links.csv", fields, (
        {**{name: getattr(s, name) for name in fields if name != "departures"},
         "departures": json.dumps(s.departures)} for s in network.services.values()))
    fields = ["shipment_id", "origin", "destination", "volume", "start_time", "deadline",
              "priority", "allowed_modes", "preferred_mode"]
    _write_csv(directory / "shipments.csv", fields, (
        {**{name: getattr(s, name) for name in fields if name not in ("allowed_modes", "preferred_mode")},
         "allowed_modes": json.dumps(sorted(s.allowed_modes) if s.allowed_modes is not None else None),
         "preferred_mode": s.preferred_mode or ""} for s in shipments))
    info = {"bucket_hours": network.bucket_hours, "planning_horizon": network.planning_horizon,
            "time_unit": "hours", "cost_model": "per_shipment", "time_model": "scheduled_fixed_duration",
            "metadata": metadata or {}}
    (directory / "instance.json").write_text(json.dumps(info, indent=2, allow_nan=False), encoding="utf-8")
    if reference is not None:
        if not feasibility_report(network, reference, shipments)["complete"]:
            raise ValueError("Reference plan must completely and validly route the instance.")
        write_routes(directory / "reference_routes.csv", reference)
    else:
        # Do not leave an old feasible-instance reference attached to a stress instance.
        reference_path = directory / "reference_routes.csv"
        if reference_path.exists():
            reference_path.unlink()


def read_instance(directory, bucket_hours=None, planning_horizon=None):
    directory = Path(directory)
    info = json.loads((directory / "instance.json").read_text(encoding="utf-8"))
    if (info.get("time_unit") != "hours" or info.get("cost_model") != "per_shipment"
            or info.get("time_model") != "scheduled_fixed_duration"):
        raise ValueError("Unsupported instance time units, cost model, or duration model.")
    if bucket_hours is not None and bucket_hours != info["bucket_hours"]:
        raise ValueError("Configured bucket duration differs from the input instance.")
    if planning_horizon is not None and planning_horizon != info["planning_horizon"]:
        raise ValueError("Configured horizon differs from the input instance.")
    network = FreightNetwork(info["bucket_hours"], info["planning_horizon"])
    for row in _read_csv(directory / "hubs.csv"):
        if row["hub_id"] in network.adjacency:
            raise ValueError("Duplicate hub ID.")
        network.add_hub(row["hub_id"])
    for row in _read_csv(directory / "links.csv"):
        if row["origin"] not in network.adjacency or row["destination"] not in network.adjacency:
            raise ValueError("A link refers to an unknown hub.")
        network.add_service(Service(row["service_id"], row["origin"], row["destination"], row["mode"],
                                    float(row["travel_time"]), float(row["cost"]), float(row["emissions"]),
                                    float(row["capacity"]), json.loads(row["departures"])))
    shipments, seen = [], set()
    for row in _read_csv(directory / "shipments.csv"):
        s = Shipment(row["shipment_id"], row["origin"], row["destination"], float(row["volume"]),
                     float(row["start_time"]), float(row["deadline"]), int(row["priority"]),
                     json.loads(row["allowed_modes"]), row["preferred_mode"] or None)
        if s.shipment_id in seen or s.origin not in network.adjacency or s.destination not in network.adjacency:
            raise ValueError("Duplicate shipment ID or unknown shipment hub.")
        seen.add(s.shipment_id)
        shipments.append(s)
    return network, shipments


def write_results(directory, network, shipments, result, config):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    write_routes(directory / "routes.csv", result["assignments"])
    unassigned = [{"shipment_id": r["shipment"].shipment_id, "reason": r["reason"]}
                  for r in result["assignments"] if r["status"] == "unassigned"]
    _write_csv(directory / "unassigned.csv", ["shipment_id", "reason"], unassigned)
    _write_csv(directory / "history.csv", list(result["history"][0]), result["history"])
    summary = {key: value for key, value in result.items() if key not in ("assignments", "capacity", "history")}
    report = feasibility_report(network, result["assignments"], shipments)
    summary.update({"parameters": config, "feasibility": report,
                    "actual_instance": {"hubs": len(network.adjacency), "links": len(network.services),
                                        "shipments": len(shipments), "bucket_hours": network.bucket_hours,
                                        "planning_horizon": network.planning_horizon},
                    "ranking_rule": "minimize (unassigned_count, weighted_soft_score)"})
    (directory / "metrics.json").write_text(json.dumps(summary, indent=2, allow_nan=False), encoding="utf-8")
    (directory / "history.json").write_text(json.dumps(result["history"], indent=2, allow_nan=False), encoding="utf-8")
    lines = ["# Feasibility report", "", f"Assigned routes valid: {report['valid']}",
             f"Complete delivery: {report['complete']}",
             f"Assigned: {report['assigned']}/{report['total_shipments']}", "",
             "Capacity: departure throughput per fixed time bucket; scheduled capacity per departure.",
             "Times: hours from time zero. Service durations are fixed.", ""]
    lines.extend(f"- {e['shipment_id']}: {e['rule']}" for e in report["errors"])
    (directory / "feasibility_report.md").write_text("\n".join(lines), encoding="utf-8")
    if not report["valid"]:
        raise ValueError("Exported optimizer result failed independent validation.")

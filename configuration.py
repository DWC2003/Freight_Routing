"""Strict configuration loading; paths are resolved relative to the config file."""
import json
from pathlib import Path
from models.common import integer, number
from objective import normalize_weights

DEFAULTS = {
    "seed": 42, "hub_count": 500, "link_count": 5000, "shipment_count": 10000,
    "iterations": 3, "alpha": .3, "rcl_size": None, "max_no_improvement": 2,
    "max_local_moves": 12, "max_routes": 2, "max_route_searches": 4,
    "max_rebuild_shipments": 8, "capacity_bucket_hours": 1.0,
    "planning_horizon": 336.0, "max_legs": 4, "deadline_slack": 24.0,
    "max_attempts_per_shipment": 100, "scenario": "feasible",
    "capacity_factor": .5, "deadline_factor": .5,
    "data_dir": "data", "output_dir": "out", "input_dir": None,
    "weights": {"cost": 1.0, "travel_time": 10.0, "transfer": 50.0,
                "emissions": 1.0, "preferred_mode": 25.0, "unassigned_penalty": 1000000.0},
}


def validate_config(config):
    unknown = set(config) - set(DEFAULTS)
    if unknown:
        raise ValueError(f"Unknown configuration keys: {sorted(unknown)}")
    values = {**DEFAULTS, **config}
    for name in ("iterations", "max_routes", "max_route_searches", "max_legs", "max_attempts_per_shipment"):
        integer(name, values[name])
    for name in ("seed", "shipment_count", "max_local_moves"):
        integer(name, values[name], minimum=0)
    integer("hub_count", values["hub_count"], minimum=2)
    integer("link_count", values["link_count"], minimum=values["hub_count"])
    integer("max_rebuild_shipments", values["max_rebuild_shipments"], minimum=2)
    for name in ("rcl_size", "max_no_improvement"):
        if values[name] is not None:
            integer(name, values[name])
    for name in ("capacity_bucket_hours", "planning_horizon", "capacity_factor", "deadline_factor"):
        number(name, values[name], positive=True)
    number("deadline_slack", values["deadline_slack"])
    number("alpha", values["alpha"])
    for name in ("alpha", "capacity_factor", "deadline_factor"):
        if values[name] > 1:
            raise ValueError(f"{name} must not exceed one.")
    if values["scenario"] not in ("feasible", "stress"):
        raise ValueError("scenario must be feasible or stress.")
    for name in ("data_dir", "output_dir", "input_dir"):
        if values[name] is None and name == "input_dir":
            continue
        if not isinstance(values[name], str) or not values[name].strip():
            raise ValueError(f"{name} must be a nonempty path.")
    normalize_weights(values["weights"])
    return values


def load_config(path, overrides=None):
    path = Path(path).resolve()
    values = validate_config({**json.loads(path.read_text(encoding="utf-8")), **(overrides or {})})
    for name in ("data_dir", "output_dir", "input_dir"):
        if values[name] is not None:
            values[name] = str((path.parent / values[name]).resolve())
    return values

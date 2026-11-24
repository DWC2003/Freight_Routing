# Measures routes and compares solutions based on objectives

from dataclasses import dataclass
from math import isfinite
from numbers import Real

@dataclass(frozen=True)
class ObjectiveWeights:
    cost: float = 1.0
    travel_time: float = 10.0
    transfer: float = 50.0
    emissions: float = 1.0
    unassigned_penalty: float = 1000000.0
    preferred_mode: float = 25.0

    def __post_init__(self):
        names = (
            "cost",
            "travel_time",
            "transfer",
            "emissions",
            "preferred_mode",
            "unassigned_penalty"
        )

        for name in names:
            value = getattr(self, name)

            if isinstance(value, bool) or not isinstance(value, Real):
                raise TypeError(f"{name} must be a real number.")

            if not isfinite(value) or value < 0:
                raise ValueError(f"{name} must be finite and nonnegative.")

        if self.unassigned_penalty == 0:
            raise ValueError("unassigned_penalty must be positive.")

def normalize_weights(weights):
    # Accept defaults, an ObjectiveWeights instance, or a weight dict

    if weights is None:
        return ObjectiveWeights()

    if isinstance(weights, ObjectiveWeights):
        return weights

    if isinstance(weights, dict):
        return ObjectiveWeights(**weights)

    raise TypeError("weights must be ObjectiveWeights, a dict, or None")

def route_metrics(path, start_time=None, preferred_mode=None):
    # Calculate unweighted metrics for an already validated route

    metrics = {
        "cost": 0.0,
        "travel_time": 0.0,
        "transfers": 0,
        "emissions": 0.0,
        "mode_mismatches": 0
    }

    if not path:
        return metrics
    previous_mode = None

    for leg in path:
        service = leg["service"]

        metrics["cost"] += service.cost
        metrics["emissions"] += service.emissions
        if preferred_mode is not None and service.mode != preferred_mode:
            metrics["mode_mismatches"] += 1

        if previous_mode is not None and service.mode != previous_mode:
            metrics["transfers"] += 1

        previous_mode = service.mode

    if start_time is None:
        start_time = path[0]["departure"]

    metrics["travel_time"] = path[-1]["arrival"] - start_time

    return metrics

def solution_metrics(assignments):
    # Aggregate unweighted metrics across all shipment assignments
    metrics = {
        "total_shipments": 0,
        "assigned": 0,
        "unassigned": 0,
        "cost": 0.0,
        "travel_time": 0.0,
        "transfers": 0,
        "emissions": 0.0,
        "mode_mismatches": 0
    }

    for result in assignments:
        metrics["total_shipments"] += 1
        status = result["status"]

        if status == "unassigned":
            if result["route"] is not None:
                raise ValueError("An unassigned shipment cannot have a route")

            metrics["unassigned"] += 1
            continue

        if status != "assigned":
            raise ValueError(f"Unknown assignment status: {status!r}")

        route = result["route"]
        if route is None:
            raise ValueError("An assigned shipment must have a route.")

        shipment = result["shipment"]
        values = route_metrics(
            route["path"],
            start_time=shipment.start_time,
            preferred_mode=shipment.preferred_mode,
        )

        metrics["assigned"] += 1

        for name in ("cost", "travel_time", "transfers", "emissions", "mode_mismatches"):
            metrics[name] += values[name]

    return metrics

def weighted_objective(assignments, weights=None):
    # Return the weighted score for a complete assignment list

    weights = normalize_weights(weights)

    metrics = solution_metrics(assignments)

    return soft_objective(metrics, weights) + weights.unassigned_penalty * metrics["unassigned"]


def soft_objective(metrics, weights=None):
    """Explainable weighted sum; service costs/emissions are per shipment."""
    weights = normalize_weights(weights)
    return (
        weights.cost * metrics["cost"]
        + weights.travel_time * metrics["travel_time"]
        + weights.transfer * metrics["transfers"]
        + weights.emissions * metrics["emissions"]
        + weights.preferred_mode * metrics["mode_mismatches"]
    )


def solution_rank(assignments, weights=None):
    """Delivery coverage takes precedence over the weighted soft objective."""
    metrics = solution_metrics(assignments)
    return metrics["unassigned"], soft_objective(metrics, weights)

# Measures routes and compares solutions based on objectives

from dataclasses import dataclass

@dataclass(frozen=True)
class ObjectiveWeights:
    cost: float = 1.0
    travel_time: float = 10.0
    transfer: float = 50.0
    emissions: float = 1.0
    unassigned_penalty: float = 1000000.0

def route_metrics(path, start_time=None):
    # Calculate unweighted metrics for an already validated route

    metrics = {
        "cost": 0.0,
        "travel_time": 0.0,
        "transfers": 0,
        "emissions": 0.0
    }

    if not path:
        return metrics
    previous_mode = None

    for leg in path:
        service = leg["service"]

        metrics["cost"] += service.cost
        metrics["emissions"] += service.emissions

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
        "emissions": 0.0
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
            start_time=shipment.start_time
        )

        metrics["assigned"] += 1

        for name in ("cost", "travel_time", "transfers", "emissions"):
            metrics[name] += values[name]

    return metrics

def weighted_objective(assignments, weights=None):
    # Return the weighted score for a complete assignment list

    if weights is None:
        weights = ObjectiveWeights()
    elif isinstance(weights, dict):
        weights = ObjectiveWeights(**weights)
    elif not isinstance(weights, ObjectiveWeights):
        raise TypeError("weights must be ObjectiveWeights, a dict, or None")

    metrics = solution_metrics(assignments)

    return (
        weights.cost * metrics["cost"]
        + weights.travel_time * metrics["travel_time"]
        + weights.transfer * metrics["transfers"]
        + weights.emissions * metrics["emissions"]
        + weights.unassigned_penalty * metrics["unassigned"]
    )
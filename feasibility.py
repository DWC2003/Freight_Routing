"""Independent validation of coverage, network paths, timing and capacity."""
from math import isclose
from generator import get_transfer_delays, travel_duration
from models.common import number


def feasibility_report(network, assignments, shipments=None):
    assignments = list(assignments)
    expected = None
    errors = []
    seen = set()
    assigned = 0
    capacity = network.new_capacity_manager()
    if shipments is not None:
        shipments = list(shipments)
        expected = {s.shipment_id: s for s in shipments}
        if len(expected) != len(shipments):
            errors.append({"shipment_id": None, "rule": "duplicate_expected_id"})

    for record in assignments:
        shipment_id = None
        try:
            shipment = record["shipment"]
            shipment_id = shipment.shipment_id
            if shipment_id in seen:
                raise ValueError("duplicate_assignment")
            seen.add(shipment_id)
            if expected is not None and (shipment_id not in expected or shipment != expected[shipment_id]):
                raise ValueError("unexpected_or_altered_shipment")
            number("volume", shipment.volume, positive=True)
            number("start_time", shipment.start_time)
            number("deadline", shipment.deadline, minimum=shipment.start_time)
            status, route = record["status"], record["route"]
            if status == "unassigned":
                if route is not None:
                    raise ValueError("unassigned_has_route")
                continue
            if status != "assigned" or route is None:
                raise ValueError("invalid_status_or_missing_route")
            if shipment.origin not in network.adjacency or shipment.destination not in network.adjacency:
                raise ValueError("unknown_hub")
            hub, ready, previous_mode = shipment.origin, shipment.start_time, None
            path = route["path"]
            if not isinstance(path, (list, tuple)):
                raise ValueError("invalid_path")
            for index, leg in enumerate(path):
                service = leg["service"]
                if network.services.get(service.service_id) is not service:
                    raise ValueError(f"leg_{index}:service_not_in_network")
                if service.origin != hub:
                    raise ValueError(f"leg_{index}:path_discontinuity")
                departure, arrival = leg["departure"], leg["arrival"]
                number("departure", departure)
                number("arrival", arrival)
                for field in ("capacity", "cost", "emissions"):
                    number(field, getattr(service, field))
                duration = travel_duration(service, departure)
                number("travel_duration", duration)
                earliest = ready + get_transfer_delays(previous_mode, service.mode)
                if departure + 1e-9 < earliest:
                    raise ValueError(f"leg_{index}:release_or_transfer_time")
                if shipment.allowed_modes is not None and service.mode not in shipment.allowed_modes:
                    raise ValueError(f"leg_{index}:mode_restriction")
                if service.departures is not None and departure not in service.departures:
                    raise ValueError(f"leg_{index}:not_a_scheduled_departure")
                if arrival < departure or not isclose(arrival, departure + duration, rel_tol=0, abs_tol=1e-9):
                    raise ValueError(f"leg_{index}:incorrect_arrival")
                hub, ready, previous_mode = service.destination, arrival, service.mode
            if hub != shipment.destination:
                raise ValueError("incorrect_destination_or_empty_path")
            final = number("final_arrival", route["arrival_time"])
            if not isclose(final, ready, rel_tol=0, abs_tol=1e-9):
                raise ValueError("incorrect_final_arrival")
            if max(final, ready) > min(shipment.deadline, network.planning_horizon):
                raise ValueError("deadline_or_horizon")
            if not capacity.reserve_route(path, shipment.volume):
                raise ValueError("capacity_exceeded")
            assigned += 1
        except (KeyError, TypeError, ValueError, AttributeError, OverflowError) as exc:
            errors.append({"shipment_id": shipment_id, "rule": str(exc)})

    if expected is not None:
        for shipment_id in sorted(set(expected) - seen):
            errors.append({"shipment_id": shipment_id, "rule": "missing_assignment"})
    valid = not errors
    total = len(expected) if expected is not None else len(assignments)
    return {"valid": valid, "complete": valid and assigned == total,
            "total_shipments": total, "assigned": assigned,
            "unassigned": total - assigned, "errors": errors}


def solution_is_feasible(network, assignments, shipments=None, require_complete=False):
    report = feasibility_report(network, assignments, shipments)
    return report["complete"] if require_complete else report["valid"]

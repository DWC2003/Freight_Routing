"""Assign whole shipments one at a time, keeping earlier assignments."""

from algorithms.dijkstra import CapacityManager, time_dependant_dijkstra


def greedy_assign(network, shipments, capacity_manager=None, order="priority"):
    """Return one result per shipment, in processing order.

    order="priority": higher priority first, then earlier deadline.
    order="input": process the supplied order as a simple baseline.
    Equal sorting keys keep their input order. The input list is not changed.
    Pass a CapacityManager to inspect or reuse the resulting reservations.
    Each independent experiment should start with a fresh CapacityManager.
    """
    shipments = list(shipments)
    ids = [shipment.shipment_id for shipment in shipments]
    if len(ids) != len(set(ids)):
        raise ValueError("Shipment IDs must be unique within an assignment run.")

    if order == "priority":
        ordered = sorted(shipments, key=lambda s: (-s.priority, s.deadline))
    elif order == "input":
        ordered = shipments
    else:
        raise ValueError("Order must be 'priority' or 'input'.")

    if capacity_manager is None:
        capacity_manager = network.new_capacity_manager()

    assignments = []
    for shipment in ordered:
        result = {
            "shipment": shipment,
            "status": "unassigned",
            "route": None,
            "reason": None,
        }

        if (shipment.origin not in network.adjacency
                or shipment.destination not in network.adjacency):
            result["reason"] = "unknown_hub"
            assignments.append(result)
            continue

        # Dijkstra reads shared reservations; it does not book anything.
        route = time_dependant_dijkstra(
            network=network,
            origin=shipment.origin,
            destination=shipment.destination,
            start_time=shipment.start_time,
            deadline=shipment.deadline,
            demand=shipment.volume,
            capacity_manager=capacity_manager,
            allowed_modes=shipment.allowed_modes,
        )

        if route is None:
            result["reason"] = "no_feasible_route"
        elif not capacity_manager.reserve_route(route["path"], shipment.volume):
            result["reason"] = "insufficient_capacity"
        else:
            result["status"] = "assigned"
            result["route"] = route

        assignments.append(result)

    return assignments

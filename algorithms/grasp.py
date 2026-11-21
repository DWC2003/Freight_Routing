"""GRASP optimizer for the freight-routing project."""

import random
from collections import deque
from math import ceil, isfinite

from algorithms.dijkstra import CapacityManager, time_dependant_dijkstra
from generator import get_transfer_delays
from objective import ObjectiveWeights, route_metrics, solution_metrics, weighted_objective


def _record(shipment, status="unassigned", route=None, reason=None):
    return {"shipment": shipment, "status": status, "route": route, "reason": reason}


class _ExcludedServiceNetwork:
    """A view of a network that suppresses selected service IDs."""

    def __init__(self, network, excluded_service_ids):
        self.network = network
        self.excluded_service_ids = frozenset(excluded_service_ids)

    def get_outgoing(self, hub):
        return [
            service for service in self.network.get_outgoing(hub)
            if service.service_id not in self.excluded_service_ids
        ]


def generate_alternative_routes(network, shipment, capacity_manager=None,
                                max_routes=8, weights=None):
    """Generate distinct feasible routes by removing route service edges.

    This is a service-edge exclusion search layered over the existing
    time-dependent Dijkstra implementation, so scheduled departures,
    capacity pools, release times, transfer delays and shipment restrictions
    remain in the original routing code.
    """
    routes = []
    seen = set()
    queue = deque([frozenset()])

    while queue and len(routes) < max_routes:
        excluded = queue.popleft()
        routed_network = (_ExcludedServiceNetwork(network, excluded)
                          if excluded else network)
        route = time_dependant_dijkstra(
            network=routed_network,
            origin=shipment.origin,
            destination=shipment.destination,
            start_time=shipment.start_time,
            deadline=shipment.deadline,
            demand=shipment.volume,
            capacity_manager=capacity_manager,
            allowed_modes=shipment.allowed_modes,
        )
        if route is None:
            continue

        signature = tuple(
            (leg["service"].service_id, leg["departure"])
            for leg in route["path"]
        )
        if signature not in seen:
            seen.add(signature)
            routes.append(route)

        if len(excluded) >= 3:
            continue

        for leg in route["path"]:
            service_id = leg["service"].service_id
            expanded = excluded | {service_id}
            if expanded not in queue:
                queue.append(expanded)

    routes.sort(key=lambda r: (_candidate_quality(r, shipment, weights),
                                r["arrival_time"],
                                tuple(s["service"].service_id for s in r["path"])))
    return routes


def _candidate_quality(route, shipment, weights):
    w = weights if isinstance(weights, ObjectiveWeights) else ObjectiveWeights()
    metrics = route_metrics(route["path"], start_time=shipment.start_time)
    deadline_penalty = max(0.0, route["arrival_time"] - shipment.deadline)
    return (
        w.cost * metrics["cost"]
        + w.travel_time * metrics["travel_time"]
        + w.transfer * metrics["transfers"]
        + w.emissions * metrics["emissions"]
        + 100.0 * deadline_penalty
    )


def randomized_greedy_construction(network, shipments, capacity_manager=None,
                                    alpha=0.3, rcl_size=None, rng=None,
                                    weights=None):
    """Build one feasible assignment using an RCL and return (assignments, capacity)."""
    rng = rng or random.Random()
    capacity = capacity_manager if capacity_manager is not None else CapacityManager()
    remaining = list(shipments)
    ids = [s.shipment_id for s in remaining]
    if len(ids) != len(set(ids)):
        raise ValueError("Shipment IDs must be unique within an assignment run.")

    assignments = []

    while remaining:
        candidates = []
        for shipment in remaining:
            if (shipment.origin not in network.adjacency
                    or shipment.destination not in network.adjacency):
                candidates.append((float("inf"), shipment, None, "unknown_hub"))
                continue

            routes = generate_alternative_routes(
                network, shipment, capacity_manager=capacity,
                max_routes=8, weights=weights,
            )
            if not routes:
                candidates.append((float("inf"), shipment, None, "no_feasible_route"))
            else:
                for route in routes:
                    quality = _candidate_quality(route, shipment, weights)
                    candidates.append((quality, shipment, route, None))

        feasible = [candidate for candidate in candidates if candidate[2] is not None]
        if feasible:
            feasible.sort(key=lambda c: (
                c[0] + 0.01 * c[1].deadline - 0.05 * c[1].priority,
                c[1].deadline,
                -c[1].priority,
                c[1].shipment_id,
            ))
            if rcl_size is not None:
                limit = max(1, min(int(rcl_size), len(feasible)))
            else:
                alpha = max(0.0, min(1.0, float(alpha)))
                best = feasible[0][0]
                worst = feasible[-1][0]
                threshold = best + alpha * max(0.0, worst - best)
                rcl = [candidate for candidate in feasible
                       if candidate[0] <= threshold]
                # Keep at least the two strongest route choices when possible.
                limit = max(1, min(len(feasible), max(ceil(alpha * len(feasible)),
                                                   min(2, len(rcl)))))
                rcl = rcl[:limit]
                chosen = rng.choice(rcl)
                feasible = rcl

            if rcl_size is not None:
                chosen = rng.choice(feasible[:limit])
        else:
            chosen = rng.choice(candidates)

        _, shipment, route, reason = chosen
        remaining.remove(shipment)

        if route is None:
            assignments.append(_record(shipment, reason=reason or "no_feasible_route"))
            continue

        if capacity.reserve_route(route["path"], shipment.volume):
            assignments.append(_record(shipment, "assigned", route))
        else:
            assignments.append(_record(shipment, reason="insufficient_capacity"))

    return assignments, capacity


def reconstruct_solution(network, shipments, capacity_manager=None, weights=None):
    """Deterministically rebuild a solution in the supplied shipment order."""
    return randomized_greedy_construction(
        network, shipments, capacity_manager=capacity_manager,
        alpha=0.0, rng=random.Random(0), weights=weights,
    )


def _normalize_weights(weights):
    if weights is None:
        return ObjectiveWeights()
    if isinstance(weights, ObjectiveWeights):
        return weights
    if isinstance(weights, dict):
        base = ObjectiveWeights()
        return ObjectiveWeights(
            cost=weights.get("cost", base.cost),
            travel_time=weights.get("travel_time", base.travel_time),
            transfer=weights.get("transfer", weights.get("transfers", base.transfer)),
            emissions=weights.get("emissions", base.emissions),
            unassigned_penalty=weights.get("unassigned_penalty", base.unassigned_penalty),
        )
    return weights


def reroute_local_search(network, assignments, weights=None):
    """Try to improve every assigned shipment by rerouting it on fresh capacity."""
    order = [result["shipment"] for result in assignments]
    current = list(assignments)
    current_value = weighted_objective(current, weights)

    for target in order:
        capacity = CapacityManager()
        rebuilt = []

        for result in current:
            shipment = result["shipment"]
            if shipment is target:
                continue
            if result["status"] == "assigned" and result["route"] is not None:
                if not capacity.reserve_route(result["route"]["path"], shipment.volume):
                    rebuilt.append(_record(shipment, reason="insufficient_capacity"))
                else:
                    rebuilt.append(_record(shipment, "assigned", result["route"]))
            else:
                rebuilt.append(_record(shipment, reason=result["reason"]))

        target_routes = generate_alternative_routes(
            network, target, capacity_manager=capacity,
            max_routes=10, weights=weights,
        )

        target_records = []
        if target_routes:
            for target_route in target_routes:
                trial_capacity = CapacityManager()
                trial_capacity.reserved = dict(capacity.reserved)
                if trial_capacity.reserve_route(target_route["path"], target.volume):
                    target_records.append(_record(target, "assigned", target_route))
        else:
            target_records.append(_record(target, reason="no_feasible_route"))

        rebuilt_by_id = {r["shipment"].shipment_id: r for r in rebuilt}
        for target_record in target_records:
            rebuilt_by_id[target.shipment_id] = target_record
            candidate = [rebuilt_by_id[r["shipment"].shipment_id] for r in current]
            candidate_value = weighted_objective(candidate, weights)
            if candidate_value + 1e-9 < current_value:
                current = candidate
                current_value = candidate_value

    return current


def reorder_local_search(network, assignments, weights=None):
    """Try pairwise order swaps and rebuild the solution after each swap."""
    order = [r["shipment"] for r in assignments]
    current = list(assignments)
    current_value = weighted_objective(current, weights)

    improved = True
    while improved:
        improved = False
        for i in range(len(order)):
            for j in range(i + 1, len(order)):
                trial = list(order)
                trial[i], trial[j] = trial[j], trial[i]
                candidate, _ = reconstruct_solution(
                    network, trial, capacity_manager=None, weights=weights
                )
                candidate_value = weighted_objective(candidate, weights)
                if candidate_value + 1e-9 < current_value:
                    order = trial
                    current = candidate
                    current_value = candidate_value
                    improved = True
                    break
            if improved:
                break

    return current


def local_search(network, assignments, weights=None):
    assignments = reroute_local_search(network, assignments, weights)
    assignments = reorder_local_search(network, assignments, weights)
    return assignments


def solution_is_feasible(network, assignments):
    """Check deadlines, release times, modes, transfers and capacity for a solution."""
    capacity = CapacityManager()

    for result in assignments:
        shipment = result["shipment"]
        if result["status"] != "assigned":
            continue
        route = result["route"]
        if route is None:
            return False
        if shipment.allowed_modes is not None:
            if any(leg["service"].mode not in shipment.allowed_modes for leg in route["path"]):
                return False

        ready = shipment.start_time
        previous_mode = None
        for leg in route["path"]:
            service = leg["service"]
            ready += get_transfer_delays(previous_mode, service.mode)
            departure = leg["departure"]
            if departure + 1e-9 < ready:
                return False
            if service.departures is not None and departure not in service.departures:
                return False
            if leg["arrival"] + 1e-9 < departure + service.travel_time:
                return False
            if leg["arrival"] + 1e-9 > shipment.deadline:
                return False
            if not capacity.reserve_route([leg], shipment.volume):
                return False
            ready = leg["arrival"]
            previous_mode = service.mode

        if route["arrival_time"] + 1e-9 > shipment.deadline:
            return False

    return True


def grasp_assign(network, shipments, iterations=50, alpha=0.3, weights=None,
                 seed=None, rcl_size=None, random_state=None):
    """Run GRASP and return the best feasible solution.

    The returned dictionary contains assignments, a CapacityManager, objective
    value, metrics, runtime, iteration count and seed for reproducible reporting.
    """
    import time

    shipments = list(shipments)
    weights = _normalize_weights(weights)
    rng = random_state if random_state is not None else random.Random(seed)
    effective_seed = seed

    start = time.perf_counter()
    best_assignments = None
    best_capacity = CapacityManager()
    best_value = float("inf")

    for _ in range(max(0, int(iterations))):
        assignments, capacity = randomized_greedy_construction(
            network, shipments, capacity_manager=CapacityManager(),
            alpha=alpha, rcl_size=rcl_size, rng=rng, weights=weights,
        )
        assignments = local_search(network, assignments, weights)

        # Local search is rebuilt deterministically, so rebuild capacity for the
        # final result and discard it if any selected route conflicts.
        final_capacity = CapacityManager()
        feasible = True
        for result in assignments:
            if result["status"] == "assigned":
                if not final_capacity.reserve_route(result["route"]["path"], result["shipment"].volume):
                    feasible = False
                    break
        if not feasible or not solution_is_feasible(network, assignments):
            continue

        value = weighted_objective(assignments, weights)
        if value < best_value:
            best_assignments = assignments
            best_capacity = final_capacity
            best_value = value

    if best_assignments is None:
        best_assignments = []
        best_capacity = CapacityManager()
        for shipment in shipments:
            best_assignments.append(_record(shipment, reason="no_feasible_route"))
        best_value = weighted_objective(best_assignments, weights)

    elapsed = time.perf_counter() - start
    metrics = solution_metrics(best_assignments)

    return {
        "assignments": best_assignments,
        "capacity": best_capacity,
        "objective": best_value,
        "weighted_objective": best_value,
        "metrics": metrics,
        "runtime": elapsed,
        "iterations": max(0, int(iterations)),
        "seed": effective_seed,
    }


# Common descriptive aliases.
grasp_optimize = grasp_assign
grasp_solve = grasp_assign


class GRASPOptimizer:
    """Reusable object interface around :func:`grasp_assign`."""

    def __init__(self, iterations=50, alpha=0.3, weights=None, seed=None,
                 rcl_size=None):
        self.iterations = iterations
        self.alpha = alpha
        self.weights = weights
        self.seed = seed
        self.rcl_size = rcl_size

    def optimize(self, network, shipments):
        return grasp_assign(
            network, shipments, iterations=self.iterations,
            alpha=self.alpha, weights=self.weights, seed=self.seed,
            rcl_size=self.rcl_size,
        )

    run = optimize

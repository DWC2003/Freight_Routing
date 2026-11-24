"""GRASP with randomized construction and bounded local-search neighborhoods."""
import random
import time
from collections import deque

from algorithms.greedy import greedy_assign
from algorithms.dijkstra import time_dependant_dijkstra
from feasibility import solution_is_feasible
from models.common import integer, number
from objective import (normalize_weights, route_metrics, soft_objective,
                       solution_metrics, solution_rank, weighted_objective)

# Preserve the previously used helper name for callers.
_normalize_weights = normalize_weights


def _record(shipment, status="unassigned", route=None, reason=None):
    return {"shipment": shipment, "status": status, "route": route, "reason": reason}


def _validate_positive_int(name, value):
    return integer(name, value)


def _validate_rcl_parameters(alpha, rcl_size):
    number("alpha", alpha)
    if alpha > 1:
        raise ValueError("alpha must be between 0 and 1.")
    if rcl_size is not None:
        integer("rcl_size", rcl_size)


def _unique_shipments(shipments):
    shipments = list(shipments)
    if len({s.shipment_id for s in shipments}) != len(shipments):
        raise ValueError("Shipment IDs must be unique within an assignment run.")
    return shipments


class _ExcludedServiceNetwork:
    def __init__(self, network, excluded):
        self.network, self.excluded = network, excluded

    def __getattr__(self, name):
        return getattr(self.network, name)

    def get_outgoing(self, hub):
        return [s for s in self.network.get_outgoing(hub) if s.service_id not in self.excluded]


def _candidate_quality(route, shipment, weights):
    metrics = route_metrics(route["path"], shipment.start_time, shipment.preferred_mode)
    return number("candidate score", soft_objective(metrics, weights))


def generate_alternative_routes(network, shipment, capacity_manager=None,
                                max_routes=8, weights=None, max_searches=16, stats=None):
    """Bound both distinct routes and Dijkstra calls; not exhaustive enumeration."""
    integer("max_routes", max_routes)
    integer("max_searches", max_searches)
    weights = normalize_weights(weights)
    routes, signatures = [], set()
    queue, scheduled = deque([frozenset()]), {frozenset()}
    searches = 0
    while queue and len(routes) < max_routes and searches < max_searches:
        excluded = queue.popleft()
        view = _ExcludedServiceNetwork(network, excluded) if excluded else network
        searches += 1
        if stats is not None:
            stats["route_searches"] = stats.get("route_searches", 0) + 1
        route = time_dependant_dijkstra(
            view, shipment.origin, shipment.destination, shipment.start_time,
            deadline=shipment.deadline, demand=shipment.volume,
            capacity_manager=capacity_manager, allowed_modes=shipment.allowed_modes)
        if route is None:
            continue
        signature = tuple((leg["service"].service_id, leg["departure"]) for leg in route["path"])
        if signature not in signatures:
            signatures.add(signature)
            routes.append(route)
        if len(excluded) < 3:
            for leg in route["path"]:
                expanded = excluded | {leg["service"].service_id}
                if expanded not in scheduled:
                    scheduled.add(expanded)
                    queue.append(expanded)
    routes.sort(key=lambda r: (_candidate_quality(r, shipment, weights), r["arrival_time"],
                              tuple(leg["service"].service_id for leg in r["path"])))
    return routes


def _assign_one(network, shipment, capacity, weights, max_routes, max_route_searches,
                rng=None, alpha=0, rcl_size=None, stats=None):
    if shipment.origin not in network.adjacency or shipment.destination not in network.adjacency:
        return _record(shipment, reason="unknown_hub")
    routes = generate_alternative_routes(network, shipment, capacity, max_routes, weights,
                                         max_searches=max_route_searches, stats=stats)
    if not routes:
        return _record(shipment, reason="no_feasible_route")
    if rng is None:
        route = routes[0]
    else:
        if rcl_size is not None:
            rcl = routes[:rcl_size]
        else:
            best = _candidate_quality(routes[0], shipment, weights)
            worst = _candidate_quality(routes[-1], shipment, weights)
            threshold = best + alpha * (worst - best)
            rcl = [r for r in routes if _candidate_quality(r, shipment, weights) <= threshold]
        route = rng.choice(rcl)
    if not capacity.reserve_route(route["path"], shipment.volume):
        return _record(shipment, reason="insufficient_capacity")
    return _record(shipment, "assigned", route)


def randomized_greedy_construction(network, shipments, capacity_manager=None,
                                    alpha=0.3, rcl_size=None, rng=None, weights=None,
                                    max_routes=8, max_route_searches=16, stats=None):
    """Shuffle within priority tiers, then pick a route from each shipment's RCL.

    alpha=0 retains minimum-score ties; alpha=1 retains every generated route.
    An explicit rcl_size overrides the threshold. Routes are recomputed only for
    the shipment being processed, rather than for every remaining shipment.
    """
    _validate_rcl_parameters(alpha, rcl_size)
    integer("max_routes", max_routes)
    integer("max_route_searches", max_route_searches)
    weights = normalize_weights(weights)
    ordered = _unique_shipments(shipments)
    rng = random.Random() if rng is None else rng
    rng.shuffle(ordered)
    ordered.sort(key=lambda s: -s.priority)
    capacity = network.new_capacity_manager() if capacity_manager is None else capacity_manager
    assignments = []
    for shipment in ordered:
        if stats is not None:
            stats["construction_route_generations"] = stats.get("construction_route_generations", 0) + 1
        assignments.append(_assign_one(network, shipment, capacity, weights, max_routes,
                                       max_route_searches, rng, alpha, rcl_size, stats))
    return assignments, capacity


def reconstruct_solution(network, shipments, capacity_manager=None, weights=None,
                         max_routes=8, max_route_searches=16, stats=None):
    """Deterministically reconstruct in exactly the supplied shipment order."""
    weights = normalize_weights(weights)
    integer("max_routes", max_routes)
    integer("max_route_searches", max_route_searches)
    shipments = _unique_shipments(shipments)
    capacity = network.new_capacity_manager() if capacity_manager is None else capacity_manager
    return [_assign_one(network, s, capacity, weights, max_routes, max_route_searches,
                        stats=stats) for s in shipments], capacity


def _fixed_capacity(network, assignments, excluded_indices):
    capacity = network.new_capacity_manager()
    for index, record in enumerate(assignments):
        if index not in excluded_indices and record["status"] == "assigned":
            if not capacity.reserve_route(record["route"]["path"], record["shipment"].volume):
                raise ValueError("Existing assignments exceed capacity.")
    return capacity


def _without(capacity, assignments, excluded_indices):
    trial = capacity.copy()
    for index in excluded_indices:
        record = assignments[index]
        if record["status"] == "assigned":
            if not trial.release_route(record["route"]["path"], record["shipment"].volume):
                raise ValueError("Reservation ledger does not match existing assignments.")
    return trial


def _improves(network, candidate, current, weights):
    # Validate only potentially improving candidates, but always check coverage.
    return (solution_rank(candidate, weights) < solution_rank(current, weights)
            and solution_is_feasible(network, candidate,
                                     shipments=[r["shipment"] for r in current]))


def _move(stats):
    if stats is not None:
        stats["local_moves"] = stats.get("local_moves", 0) + 1


def reroute_local_search(network, assignments, weights=None, rng=None, max_moves=20,
                         max_routes=8, max_route_searches=16, stats=None):
    weights = normalize_weights(weights)
    integer("max_moves", max_moves, minimum=0)
    rng = random.Random(0) if rng is None else rng
    current = list(assignments)
    ledger = _fixed_capacity(network, current, set())
    for index in rng.sample(range(len(current)), min(len(current), max_moves)):
        _move(stats)
        capacity = _without(ledger, current, {index})
        candidate = list(current)
        candidate[index] = _assign_one(network, current[index]["shipment"], capacity,
                                       weights, max_routes, max_route_searches, stats=stats)
        if _improves(network, candidate, current, weights):
            current, ledger = candidate, capacity
    return current


def _sample_pairs(size, limit, rng, window=None):
    """Bound selection work too; do not materialize the quadratic pair set."""
    seen = set()
    for _ in range(limit * 8):
        if len(seen) >= limit or size < 2:
            return
        if window is None:
            i, j = sorted(rng.sample(range(size), 2))
        else:
            i = rng.randrange(size - 1)
            j = rng.randrange(i + 1, min(size, i + window))
        if (i, j) not in seen:
            seen.add((i, j))
            yield i, j


def repair_local_search(network, assignments, weights=None, max_pairs=20, rng=None,
                        max_moves=None, max_routes=8, max_route_searches=16, stats=None):
    integer("max_pairs", max_pairs)
    limit = max_pairs * 2 if max_moves is None else integer("max_moves", max_moves, minimum=0)
    weights = normalize_weights(weights)
    rng = random.Random(0) if rng is None else rng
    current, attempted = list(assignments), 0
    ledger = _fixed_capacity(network, current, set())
    for i, j in _sample_pairs(len(current), max_pairs, rng):
        fixed = _without(ledger, current, {i, j})
        first, second = current[i]["shipment"], current[j]["shipment"]
        for order in ([first, second], [second, first]):
            if attempted >= limit:
                return current
            attempted += 1
            _move(stats)
            repaired, _ = reconstruct_solution(network, order, fixed.copy(), weights,
                                               max_routes, max_route_searches, stats)
            by_id = {r["shipment"].shipment_id: r for r in repaired}
            candidate = list(current)
            candidate[i], candidate[j] = by_id[first.shipment_id], by_id[second.shipment_id]
            if _improves(network, candidate, current, weights):
                return candidate
    return current


def reorder_local_search(network, assignments, weights=None, rng=None, max_moves=20,
                         max_rebuild_shipments=16, max_routes=8, max_route_searches=16,
                         stats=None):
    """Swap within bounded windows, holding routes outside each window fixed."""
    weights = normalize_weights(weights)
    integer("max_moves", max_moves, minimum=0)
    integer("max_rebuild_shipments", max_rebuild_shipments, minimum=2)
    rng = random.Random(0) if rng is None else rng
    current = list(assignments)
    ledger = _fixed_capacity(network, current, set())
    for i, j in _sample_pairs(len(current), max_moves, rng, max_rebuild_shipments):
        _move(stats)
        indices = set(range(i, j + 1))
        capacity = _without(ledger, current, indices)
        order = [current[k]["shipment"] for k in range(i, j + 1)]
        order[0], order[-1] = order[-1], order[0]
        rebuilt, _ = reconstruct_solution(network, order, capacity, weights,
                                          max_routes, max_route_searches, stats)
        by_id = {r["shipment"].shipment_id: r for r in rebuilt}
        candidate = list(current)
        for k in indices:
            candidate[k] = by_id[current[k]["shipment"].shipment_id]
        if _improves(network, candidate, current, weights):
            current, ledger = candidate, capacity
    return current


def local_search(network, assignments, weights=None, rng=None, max_moves=30,
                 max_routes=8, max_route_searches=16, max_rebuild_shipments=16, stats=None):
    integer("max_moves", max_moves, minimum=0)
    weights = normalize_weights(weights)
    rng = random.Random(0) if rng is None else rng
    # One shared per-iteration budget partitioned across the three neighborhoods.
    reroutes = max_moves // 3
    repairs = max_moves // 3
    swaps = max_moves - reroutes - repairs
    common = dict(weights=weights, rng=rng, max_routes=max_routes,
                  max_route_searches=max_route_searches, stats=stats)
    assignments = reroute_local_search(network, assignments, max_moves=reroutes, **common)
    assignments = repair_local_search(network, assignments, max_moves=repairs, **common)
    return reorder_local_search(network, assignments, max_moves=swaps,
                                max_rebuild_shipments=max_rebuild_shipments, **common)


def grasp_assign(network, shipments, iterations=50, alpha=0.3, weights=None, seed=None,
                 rcl_size=None, random_state=None, max_no_improvement=None,
                 max_local_moves=30, max_routes=8, max_route_searches=16,
                 max_rebuild_shipments=16):
    """Retain the best (unassigned count, soft score) starting from greedy."""
    integer("iterations", iterations)
    _validate_rcl_parameters(alpha, rcl_size)
    if max_no_improvement is not None:
        integer("max_no_improvement", max_no_improvement)
    integer("max_local_moves", max_local_moves, minimum=0)
    integer("max_routes", max_routes)
    integer("max_route_searches", max_route_searches)
    integer("max_rebuild_shipments", max_rebuild_shipments, minimum=2)
    shipments, weights = _unique_shipments(shipments), normalize_weights(weights)
    rng = random.Random(seed) if random_state is None else random_state
    started = time.perf_counter()
    capacity = network.new_capacity_manager()
    best = greedy_assign(network, shipments, capacity, order="priority")
    if not solution_is_feasible(network, best, shipments):
        raise ValueError("The greedy baseline contains invalid routes.")
    best_rank = baseline_rank = solution_rank(best, weights)
    baseline_value = weighted_objective(best, weights)
    history, stats = [], {"route_searches": 0, "construction_route_generations": 0, "local_moves": 0}
    stagnant, completed, stop_reason = 0, 0, "iteration_limit"

    def log(iteration, candidate, valid):
        rank = solution_rank(candidate, weights) if valid else None
        history.append({"iteration": iteration, "elapsed_seconds": time.perf_counter() - started,
                        "current_score": weighted_objective(candidate, weights) if valid else None,
                        "best_score": weighted_objective(best, weights),
                        "current_soft_score": rank[1] if rank is not None else None,
                        "best_soft_score": best_rank[1], "best_rank": list(best_rank),
                        "assigned_count": sum(r["status"] == "assigned" for r in candidate),
                        "best_assigned_count": len(shipments) - best_rank[0], "valid": valid,
                        "local_moves": stats["local_moves"], "route_searches": stats["route_searches"]})

    log(0, best, True)
    for iteration in range(1, iterations + 1):
        candidate, _ = randomized_greedy_construction(
            network, shipments, alpha=alpha, rcl_size=rcl_size, rng=rng, weights=weights,
            max_routes=max_routes, max_route_searches=max_route_searches, stats=stats)
        candidate = local_search(network, candidate, weights, rng, max_local_moves,
                                 max_routes, max_route_searches, max_rebuild_shipments, stats)
        valid = solution_is_feasible(network, candidate, shipments)
        rank = solution_rank(candidate, weights) if valid else None
        if rank is not None and rank < best_rank:
            best, best_rank, stagnant = candidate, rank, 0
            capacity = _fixed_capacity(network, best, set())
        else:
            stagnant += 1
        completed = iteration
        log(iteration, candidate, valid)
        if max_no_improvement is not None and stagnant >= max_no_improvement:
            stop_reason = "no_improvement_limit"
            break
    value = weighted_objective(best, weights)
    return {"assignments": best, "capacity": capacity, "objective": value,
            "weighted_objective": value, "rank": list(best_rank),
            "baseline_objective": baseline_value, "baseline_rank": list(baseline_rank),
            "metrics": solution_metrics(best), "runtime": time.perf_counter() - started,
            "iterations": completed, "requested_iterations": iterations,
            "seed": seed, "history": history, "stop_reason": stop_reason, "search_stats": stats}


grasp_optimize = grasp_assign
grasp_solve = grasp_assign


class GRASPOptimizer:
    def __init__(self, iterations=50, alpha=0.3, weights=None, seed=None,
                 rcl_size=None, max_no_improvement=None, max_local_moves=30,
                 max_routes=8, max_route_searches=16, max_rebuild_shipments=16):
        integer("iterations", iterations)
        _validate_rcl_parameters(alpha, rcl_size)
        if max_no_improvement is not None:
            integer("max_no_improvement", max_no_improvement)
        integer("max_local_moves", max_local_moves, minimum=0)
        integer("max_routes", max_routes)
        integer("max_route_searches", max_route_searches)
        integer("max_rebuild_shipments", max_rebuild_shipments, minimum=2)
        self.iterations, self.alpha, self.weights = iterations, alpha, normalize_weights(weights)
        self.seed, self.rcl_size = seed, rcl_size
        self.max_no_improvement, self.max_local_moves = max_no_improvement, max_local_moves
        self.max_routes, self.max_route_searches = max_routes, max_route_searches
        self.max_rebuild_shipments = max_rebuild_shipments

    def optimize(self, network, shipments):
        return grasp_assign(network, shipments, **vars(self))

    run = optimize

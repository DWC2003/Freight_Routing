"""Regression tests for the routing pipeline and its hard constraints."""
import copy
import json
import random
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from algorithms.dijkstra import CapacityManager, time_dependant_dijkstra
import algorithms.grasp as grasp
from algorithms.greedy import greedy_assign
from configuration import validate_config
from feasibility import feasibility_report, solution_is_feasible
from generator import FreightNetwork, Service, get_transfer_delays, next_feasible_departure
from instance_generator import generate_instance, stress_instance
from models.shipment import Shipment
from objective import ObjectiveWeights, normalize_weights, solution_rank, weighted_objective
from project_io import read_instance, read_routes, write_instance, write_results


def service(sid="t", origin="A", destination="B", **kwargs):
    values = dict(mode="truck", travel_time=1, cost=1, emissions=0, capacity=1, departures=None)
    values.update(kwargs)
    return Service(sid, origin, destination, **values)


def network(*services, **kwargs):
    result = FreightNetwork(**kwargs)
    for item in services:
        result.add_service(item)
    return result


def shipment(sid="s", **kwargs):
    values = dict(origin="A", destination="B", volume=1, start_time=0, deadline=10)
    values.update(kwargs)
    return Shipment(sid, **values)


def record(s, path, arrival):
    return {"shipment": s, "status": "assigned", "reason": None,
            "route": {"path": path, "arrival_time": arrival}}


def leg(s, departure=0, arrival=1):
    return {"service": s, "departure": departure, "arrival": arrival}


COST_ONLY = ObjectiveWeights(cost=1, travel_time=0, transfer=0, emissions=0, preferred_mode=0)


class ModelTests(unittest.TestCase):
    def test_modes_and_transfer_rules(self):
        self.assertEqual(service(mode="Sea").mode, "ship")
        self.assertEqual(shipment(allowed_modes={"Rail"}, preferred_mode="RAIL").allowed_modes, {"rail"})
        for a in ("truck", "rail", "air", "ship"):
            for b in ("truck", "rail", "air", "ship"):
                self.assertEqual(get_transfer_delays(a, b) == 0, a == b)
        with self.assertRaises(ValueError):
            get_transfer_delays("spaceship", "truck")

    def test_invalid_services_and_demands(self):
        for field in ("travel_time", "capacity", "cost", "emissions"):
            for value in (-1, float("nan"), float("inf"), True, "1"):
                with self.subTest(field=field, value=value), self.assertRaises((ValueError, TypeError)):
                    service(**{field: value})
        with self.assertRaises(ValueError):
            network(service(), service())
        with self.assertRaises(TypeError):
            shipment(allowed_modes="rail")
        with self.assertRaises(TypeError):
            shipment(priority=True)
        self.assertEqual(service(departures=[4, 2, 2]).departures, [2, 4])


class CapacityTests(unittest.TestCase):
    def test_wait_and_deadline(self):
        s = service()
        n = network(s)
        c = n.new_capacity_manager()
        self.assertTrue(c.reserve(s, 0, 1))
        route = time_dependant_dijkstra(n, "A", "B", 0, deadline=2, capacity_manager=c)
        self.assertEqual(route["path"][0]["departure"], 1)
        self.assertIsNone(time_dependant_dijkstra(n, "A", "B", 0, deadline=1, capacity_manager=c))
        self.assertEqual(next_feasible_departure(s, 0, 2, c, 20), None)
        self.assertTrue(c.reserve(s, 100, 1))

    def test_schedule_and_fractional_bucket(self):
        s = service(mode="rail", departures=[2, 5])
        n = network(s, bucket_hours=.1)
        c = n.new_capacity_manager()
        c.reserve(s, 2, 1)
        self.assertEqual(next_feasible_departure(s, 0, 1, c, 5), 5)
        t = service("continuous")
        self.assertEqual(c.reservation_key(t, .3), c.reservation_key(t, .30000000000000004))
        c.reserve(t, .3, 1)
        self.assertAlmostEqual(next_feasible_departure(t, .3, 1, c, .5), .4)

    def test_admissible_pruning_matches_unpruned_search(self):
        n, items, reference = generate_instance(12, 50, 40, seed=19)
        capacity = n.new_capacity_manager()
        for row in reference[:10]:
            capacity.reserve_route(row["route"]["path"], row["shipment"].volume)
        for s in items:
            args = (n, s.origin, s.destination, s.start_time)
            kwargs = dict(deadline=s.deadline, demand=s.volume, capacity_manager=capacity,
                          allowed_modes=s.allowed_modes)
            pruned = time_dependant_dijkstra(*args, **kwargs)
            with patch.object(n, "travel_lower_bounds", return_value={hub: 0 for hub in n.adjacency}):
                unpruned = time_dependant_dijkstra(*args, **kwargs)
            self.assertEqual(pruned is None, unpruned is None)
            if pruned is not None:
                self.assertAlmostEqual(pruned["arrival_time"], unpruned["arrival_time"])
        old = n.travel_lower_bounds(items[0].destination)
        n.add_service(service("shortcut", items[0].origin, items[0].destination, travel_time=0))
        self.assertIsNot(old, n.travel_lower_bounds(items[0].destination))

    def test_atomic_reserve_release_and_copy(self):
        a, b = service("a"), service("b", "B", "C", capacity=0)
        c = CapacityManager()
        self.assertFalse(c.reserve_route([leg(a), leg(b)], 1))
        self.assertEqual(c.reserved, {})
        self.assertTrue(c.reserve(a, 0, 1))
        clone = c.copy()
        self.assertTrue(clone.release_route([leg(a)], 1))
        self.assertEqual(clone.reserved, {})
        self.assertTrue(c.reserved)
        self.assertFalse(c.release_route([leg(a), leg(b)], 1))
        self.assertTrue(c.reserved)

    def test_fractional_volume_rounding(self):
        s = service(capacity=.3)
        c = CapacityManager()
        self.assertTrue(c.reserve(s, 0, .1))
        self.assertTrue(c.reserve(s, 0, .2))
        self.assertFalse(c.reserve(s, 0, .01))
        self.assertTrue(c.release_route([leg(s)], .1))
        self.assertTrue(c.release_route([leg(s)], .2))
        self.assertEqual(c.reserved, {})

    def test_transfer_and_modes(self):
        t = service("t", "A", "B", travel_time=4)
        r = service("r", "B", "C", mode="rail", travel_time=8, departures=[6, 18])
        n = network(t, r)
        route = time_dependant_dijkstra(n, "A", "C", 0, deadline=30)
        self.assertEqual(route["arrival_time"], 26)
        self.assertIsNone(time_dependant_dijkstra(n, "A", "C", 0, 30, allowed_modes={"truck"}))
        self.assertIsNone(time_dependant_dijkstra(n, "A", "missing", 0))


class FeasibilityTests(unittest.TestCase):
    def setUp(self):
        self.t = service()
        self.n = network(self.t)
        self.s = shipment()
        self.good = record(self.s, [leg(self.t)], 1)

    def test_valid_partial_complete_and_coverage(self):
        self.assertTrue(solution_is_feasible(self.n, [self.good], [self.s], True))
        missing = grasp._record(self.s, reason="no_feasible_route")
        self.assertTrue(solution_is_feasible(self.n, [missing], [self.s]))
        self.assertFalse(solution_is_feasible(self.n, [missing], [self.s], True))
        self.assertFalse(solution_is_feasible(self.n, [], [self.s]))
        self.assertFalse(solution_is_feasible(self.n, [self.good, self.good], [self.s]))
        clone = copy.copy(self.s)
        clone.deadline = 100
        self.assertFalse(solution_is_feasible(self.n, [record(clone, [leg(self.t)], 1)], [self.s]))

    def test_reject_invalid_paths_and_times(self):
        foreign = service("foreign", "X", "Y")
        cases = [record(self.s, [], 0), record(self.s, [leg(foreign)], 1),
                 record(self.s, [leg(self.t)], 0),
                 record(self.s, [leg(self.t, float("nan"), float("nan"))], float("nan")),
                 record(self.s, [leg(self.t, 0, 2)], 2),
                 record(self.s, [leg(self.t, -1, 0)], 0)]
        for item in cases:
            with self.subTest(item=item):
                self.assertFalse(solution_is_feasible(self.n, [item], [self.s]))
        x = service("x", "X", "B")
        self.n.add_service(x)
        self.assertFalse(solution_is_feasible(self.n, [record(self.s, [leg(x)], 1)]))

    def test_overbooking_empty_path_and_compatibility(self):
        other = shipment("other")
        self.assertFalse(solution_is_feasible(self.n, [self.good, record(other, [leg(self.t)], 1)]))
        local = shipment(origin="A", destination="A")
        self.assertTrue(solution_is_feasible(self.n, [record(local, [], 0)], [local], True))
        restricted = shipment(allowed_modes={"rail"})
        self.assertFalse(solution_is_feasible(self.n, [record(restricted, [leg(self.t)], 1)]))
        bad_status = dict(self.good, status="unknown")
        self.assertFalse(solution_is_feasible(self.n, [bad_status]))


class OptimizationTests(unittest.TestCase):
    def test_alpha_and_weight_dictionary(self):
        n = network(*(service(str(c), cost=c, capacity=10) for c in (10, 20, 50)))
        s = shipment()
        class Spy:
            def shuffle(self, items):
                pass
            def choice(self, routes):
                self.costs = [r["path"][0]["service"].cost for r in routes]
                return routes[0]
        weights = dict(cost=1, travel_time=0, transfer=0, emissions=0, preferred_mode=0)
        for alpha, expected in ((0, [10]), (.25, [10, 20]), (1, [10, 20, 50])):
            spy = Spy()
            grasp.randomized_greedy_construction(n, [s], weights=weights, alpha=alpha, rng=spy)
            self.assertEqual(spy.costs, expected)
        spy = Spy()
        grasp.randomized_greedy_construction(n, [s], weights=weights, alpha=0, rcl_size=2, rng=spy)
        self.assertEqual(spy.costs, [10, 20])
        self.assertEqual(grasp.generate_alternative_routes(n, s, weights=weights),
                         grasp.generate_alternative_routes(n, s, weights=COST_ONLY))

    def test_preferences_and_coverage_first(self):
        n = network(service("truck", cost=1), service("rail", mode="rail", cost=2000000))
        flex = shipment("flex", priority=2)
        restricted = shipment("restricted", deadline=1, allowed_modes={"truck"})
        # Tight deadlines prohibit simply waiting for another continuous bucket.
        flex.deadline = 1
        result = grasp.grasp_assign(n, [flex, restricted], iterations=2, weights=COST_ONLY,
                                    seed=42, max_local_moves=6, max_routes=2, max_route_searches=4)
        self.assertEqual(result["rank"][0], 0)
        self.assertLess(tuple(result["rank"]), tuple(result["baseline_rank"]))
        self.assertGreater(result["objective"], result["baseline_objective"])
        preferred = shipment(preferred_mode="rail")
        cheap_network = network(service("truck", cost=1), service("rail", mode="rail", cost=10))
        weights = dict(cost=1, travel_time=0, transfer=0, emissions=0, preferred_mode=100)
        routes = grasp.generate_alternative_routes(cheap_network, preferred, weights=weights)
        self.assertEqual(routes[0]["path"][0]["service"].mode, "rail")

    def test_order_pair_repair_and_seed(self):
        n = network(service("truck"), service("rail", mode="rail", cost=10))
        a = shipment("flex", deadline=1)
        b = shipment("restricted", deadline=1, allowed_modes={"truck"})
        bad, _ = grasp.reconstruct_solution(n, [a, b], weights=COST_ONLY)
        good, _ = grasp.reconstruct_solution(n, [b, a], weights=COST_ONLY)
        self.assertEqual([r["shipment"] for r in good], [b, a])
        self.assertLess(solution_rank(good, COST_ONLY), solution_rank(bad, COST_ONLY))
        repaired = grasp.repair_local_search(n, bad, weights=COST_ONLY)
        self.assertEqual(solution_rank(repaired, COST_ONLY), (0, 11))
        self.assertEqual(grasp.repair_local_search(n, good, weights=COST_ONLY), good)
        for items in ([], [a], [a, b]):
            first = grasp.grasp_assign(n, items, iterations=2, seed=42, max_local_moves=6)
            second = grasp.grasp_assign(n, items, iterations=2, seed=42, max_local_moves=6)
            self.assertEqual(first["assignments"], second["assignments"])
            self.assertLessEqual(tuple(first["rank"]), tuple(first["baseline_rank"]))

    def test_history_stopping_and_work_limits(self):
        n = network(service(capacity=100))
        items = [shipment(str(i)) for i in range(30)]
        result = grasp.grasp_assign(n, items, iterations=8, max_no_improvement=2, seed=42,
                                    max_local_moves=6, max_routes=2, max_route_searches=3)
        self.assertEqual(result["iterations"], 2)
        self.assertEqual(result["stop_reason"], "no_improvement_limit")
        self.assertEqual(len(result["history"]), 3)
        self.assertEqual(result["search_stats"]["construction_route_generations"], 60)
        self.assertLessEqual(result["search_stats"]["local_moves"], 12)
        ranks = [tuple(h["best_rank"]) for h in result["history"]]
        self.assertTrue(all(a >= b for a, b in zip(ranks, ranks[1:])))
        stats = {}
        grasp.generate_alternative_routes(n, items[0], max_routes=10, max_searches=1, stats=stats)
        self.assertEqual(stats["route_searches"], 1)

    def test_invalid_parameters_even_on_empty_inputs(self):
        n = network(service())
        for args in ({"iterations": 0}, {"iterations": True}, {"alpha": float("nan")},
                     {"alpha": 1.1}, {"rcl_size": 0}, {"max_local_moves": -1},
                     {"max_routes": 0}, {"max_route_searches": 0}, {"max_no_improvement": 0},
                     {"weights": object()}):
            with self.subTest(args=args), self.assertRaises((ValueError, TypeError)):
                grasp.grasp_assign(n, [], **args)
        for value in (-1, float("inf"), True, "1"):
            with self.assertRaises((TypeError, ValueError)):
                ObjectiveWeights(cost=value)
        with self.assertRaises(TypeError):
            normalize_weights({"typo": 1})
        with self.assertRaises(ValueError):
            validate_config({"alpha": 2})


class PipelineTests(unittest.TestCase):
    def test_generation_reproducibility_reference_and_stress(self):
        n, items, ref = generate_instance(12, 40, 50, seed=7, bucket_hours=.5)
        other, demands, other_ref = generate_instance(12, 40, 50, seed=7, bucket_hours=.5)
        self.assertEqual(items, demands)
        self.assertEqual(list(n.services.values()), list(other.services.values()))
        self.assertEqual(ref, other_ref)
        self.assertTrue(solution_is_feasible(n, ref, items, True))
        stressed, tightened = stress_instance(n, items)
        self.assertLessEqual(tightened[0].deadline, items[0].deadline)
        self.assertEqual(stressed.bucket_hours, .5)
        self.assertEqual(n.services["L00000"].capacity, 50)

    def test_csv_round_trip_and_json_exports(self):
        n, items, reference = generate_instance(10, 30, 30, seed=8)
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            write_instance(directory, n, items, reference)
            loaded, demands = read_instance(directory)
            routes = read_routes(directory / "reference_routes.csv", loaded, demands)
            self.assertTrue(solution_is_feasible(loaded, routes, demands, True))
            self.assertEqual(items, demands)
            with self.assertRaises(ValueError):
                read_instance(directory, bucket_hours=.5)
            result = grasp.grasp_assign(loaded, demands, iterations=1, seed=42,
                                        max_local_moves=3, max_routes=2, max_route_searches=3)
            write_results(directory / "out", loaded, demands, result, {"seed": 42})
            summary = json.loads((directory / "out" / "metrics.json").read_text())
            self.assertTrue(summary["feasibility"]["valid"])
            reloaded = read_routes(directory / "out" / "routes.csv", loaded, demands)
            self.assertEqual(solution_rank(reloaded), solution_rank(result["assignments"]))
            write_instance(directory, n, items, reference=None)
            self.assertFalse((directory / "reference_routes.csv").exists())


if __name__ == "__main__":
    unittest.main()

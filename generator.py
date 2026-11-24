"""Network model and departures. Times are hours from time zero."""
from bisect import bisect_left
import heapq
from collections import defaultdict
from dataclasses import dataclass
from math import inf
from typing import Optional

from models.common import MODES, identifier, mode, number

# Illustrative handling delays shared by generation, routing and validation.
TRANSFER_DELAYS = {
    ("truck", "rail"): 3, ("rail", "truck"): 2,
    ("truck", "ship"): 4, ("ship", "truck"): 4,
    ("rail", "ship"): 5, ("ship", "rail"): 5,
    ("truck", "air"): 2, ("air", "truck"): 2,
    ("rail", "air"): 4, ("air", "rail"): 4,
    ("ship", "air"): 6, ("air", "ship"): 6,
}


def get_transfer_delays(old_mode, new_mode):
    new_mode = mode(new_mode)
    if old_mode is None:
        return 0
    old_mode = mode(old_mode)
    return 0 if old_mode == new_mode else TRANSFER_DELAYS[old_mode, new_mode]


@dataclass
class Service:
    service_id: str
    origin: str
    destination: str
    mode: str
    travel_time: float
    cost: float
    emissions: float
    capacity: float
    departures: Optional[list[float]] = None

    def __post_init__(self):
        for name in ("service_id", "origin", "destination"):
            identifier(name, getattr(self, name))
        self.mode = mode(self.mode)
        for name in ("travel_time", "cost", "emissions", "capacity"):
            number(name, getattr(self, name))
        if self.departures is not None:
            values = list(self.departures)
            for value in values:
                number("departure", value)
            self.departures = sorted(set(values))


def travel_duration(service, departure):
    """Scheduled, fixed-duration model; shared hook for future time profiles."""
    return service.travel_time


class FreightNetwork:
    def __init__(self, bucket_hours=1.0, planning_horizon=336.0):
        self.bucket_hours = number("bucket_hours", bucket_hours, positive=True)
        self.planning_horizon = number("planning_horizon", planning_horizon, positive=True)
        self.adjacency = defaultdict(list)
        self.services = {}
        self._reverse_edges = defaultdict(list)
        self._lower_bound_cache = {}

    def add_hub(self, hub):
        identifier("hub", hub)
        self.adjacency.setdefault(hub, [])

    def add_service(self, service):
        if service.service_id in self.services:
            raise ValueError(f"Duplicate service ID: {service.service_id}")
        self.add_hub(service.origin)
        self.add_hub(service.destination)
        self.services[service.service_id] = service
        self.adjacency[service.origin].append(service)
        self._reverse_edges[service.destination].append((service.origin, service.travel_time))
        self._lower_bound_cache.clear()

    def get_outgoing(self, hub):
        return self.adjacency.get(hub, [])

    def travel_lower_bounds(self, destination):
        """Admissible static durations: ignore waits, transfers, modes and capacity.

        Models are built before solving; add_service invalidates these caches.
        Edges excluded by a route search may remain in the bound graph, which
        only makes its estimates more optimistic.
        """
        if destination not in self._lower_bound_cache:
            distances = {destination: 0}
            queue = [(0, destination)]
            while queue:
                distance, hub = heapq.heappop(queue)
                if distance != distances[hub]:
                    continue
                for previous, duration in self._reverse_edges.get(hub, []):
                    candidate = distance + duration
                    if candidate < distances.get(previous, float("inf")):
                        distances[previous] = candidate
                        heapq.heappush(queue, (candidate, previous))
            self._lower_bound_cache[destination] = distances
        return self._lower_bound_cache[destination]

    def new_capacity_manager(self):
        from algorithms.dijkstra import CapacityManager
        return CapacityManager(self.bucket_hours, self.planning_horizon)


def next_departure(service, ready_time):
    if service.departures is None:
        return ready_time
    index = bisect_left(service.departures, ready_time)
    return service.departures[index] if index < len(service.departures) else None


def next_feasible_departure(service, ready_time, demand, capacity_manager,
                            latest_departure=inf):
    """Wait for capacity, bounded by the deadline and planning horizon."""
    if demand > service.capacity:
        return None
    latest = min(latest_departure, capacity_manager.planning_horizon)
    if service.departures is None:
        departure = ready_time
        while departure <= latest:
            if capacity_manager.can_reserve(service, departure, demand):
                return departure
            departure = capacity_manager.next_bucket(departure)
        return None
    index = bisect_left(service.departures, ready_time)
    while index < len(service.departures):
        departure = service.departures[index]
        if departure > latest:
            break
        if capacity_manager.can_reserve(service, departure, demand):
            return departure
        index += 1
    return None


def print_service(services):
    for service in services:
        print(service)

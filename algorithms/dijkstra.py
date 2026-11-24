# Dijkstra's algorithm implementation for network - David

import heapq
from itertools import count
from math import floor, isfinite, nextafter
from generator import get_transfer_delays, next_departure, next_feasible_departure, travel_duration
from models.common import number

class CapacityManager:
    """Departure throughput per bucket; scheduled capacity per departure."""
    def __init__(self, bucket_hours=1.0, planning_horizon=336.0):
        from models.common import number
        self.bucket_hours = number("bucket_hours", bucket_hours, positive=True)
        self.planning_horizon = number("planning_horizon", planning_horizon, positive=True)
        self.reserved = {}

    def bucket_index(self, departure):
        return floor(nextafter(departure / self.bucket_hours, float("inf")))

    def next_bucket(self, departure):
        boundary = (self.bucket_index(departure) + 1) * self.bucket_hours
        return boundary if boundary > departure else nextafter(departure, float("inf"))

    def reservation_key(self, service, departure):
        if service.departures is None:
            return service.service_id, self.bucket_index(departure)
        return service.service_id, departure

    def remaining(self, service, departure):
        return service.capacity - self.reserved.get(self.reservation_key(service, departure), 0)

    def can_reserve(self, service, departure, demand):
        return (not isinstance(demand, bool) and isfinite(demand) and demand > 0 and isfinite(departure)
                and 0 <= departure <= self.planning_horizon
                and (service.departures is None or departure in service.departures)
                and self.remaining(service, departure) + 1e-9 >= demand)

    def reserve(self, service, departure, demand):
        return self.reserve_route([{"service": service, "departure": departure}], demand)

    def _requirements(self, path, demand):
        if isinstance(demand, bool) or not isfinite(demand) or demand <= 0:
            return None
        required = {}
        for leg in path:
            service, departure = leg["service"], leg["departure"]
            if (not isfinite(departure) or not 0 <= departure <= self.planning_horizon
                    or (service.departures is not None and departure not in service.departures)):
                return None
            key = self.reservation_key(service, departure)
            amount = required.get(key, (0, service.capacity))[0] + demand
            required[key] = amount, service.capacity
        return required

    def reserve_route(self, path, demand):
        required = self._requirements(path, demand)
        if required is None or any(self.reserved.get(k, 0) + v > cap + 1e-9 for k, (v, cap) in required.items()):
            return False
        for key, (amount, _) in required.items():
            self.reserved[key] = self.reserved.get(key, 0) + amount
        return True

    def release_route(self, path, demand):
        required = self._requirements(path, demand)
        if required is None or any(self.reserved.get(k, 0) + 1e-9 < v for k, (v, _) in required.items()):
            return False
        for key, (amount, _) in required.items():
            remaining = self.reserved[key] - amount
            if remaining > 1e-9:
                self.reserved[key] = remaining
            else:
                del self.reserved[key]
        return True

    def copy(self):
        other = CapacityManager(self.bucket_hours, self.planning_horizon)
        other.reserved = dict(self.reserved)
        return other


def time_dependant_dijkstra(network, origin, destination, start_time, deadline=float("inf"), demand=1, capacity_manager=None, allowed_modes = None):
    number("start_time", start_time)
    number("demand", demand, positive=True)
    if deadline != float("inf"):
        number("deadline", deadline)
    deadline = min(deadline, network.planning_horizon)
    if start_time > deadline:
        return None
    if capacity_manager is not None and (
        capacity_manager.bucket_hours != network.bucket_hours
        or capacity_manager.planning_horizon != network.planning_horizon
    ):
        raise ValueError("Capacity settings must match the network.")
    if origin not in network.adjacency or destination not in network.adjacency:
        return None

    # A* pruning with a reusable optimistic static travel-duration bound.
    # Incoming mode remains part of the state for correct transfer handling.
    lower_bounds = network.travel_lower_bounds(destination)
    if start_time + lower_bounds.get(origin, float("inf")) > deadline:
        return None

    # Tracks hub and incoming mode
    start_state = (origin, None)

    # initializes route using starting state and time
    arrival_times = {start_state: start_time}

    # retains route information by storing previous states
    previous = {}

    counter = count()

    pq = [(start_time + lower_bounds[origin], next(counter), start_time, start_state)]

    destination_state = None

    while pq:
        _, _, current_time, state = heapq.heappop(pq) # Get item at the front of the queue

        if current_time > arrival_times[state]: # Ignore hub where current time > arrival times
            continue

        current_hub, previous_mode = state

        if current_hub == destination: # check if we've made it to the destination node
            destination_state = state
            break

        for service in network.get_outgoing(current_hub): # checks all outgoing services from the current hub/node
            if allowed_modes is not None: # make sure that the mode of the service is compatible with the shipment
                if service.mode not in allowed_modes:
                    continue

            transfer_delay = get_transfer_delays(
                previous_mode,
                service.mode
            )

            ready_time = current_time + transfer_delay

            if capacity_manager is not None: # depending on if capacity is a concern, calls different functions for getting next departure
                departure = next_feasible_departure(
                    service, ready_time, demand, capacity_manager,
                    latest_departure=deadline - service.travel_time
                )
            else:
                departure = next_departure(service, ready_time)

            if departure is None:
                continue

            new_arrival = departure + travel_duration(service, departure)

            bound = lower_bounds.get(service.destination, float("inf"))
            if new_arrival + bound > deadline:
                continue

            next_state = (service.destination, service.mode)

            if new_arrival < arrival_times.get(next_state, float("inf")):
                # add the next state to the route and record the current state
                arrival_times[next_state] = new_arrival

                previous[next_state] = (
                    state,
                    service,
                    departure
                )

                heapq.heappush(pq, (new_arrival + bound, next(counter), new_arrival, next_state))

    if destination_state is None:
        return None

    path = []
    current = destination_state

    # Rebuilds the route used to get to the destination
    while current != start_state:
        previous_state, service, departure = previous[current]

        path.append({
            "service": service,
            "departure": departure,
            "arrival": departure + travel_duration(service, departure)
        })

        current = previous_state

    path.reverse()

    return {
        "path": path,
        "arrival_time": arrival_times[destination_state]
    }

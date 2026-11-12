# Dijkstra's algorithm implementation for network - David

import heapq
from itertools import count
from generator import *

class CapacityManager: # Handles capacity management for services
    def __init__(self):
        self.reserved = {}

    def remaining(self, service, departure): # returns remaining capacity of a service
        if service.departures is None:
            key = (service.service_id, None)
        else:
            key = (service.service_id, departure)

        used = self.reserved.get(key, 0)

        return service.capacity - used

    def can_reserve(self, service, departure, demand): # checks whether service has enough capacity
        return self.remaining(service, departure) >= demand

    def reserve(self, service, departure, demand): # books capacity once a shipment is assigned
        if not self.can_reserve(service, departure, demand):
            return False

        if service.departures is None:
            key = (service.service_id, None)
        else:
            key = (service.service_id, departure)

        self.reserved[key] = self.reserved.get(key, 0) + demand

        return True

def time_dependant_dijkstra(network, origin, destination, start_time, deadline=float("inf"), demand=1, capacity_manager=None, allowed_modes = None):
    if start_time > deadline or demand <= 0:
        return None

    # Tracks hub and incoming mode
    start_state = (origin, None)

    # initializes route using starting state and time
    arrival_times = {start_state: start_time}

    # retains route information by storing previous states
    previous = {}

    counter = count()

    pq = [(start_time, next(counter) ,start_state)] # Priority queue

    destination_state = None

    while pq:
        current_time, _, state = heapq.heappop(pq) # Get item at the front of the queue

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
                    service, ready_time, demand, capacity_manager
                )
            else:
                departure = next_departure(service, ready_time)

            if departure is None:
                continue

            new_arrival = departure + service.travel_time

            if new_arrival > deadline:
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

                heapq.heappush(pq, (new_arrival, next(counter), next_state))

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
            "arrival": departure + service.travel_time
        })

        current = previous_state

    path.reverse()

    return {
        "path": path,
        "arrival_time": arrival_times[destination_state]
    }
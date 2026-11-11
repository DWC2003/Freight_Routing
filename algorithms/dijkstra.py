# Dijkstra's algorithm implementation for network - David

import heapq
from generator import *

def time_dependant_dijkstra(network, origin, destination, start_time):
    arrival_times = {}

    previous = {}

    arrival_times[origin] = start_time

    pq = [{start_time,origin}]

    while pq:
        current_time, current_hub = heapq.heappop(pq)

        if current_time > arrival_times[current_hub]:
            continue

        if current_hub == destination:
            break

        for service in network.get_outgoing(current_hub):

            departure = next_departure(service, current_time)

            if departure is None:
                continue

            new_arrival = departure + service.travel_time

            neighbor = service.destination

            if new_arrival < arrival_times.get(neighbor, float("inf")):
                arrival_times[neighbor] = new_arrival

                previous[neighbor] = (
                    current_hub,
                    service,
                    departure
                )

                heapq.heappush(pq, (new_arrival, neighbor))

    if destination not in arrival_times:
        return None

    path = []
    current = destination

    while current != origin:
        previous_hub, service, departure = previous[current]

        path.append({
            "service": service,
            "departure": departure,
            "arrival": departure + service.travel_time
        })

        current = previous_hub

    path.reverse()

    return {
        "path": path,
        "arrival_time": arrival_times[destination]
    }
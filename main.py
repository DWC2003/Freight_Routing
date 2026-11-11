# Main file for running network generation and simulation - David

from generator import *
from algorithms.dijkstra import *

network = FreightNetwork()

network.add_service(Service(
    service_id="T1",
    origin="Atlanta",
    destination="Nashville",
    mode="truck",
    travel_time=4,
    cost=200,
    emissions=50,
    capacity=10,
    departures=None
))

network.add_service(Service(
    service_id="R1",
    origin="Nashville",
    destination="Chicago",
    mode="rail",
    travel_time=8,
    cost=150,
    emissions=20,
    capacity=30,
    departures=[6, 18, 30, 42]
))

network.add_service(Service(
    service_id="T2",
    origin="Atlanta",
    destination="Savannah",
    mode="truck",
    travel_time=4,
    cost=180,
    emissions=45,
    capacity=10,
    departures=None
))

result = time_dependant_dijkstra(
    network,
    "Atlanta",
    "Chicago",
    0
)

if result is not None:
    print("Arrival time:", result["arrival_time"])

    for leg in result["path"]:
        service = leg["service"]

        print(
            service.origin,
            "->",
            service.destination + " |",
            service.mode + " |",
            "Departure:", leg["departure"],
            "Arrival:", leg["arrival"]
        )
else:
    print("No feasible route found.")

#print_service(network.get_outgoing("Atlanta"))
#print_service(network.get_outgoing("Nashville"))

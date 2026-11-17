# Main file for running network generation and simulation - David
# Shipment and greedy-assignment example. All demo times are HOURS from time 0.

from generator import FreightNetwork, Service
from models.shipment import Shipment
from algorithms.dijkstra import CapacityManager
from algorithms.greedy import greedy_assign


def build_demo_network():
    network = FreightNetwork()

    # These are the three services from the original example.
    network.add_service(Service(
        service_id="T1", origin="Atlanta", destination="Nashville",
        mode="truck", travel_time=4, cost=200, emissions=50,
        capacity=10, departures=None,
    ))
    network.add_service(Service(
        service_id="R1", origin="Nashville", destination="Chicago",
        mode="rail", travel_time=8, cost=150, emissions=20,
        capacity=30, departures=[6, 18, 30, 42],
    ))
    network.add_service(Service(
        service_id="T2", origin="Atlanta", destination="Savannah",
        mode="truck", travel_time=4, cost=180, emissions=45,
        capacity=10, departures=None,
    ))

    # Complete the Savannah branch so it provides a slower alternative route.
    network.add_service(Service(
        service_id="T3", origin="Savannah", destination="Chicago",
        mode="truck", travel_time=28, cost=350, emissions=90,
        capacity=10, departures=None,
    ))
    return network


def build_demo_shipments():
    return [
        Shipment(shipment_id="S1", origin="Atlanta", destination="Chicago",
                 volume=6, start_time=0, deadline=40, priority=1),
        Shipment(shipment_id="S2", origin="Atlanta", destination="Chicago",
                 volume=6, start_time=0, deadline=30, priority=3),
        Shipment(shipment_id="S3", origin="Atlanta", destination="Chicago",
                 volume=4, start_time=0, deadline=30, priority=2),
        Shipment(shipment_id="S4", origin="Atlanta", destination="Chicago",
                 volume=5, start_time=0, deadline=40, priority=1),
    ]


def main():
    network = build_demo_network()
    shipments = build_demo_shipments()
    capacity = CapacityManager()
    assignments = greedy_assign(network, shipments, capacity, order="priority")

    for result in assignments:
        shipment = result["shipment"]
        print(f"\n{shipment.shipment_id} | priority={shipment.priority} | "
              f"volume={shipment.volume} | {result['status']}")

        if result["status"] != "assigned":
            print(f"  Reason: {result['reason']}")
            continue

        route = result["route"]
        print(f"  Arrival: {route['arrival_time']} | Deadline: {shipment.deadline}")
        for leg in route["path"]:
            service = leg["service"]
            print(f"  {service.origin} -> {service.destination} by {service.mode} "
                  f"({service.service_id}): {leg['departure']} -> {leg['arrival']}")

    assigned_count = sum(result["status"] == "assigned" for result in assignments)
    print(f"\nAssigned {assigned_count}/{len(shipments)} shipments.")
    print("Reserved capacity:", capacity.reserved)


if __name__ == "__main__":
    main()

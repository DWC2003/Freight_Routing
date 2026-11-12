# This file contains classes and functions pertaining to the generation of freight networks - David

from dataclasses import dataclass
from typing import Optional
from collections import defaultdict


# Time delays when transferring between modes
TRANSFER_DELAYS = {
    ("truck", "rail") : 3,
    ("rail", "truck") : 2,
    ("truck", "ship"): 4,
    ("ship", "truck"): 4,
    ("rail", "ship"): 5,
    ("ship", "rail"): 5
}

def get_transfer_delays(old_mode, new_mode):
    if old_mode is None:
        return 0

    if old_mode == new_mode:
        return 0

    return TRANSFER_DELAYS.get((old_mode, new_mode), 0)

# Service class represents a service used to transport shipments
@dataclass
class Service:
    service_id: str
    origin: str
    destination: str
    mode: str

    travel_time: float
    cost: float
    emissions: float
    capacity: int

    departures: Optional[list[float]] = None

# FreightNetwork class stores and retrieves outgoing transportation services
class FreightNetwork:
    def __init__(self):
        self.adjacency = defaultdict(list)

    def add_hub(self, hub):
        if hub not in self.adjacency:
            self.adjacency[hub] = []

    def add_service(self, service): # Takes O(1) time
        self.add_hub(service.origin)
        self.add_hub(service.destination)

        self.adjacency[service.origin].append(service)

    def get_outgoing(self, hub): # Takes O(1) time
        return self.adjacency.get(hub, [])

# Determines when a shipment can use a service by sorting the departures by arrival time and returning the first one
def next_departure(service, ready_time):
    if service.departures is None:
        return ready_time

    for departure in sorted(service.departures):
        if departure >= ready_time:
            return departure

    return None

def next_feasible_departure(service, ready_time, demand, capacity_manager):
    # continuously available transportation
    if service.departures is None:
        if capacity_manager.can_reserve(service, ready_time, demand):
            return ready_time
        return None

    #scheduled transportation

    for departure in sorted(service.departures):
        if departure < ready_time:
            continue

        if capacity_manager.can_reserve(service, departure, demand):
            return departure

    return None

# Prints details of services from a list
def print_service(services):
    for service in services:
        print(f"ID: {service.service_id} | Origin: {service.origin} | Destination: {service.destination} | Mode: {service.mode} | Travel Time: {service.travel_time} | Cost: {service.cost} | Emissions: {service.emissions} | Capacity: {service.capacity} | Departures: {service.departures} | END")
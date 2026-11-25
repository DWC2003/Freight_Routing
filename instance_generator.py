"""Seeded instances planted with a capacity-respecting reference solution."""
import random
from dataclasses import replace

from generator import (FreightNetwork, Service, get_transfer_delays,
                       next_feasible_departure, travel_duration)
from models.common import MODES, integer, number
from models.shipment import Shipment


def generate_instance(hub_count=500, link_count=5000, shipment_count=10000,
                      seed=42, bucket_hours=1.0, planning_horizon=336.0,
                      max_legs=4, deadline_slack=24.0, max_attempts_per_shipment=100):
    integer("hub_count", hub_count, minimum=2)
    integer("link_count", link_count, minimum=hub_count)
    integer("shipment_count", shipment_count, minimum=0)
    integer("max_legs", max_legs)
    integer("max_attempts_per_shipment", max_attempts_per_shipment)
    integer("seed", seed, minimum=0)
    number("deadline_slack", deadline_slack)
    rng = random.Random(seed)
    network = FreightNetwork(bucket_hours, planning_horizon)
    hubs = [f"H{i:04d}" for i in range(hub_count)]
    for hub in hubs:
        network.add_hub(hub)
    rates = {"truck": (80, 20), "rail": (40, 5), "air": (200, 80), "ship": (25, 3)}
    durations = {"truck": (1, 8), "rail": (3, 12), "air": (1, 3), "ship": (6, 24)}

    def add(origin, destination, mode, ring=False):
        travel = rng.randint(*durations[mode])
        departures = None
        if not ring and mode in {"rail", "ship"}:
            period = 6 if mode == "rail" else 12
            departures = list(range(rng.randrange(period), int(planning_horizon) + 1, period))
        cost, emissions = rates[mode]
        service = Service(f"L{len(network.services):05d}", origin, destination, mode,
                          travel, cost * travel, emissions * travel,
                          50 if ring else rng.randint(20, 80), departures)
        network.add_service(service)

    # A directed ring guarantees reachability; parallel services are intentional.
    for i, hub in enumerate(hubs):
        add(hub, hubs[(i + 1) % hub_count], "truck", ring=True)
    while len(network.services) < link_count:
        origin, destination = rng.sample(hubs, 2)
        add(origin, destination, rng.choice(MODES))

    capacity = network.new_capacity_manager()
    shipments, reference = [], []
    for index in range(shipment_count):
        for _ in range(max_attempts_per_shipment):
            origin = hub = rng.choice(hubs)
            start_time = rng.uniform(0, planning_horizon / 2)
            ready, previous = start_time, None
            volume = rng.randint(1, 5)
            visited, path = {hub}, []
            legs = rng.randint(1, min(max_legs, hub_count - 1))
            for _ in range(legs):
                options = [s for s in network.get_outgoing(hub) if s.destination not in visited]
                rng.shuffle(options)
                found = False
                for service in options:
                    earliest = ready + get_transfer_delays(previous, service.mode)
                    departure = next_feasible_departure(service, earliest, volume, capacity,
                                                        planning_horizon - service.travel_time)
                    if departure is None:
                        continue
                    arrival = departure + travel_duration(service, departure)
                    path.append({"service": service, "departure": departure, "arrival": arrival})
                    hub, ready, previous = service.destination, arrival, service.mode
                    visited.add(hub)
                    found = True
                    break
                if not found:
                    break
            if len(path) != legs:
                continue
            deadline = min(planning_horizon, ready + rng.uniform(0, deadline_slack))

            modes = {leg["service"].mode for leg in path}

            priority = rng.randint(1,3)
            allowed = modes if rng.random() < .25 else None

            preference_options = (sorted(allowed) if allowed is not None else MODES)
            preferred = rng.choice(preference_options) if rng.random() < .4 else None

            shipment = Shipment(
                f"S{index:06d}",
                origin,
                hub,
                volume,
                start_time,
                deadline,
                priority=priority,
                allowed_modes=allowed,
                preferred_mode=preferred
            )




            if capacity.reserve_route(path, volume):
                shipments.append(shipment)
                reference.append({"shipment": shipment, "status": "assigned",
                                  "route": {"path": path, "arrival_time": ready}, "reason": None})
                break
        else:
            raise RuntimeError(f"Could not plant shipment {index}; increase horizon/capacity or retry limit.")
    return network, shipments, reference


def stress_instance(network, shipments, capacity_factor=.5, deadline_factor=.5):
    """Controlled stress variant; feasibility is intentionally not guaranteed."""
    for name, value in (("capacity_factor", capacity_factor), ("deadline_factor", deadline_factor)):
        number(name, value, positive=True)
        if value > 1:
            raise ValueError(f"{name} must not exceed one.")
    stressed = FreightNetwork(network.bucket_hours, network.planning_horizon)
    for hub in network.adjacency:
        stressed.add_hub(hub)
    for service in network.services.values():
        stressed.add_service(replace(service, capacity=service.capacity * capacity_factor))
    demands = [replace(s, deadline=s.start_time + deadline_factor * (s.deadline - s.start_time))
               for s in shipments]
    return stressed, demands

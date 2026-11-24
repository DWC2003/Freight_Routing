# Main file for running network generation and simulation - David
# Shipment and greedy-assignment example. All demo times are HOURS from time 0.

from generator import FreightNetwork, Service
from models.shipment import Shipment
from algorithms.grasp import grasp_assign

# left over method for simple demo
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

# left over method for simple demo
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


def main(argv=None):
    """One command to load/generate an instance, optimize it, and export results."""
    import argparse
    from pathlib import Path
    from dataclasses import asdict
    from configuration import load_config
    from instance_generator import generate_instance, stress_instance
    from project_io import read_instance, write_instance, write_results
    from feasibility import feasibility_report
    from objective import normalize_weights

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=str(Path(__file__).with_name("config.json")))
    parser.add_argument("--demo", action="store_true", help="Run the original four-shipment example")
    parser.add_argument("--generate-only", action="store_true")
    parser.add_argument("--input-dir")
    parser.add_argument("--data-dir")
    parser.add_argument("--output-dir")
    parser.add_argument("--hubs", type=int)
    parser.add_argument("--links", type=int)
    parser.add_argument("--shipments", type=int)
    parser.add_argument("--iterations", type=int)
    parser.add_argument("--max-local-moves", type=int)
    args = parser.parse_args(argv)
    mapping = {"hubs": "hub_count", "links": "link_count", "shipments": "shipment_count"}
    overrides = {mapping.get(k, k): v for k, v in vars(args).items()
                 if k not in ("config", "demo", "generate_only") and v is not None}
    config = load_config(args.config, overrides)
    if args.demo and config["input_dir"] is not None:
        parser.error("--demo and --input-dir cannot be combined")
    weights = normalize_weights(config["weights"])
    config["weights"] = asdict(weights)
    reference = None
    if args.demo:
        network, shipments = build_demo_network(), build_demo_shipments()
        network.bucket_hours = config["capacity_bucket_hours"]
        network.planning_horizon = config["planning_horizon"]
    elif config["input_dir"] is not None:
        network, shipments = read_instance(config["input_dir"], config["capacity_bucket_hours"],
                                            config["planning_horizon"])
    else:
        names = ("hub_count", "link_count", "shipment_count", "seed", "planning_horizon",
                 "max_legs", "deadline_slack", "max_attempts_per_shipment")
        network, shipments, reference = generate_instance(
            **{name: config[name] for name in names}, bucket_hours=config["capacity_bucket_hours"])
        if not feasibility_report(network, reference, shipments)["complete"]:
            raise ValueError("Generated reference plan is invalid.")
        if config["scenario"] == "stress":
            network, shipments = stress_instance(network, shipments, config["capacity_factor"], config["deadline_factor"])
            reference = None
    if config["input_dir"] is None:
        write_instance(config["data_dir"], network, shipments, reference,
                       metadata={"seed": config["seed"], "scenario": "demo" if args.demo else config["scenario"]})
    if args.generate_only:
        print(f"Prepared {len(network.adjacency)} hubs, {len(network.services)} links, {len(shipments)} shipments.")
        return
    names = ("iterations", "alpha", "seed", "rcl_size", "max_no_improvement", "max_local_moves",
             "max_routes", "max_route_searches", "max_rebuild_shipments")
    result = grasp_assign(network, shipments, weights=weights, **{name: config[name] for name in names})
    write_results(config["output_dir"], network, shipments, result, config)
    print(f"Assigned {result['metrics']['assigned']}/{len(shipments)} shipments.")
    print(f"Baseline rank: {result['baseline_rank']} | GRASP rank: {result['rank']}")
    print(f"Runtime: {result['runtime']:.3f}s | Iterations: {result['iterations']} | {result['stop_reason']}")
    print(f"Results: {config['output_dir']}")


if __name__ == "__main__":
    main()

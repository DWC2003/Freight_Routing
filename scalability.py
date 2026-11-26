import subprocess
import sys
import json
import csv
from pathlib import Path

# Different workloads to test
shipment_counts = [1000, 2500, 5000, 7500, 10000]

root = Path(__file__).resolve().parent

experiment_folder = root / "out" / "scalability"
experiment_folder.mkdir(parents=True, exist_ok=True)

results = []

for count in shipment_counts:

    print(f"\nRunning experiment with {count} shipments...")

    output_dir = experiment_folder / str(count)
    data_dir = output_dir / "data"

    # Execute the freight routing project
    subprocess.run([
        sys.executable,
        "run_project.py",
        "--hubs", "500",
        "--links", "5000",
        "--shipments", str(count),
        "--iterations", "3",
        "--data-dir", str(data_dir),
        "--output-dir", str(output_dir)
    ], check=True, cwd=root)

    # Retrieve the results
    with open(output_dir / "metrics.json", "r") as file:
        data = json.load(file)

    results.append({
        "shipments": count,
        "runtime": data["runtime"],
        "baseline_objective": data["baseline_objective"],
        "grasp_objective": data["objective"],
        "assigned": data["metrics"]["assigned"],
        "unassigned": data["metrics"]["unassigned"],
        "iterations": data["iterations"]
    })

    print(f"Completed: {data['runtime']:.2f} seconds")

    # Save results after each completed experiment
    with open(experiment_folder / "scalability.csv",
              "w", newline="") as file:

        writer = csv.DictWriter(
            file,
            fieldnames=results[0].keys()
        )

        writer.writeheader()
        writer.writerows(results)

print("\nAll experiments completed!")
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter
from pathlib import Path
import pandas as pd
import json

output = Path("out/plots")
output.mkdir(parents=True, exist_ok=True)

algorithms = ["Priority Greedy", "GRASP"]

# Previous experiment results
scores = [16961953, 14940812]
runtimes = [4.431, 38.361]

# Graph 1: Objective score
from matplotlib.ticker import FuncFormatter

plt.figure(figsize=(8, 5))

bars = plt.bar(algorithms, scores,
               color=["steelblue", "seagreen"])

plt.title("Objective Score Comparison")
plt.ylabel("Weighted Score")

plt.gca().yaxis.set_major_formatter(
    FuncFormatter(lambda x, pos: f"{x/1000000:.1f}M")
)

plt.bar_label(bars, labels=[f"{s:,}" for s in scores],
              padding=5)

plt.ylim(0, max(scores) * 1.15)
plt.grid(axis="y", alpha=0.2)
plt.tight_layout()
plt.savefig(output / "score_comparison.png", dpi=300)
plt.show()

# Graph 2: Runtime
plt.figure()
plt.bar(algorithms, runtimes, color=["steelblue", "seagreen"])
plt.title("Runtime Comparison")
plt.ylabel("Execution Time (seconds)")
plt.tight_layout()
plt.savefig(output / "runtime_comparison.png")
plt.show()

# Graph 3: Transportation modes
plt.figure()
modes = ["Truck", "Rail", "Air", "Ship"]
counts = [16930, 15306, 1802, 626]

plt.bar(modes, counts)
plt.title("Transportation Mode Distribution")
plt.ylabel("Number of Route Legs")
plt.tight_layout()
plt.savefig(output / "mode_distribution.png")
plt.show()

with open("out/metrics.json", "r") as file:
    data = json.load(file)

assigned = data["metrics"]["assigned"]
unassigned = data["metrics"]["unassigned"]

plt.figure(figsize=(8, 5))

bars = plt.bar(
    ["Assigned", "Unassigned"],
    [assigned, unassigned],
    color=["seagreen", "firebrick"]
)

plt.bar_label(bars, padding=5)
plt.title("Shipment Assignment Feasibility")
plt.ylabel("Number of Shipments")
plt.ylim(0, (assigned + unassigned) * 1.15)
plt.grid(axis="y", alpha=0.2)
plt.tight_layout()

plt.savefig(output / "feasibility.png", dpi=300)
plt.show()

history = pd.read_csv("out/history.csv")

plt.figure(figsize=(8, 5))

plt.plot(
    history["iteration"],
    history["current_soft_score"],
    marker="o",
    linestyle="--",
    color="steelblue",
    label="Current Solution"
)

plt.plot(
    history["iteration"],
    history["best_soft_score"],
    marker="s",
    color="seagreen",
    label="Best Solution"
)

plt.title("GRASP Convergence Curve")
plt.xlabel("Iteration")
plt.ylabel("Weighted Objective Score")

plt.xticks(history["iteration"])

plt.gca().yaxis.set_major_formatter(
    FuncFormatter(lambda x, pos: f"{x/1000000:.2f}M")
)

plt.grid(alpha=0.3)
plt.legend()
plt.tight_layout()

plt.savefig(output / "cost_curve.png", dpi=300)
plt.show()

# GRAPH 6 - SCALABILITY ANALYSIS

scalability = pd.read_csv(
    "out/scalability/scalability.csv"
)

plt.figure(figsize=(8, 5))

plt.plot(
    scalability["shipments"],
    scalability["runtime"],
    marker="o",
    linewidth=2,
    color="steelblue"
)

for x, y in zip(
        scalability["shipments"],
        scalability["runtime"]
):
    plt.annotate(
        f"{y:.2f}s",
        (x, y),
        xytext=(0, 10),
        textcoords="offset points",
        ha="center"
    )

plt.title("Freight Routing Runtime Scalability")
plt.xlabel("Number of Shipments")
plt.ylabel("Execution Time (seconds)")

plt.xticks(scalability["shipments"])
plt.ylim(0, scalability["runtime"].max() * 1.20)
plt.grid(alpha=0.3)
plt.tight_layout()

plt.savefig(output / "scalability.png", dpi=300)
plt.show()

# GRAPH 7 - OPTIMIZATION CONSISTENCY

scalability["improvement"] = (
    (scalability["baseline_objective"]
     - scalability["grasp_objective"])
    / scalability["baseline_objective"]
) * 100

plt.figure(figsize=(8, 5))

bars = plt.bar(
    scalability["shipments"].astype(str),
    scalability["improvement"],
    color="seagreen"
)

plt.bar_label(bars, fmt="%.2f%%", padding=5)

plt.title("GRASP Improvement Across Workloads")
plt.xlabel("Number of Shipments")
plt.ylabel("Objective Score Improvement (%)")
plt.ylim(0, 15)

plt.grid(axis="y", alpha=0.3)
plt.tight_layout()

plt.savefig(output / "optimization_consistency.png",
            dpi=300)
plt.show()
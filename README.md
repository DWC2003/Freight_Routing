# Time-dependent multimodal freight routing

Python 3.10+; standard library only. Times are hours from time zero.

## Run

```powershell
python run_project.py
```

The default config generates 500 hubs, 5,000 services, and 10,000 shipments with
seed 42, then runs three GRASP iterations. Runtime depends on the machine and
search settings; inspect the exported runtime and search counters.

For a quick check:

```powershell
python run_project.py --demo
python run_project.py --hubs 20 --links 80 --shipments 100 --iterations 2
python run_project.py --generate-only
python run_project.py --input-dir data
python -B -m unittest discover -s tests -v
```

Both `main.py` and `run_project.py` accept these options. `--config` selects a JSON
file; paths resolve relative to that file. `--data-dir` and `--output-dir` override
locations. Use a separate output directory to preserve earlier runs.

## Models and objective

- Hubs have directed parallel services. A ring guarantees generated connectivity.
- Rail/ship departures are explicitly scheduled; truck/air are continuous.
  Travel durations are fixed, not rush-hour profiles. The common duration helper
  is used in generation, routing and validation.
- Continuous capacity is departure throughput per configurable time bucket:
  capacity 10 with one-hour buckets permits 10 units in [0,1), another 10 in [1,2),
  etc. It is not concurrent road occupancy or a returning-vehicle fleet model.
  Scheduled services have independent capacity for each departure.
- Every planner and validator obtains capacity settings from the network. Routing
  can wait for a later bucket and is bounded by the planning horizon and deadline.
- Shipments are indivisible. Allowed modes are hard restrictions (`null` allows
  all; an empty array allows none). A preferred mode is a soft preference.
- Mode names normalize case and `sea` to `ship`. All mode changes have explicit
  transfer delays in `generator.py`.
- Service cost/emissions are per-shipment totals. Elapsed time includes initial
  waiting and transfers; transfers count mode changes. A mode mismatch is one leg
  whose mode differs from a shipment's preferred mode.
- Solutions minimize `(unassigned_count, weighted_soft_score)` lexicographically.
  Soft score weights cost, elapsed time, transfers, emissions and mode mismatches.
  A legacy weighted score including an unassigned penalty is exported for
  comparison but is NOT used to choose a solution. It can increase when coverage
  improves; plot coverage alongside soft score or compare exported rank tuples.

## Search and reproducibility

Greedy earliest-arrival routing provides the incumbent. The pathfinder retains
its original function name but now uses A* ordering with cached reverse static
travel-duration lower bounds. Ignoring schedules, capacity and transfers makes
these bounds admissible; deadline pruning uses the same bounds. GRASP shuffles shipments
within priority tiers, computes each shipment's alternatives once, and chooses a
route using a score-based RCL. Alpha zero retains minimum-score ties; alpha one
allows every generated route. Explicit `rcl_size` overrides the threshold.
Alternative generation bounds both distinct routes and Dijkstra calls and tracks
visited exclusion sets. It does not enumerate all paths or all later departures
on the same service.

Local search samples reroutes, pair repairs and swaps in bounded windows.
`max_local_moves` is a shared per-iteration attempt budget, including failed
moves; `max_rebuild_shipments` bounds each swapped window. The iteration and
stagnation limits are not hard wall-clock guarantees. Search counters and full
history are exported. A fixed seed reproduces decisions; timing varies.

## Data and outputs

`data/` contains `hubs.csv`, `links.csv`, `shipments.csv`, `instance.json`, and a
`reference_routes.csv` for generated feasible instances. The reference is planted
using a separate reservation ledger, checked independently, and never supplied to
the optimizer. Generation retries are bounded. Set `scenario` to `stress` to
reduce capacities/deadlines; the stress instance has no feasibility guarantee or
reference file. CSV schedules/restrictions are JSON arrays; modes use canonical
names. `instance.json` preserves bucket/horizon settings, which are checked when
loading.

`out/` contains routes, unassigned reasons, history (CSV and JSON), metrics with
parameters/baseline/ranks/search counters, and an independent feasibility report.
An empty route is valid only at the same origin/destination. Route CSV imports
resolve canonical service objects and validate coverage and feasibility.

Formal experiments, plots, team roles, and the final methods document remain
separate reporting work.

# Real-Time Resilience Monitoring Backend (Phase 89)

`backend/simulation/resilience_monitor.py` (`ResilienceMonitor`, `ResilienceMonitorDaemon`) turns live twin state into
Phase 62 resilience indicators and alerts on threshold crossings. Built and measured; **not wired into the pipeline**,
no API route; alerts go to memory, callbacks and an optional JSONL file.

## Design
- **State reading** (default): `connectivity_ratio` and `reachable_node_ratio` of the OBSERVED topology against a healthy
  reference (first reading, or supplied). Phase 62 only accepts injected `FailureScenario`s, so a real outage in the live
  graph needs the same two formulas over reference -> live; a unit test checks they equal
  `compute_resilience_indicators` when live = a scenario's post-failure graph. Nodes missing from live count as unreachable.
- **Sweep reading** (optional, `sweep=True`): every single node/edge failure of the live graph through the real
  `run_failure_propagation_pipeline` + `compute_resilience_indicators` (all six indicators). Risk findings, not outages.
- **Rules** (`AlertRule`: indicator, op lt/gt/is_false/nonempty, threshold, severity, scope, clear margin). Defaults are
  PROVISIONAL: `connectivity_low` (< 0.8, critical), `reachable_nodes_low` (< 0.8, warning); sweep: `spof_connectivity`
  (< 0.5), `spof_no_alternate_path`.
- **Alerts** are edge-triggered per (rule, scope): `fired` once on crossing, silent while breached, `resolved` when the
  value clears threshold + margin (or the scope disappears).
- **Daemon**: latest-wins evaluator thread; skips the same twin object; `min_interval`; errors recorded, monitoring
  continues. Hook to Phase 88 with `TwinSyncDaemon(..., on_sync=lambda r: daemon.notify(r.twin))`.

## Measured (`scripts/run_resilience_monitor_benchmark.py`; 4 topologies x 2 seeds x {hub, leaf} = 16 cases)
Controlled failure = a node's traffic removed from the capture, new snapshot, synced through the Phase 88 daemon, then
restored. Expected outcome computed independently from the healthy and failed graphs.
- Healthy state: 0 false alerts. Alert fired iff the independent ratio was < 0.8: 16/16 agree (6 crossings expected,
  6 detected; the other 10 stayed at 0.80-0.92 and correctly did not fire). Alert value equals the independent value
  6/6; all alerts in the JSONL file 16/16; all 6 resolved after restoration.
- Latency, failed-snapshot submit to alert observed (includes twin sync): median 0.01 s, max 0.04 s (these captures are small).
- What-if sweep cost per evaluation: small 5 scenarios 0.01 s; multi_service 21 scenarios 0.10 s; large 44 scenarios
  0.58 s (~13 ms/scenario); it grows with nodes + edges and reruns the whole pipeline each time. On the healthy graphs
  the sweep raises 6/22/12 alerts: these are real single points of failure / no-alternate-path findings, so sweep rules
  are noisy by nature and off by default.

## Limits
"Hub" is highest observed degree, not necessarily a cut vertex, so several failures do not cross the threshold. Thresholds
are uncalibrated. Only topology-derived indicators are monitored live; latency/loss/service state are not. Single
evaluator thread, latest-wins (an intermediate twin can be skipped), no persistence of monitor state, in-process only.

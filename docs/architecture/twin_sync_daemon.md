# Continuous Digital-Twin Synchronization Daemon (Phase 88)

`backend/digital_twin/daemon.py` (`TwinSyncDaemon`) is a long-running, in-process worker that applies Phase 58's
`sync_digital_twin` (unchanged) as snapshots arrive. Built and measured; **not wired into the pipeline**, no API route,
no persistence.

## Design
- `submit(snapshot, fingerprints)` feeds a **bounded** queue. Backpressure policy per daemon: `block` (wait, optional
  timeout) or `reject` (return False at once). Refusals are counted (`rejected_full`), never silent.
- **Rate limit**: token bucket (`max_syncs_per_second`, `burst`), injectable clock/sleep.
- **Coalescing** (optional): everything queued when the worker wakes is folded into one sync to the newest snapshot;
  fingerprints merge newest-wins per `(node_id, window)`. The twin reached is the same; the `structural_changes` of the
  skipped hops are not reported (`stats.coalesced` counts them).
- A failing sync is recorded (`stats.errors_detail`) and the daemon continues on its last good twin; that batch is
  not retried. Snapshots older than the last accepted one are rejected (`rejected_out_of_order`).
- `stop(drain=True)` finishes queued work; `drain=False` discards it (`discarded_on_stop`).

## Measured (`scripts/run_twin_sync_daemon_benchmark.py`; small / multi_service / large x 2 seeds x 4 configs)
- **Equivalence**: 8-snapshot sequences (fingerprints supplied per snapshot). Final daemon twin equals a manual chain
  of on-demand `sync_digital_twin` calls in **24/24** runs (topology, dependencies, history, fingerprints, snapshot;
  only `generated_at` ignored), and is consistent with a direct `build_digital_twin` at the last snapshot in 24/24.
- **Backpressure**: queue depth never exceeded its bound (24/24). Under `reject` the producer was refused 88-642
  times before all snapshots were accepted (sync is the bottleneck).
- **Rate limit**: real-time, 8 syncs (small): cap 1/s -> 1.1/s, 2/s -> 2.1/s, 3/s -> 2.9/s (the count includes the
  first, unthrottled sync). Unlimited throughput is ~3.6 syncs/s there, so caps above that do not bind.
- **Cost, honestly**: a sync rebuilds the whole twin (Phase 58 by design), so it does not scale down. Large topology:
  sync median ~1.9-2.3 s, max ~2.6 s; submit-to-applied latency median ~8 s when snapshots are submitted back to
  back (queueing). Throughput 0.4-0.5 syncs/s there. Coalescing cuts syncs 7 -> 2 with the same final twin.

## Limits
Single worker, single machine, in-process; memory of `changes` (per-sync results) is unbounded; a failed batch's
fingerprints are lost; wall-clock timings were taken on a shared machine; it inherits Phase 58's full-rebuild cost.

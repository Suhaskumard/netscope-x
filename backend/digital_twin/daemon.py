"""Continuous Digital-Twin Synchronization Daemon (spec addendum Phase 88).

A long-running, in-process service that applies Phase 58's `sync_digital_twin` as new snapshots arrive. It adds no
new inference: every twin it holds was produced by `sync_digital_twin` itself.

- Bounded input queue with an explicit backpressure policy: "block" (submit waits, optionally with a timeout) or
  "reject" (submit returns False at once). A refused submission is counted, never silently dropped.
- Token-bucket rate limit on syncs per second (injectable clock/sleep so it is testable without real waiting).
- Optional coalescing: if several submissions are queued when the worker wakes, it syncs once to the newest
  snapshot and merges the fingerprints (newest wins per (node_id, window), matching `sync_digital_twin`). The twin
  reached is the same as syncing step by step; only the `structural_changes` of the skipped hops are not reported.
- A failing sync is recorded and the daemon keeps running on its last good twin (the failed batch is not retried).

Limits: single worker thread, in-process, no persistence; snapshots must be submitted in `captured_at` order (an
older one is rejected and counted).

Never imports `simulator.ground_truth` (spec §4).
"""

from __future__ import annotations

import queue
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from backend.app.models.behavior import BehavioralFingerprint
from backend.app.models.snapshot import NetworkSnapshot
from backend.digital_twin.sync import TwinSyncResult, sync_digital_twin
from backend.digital_twin.twin import DigitalTwin

POLICIES = ("block", "reject")


class TokenBucket:
    """Classic token bucket: `rate` tokens/second, up to `burst` stored. `acquire` blocks (via `sleep`) until a
    token is available."""

    def __init__(
        self,
        rate: float,
        burst: int = 1,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if rate <= 0 or burst < 1:
            raise ValueError("rate must be > 0 and burst >= 1")
        self.rate, self.burst, self._clock, self._sleep = rate, burst, clock, sleep
        self._tokens = float(burst)
        self._last = clock()

    def acquire(self) -> None:
        while True:
            now = self._clock()
            self._tokens = min(float(self.burst), self._tokens + (now - self._last) * self.rate)
            self._last = now
            if self._tokens >= 1.0:
                self._tokens -= 1.0
                return
            self._sleep((1.0 - self._tokens) / self.rate)


@dataclass
class DaemonStats:
    submitted: int = 0  # accepted into the queue
    rejected_full: int = 0  # refused: queue full (reject policy, or block policy timed out)
    rejected_out_of_order: int = 0
    synced: int = 0  # sync_digital_twin calls that succeeded
    coalesced: int = 0  # queued submissions folded into a later sync (not synced on their own)
    errors: int = 0
    discarded_on_stop: int = 0
    max_queue_depth: int = 0
    latencies_s: List[float] = field(default_factory=list)  # oldest submit in the batch -> twin updated
    sync_times_s: List[float] = field(default_factory=list)  # wall time inside sync_digital_twin
    errors_detail: List[str] = field(default_factory=list)


@dataclass
class _Item:
    snapshot: NetworkSnapshot
    fingerprints: List[BehavioralFingerprint]
    submitted_at: float


class TwinSyncDaemon:
    def __init__(
        self,
        root: Path,
        twin: DigitalTwin,
        *,
        max_queue: int = 8,
        policy: str = "block",
        max_syncs_per_second: Optional[float] = None,
        burst: int = 1,
        coalesce: bool = True,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        sync_kwargs: Optional[Dict[str, Any]] = None,
        on_sync: Optional[Callable[[TwinSyncResult], None]] = None,
    ) -> None:
        if policy not in POLICIES:
            raise ValueError(f"policy must be one of {POLICIES}")
        if max_queue < 1:
            raise ValueError("max_queue must be >= 1")
        self._root = root
        self._twin = twin
        self._policy = policy
        self._coalesce = coalesce
        self._clock = clock
        self._sync_kwargs = dict(sync_kwargs or {})
        self._on_sync = on_sync
        self._bucket = (
            TokenBucket(max_syncs_per_second, burst, clock, sleep) if max_syncs_per_second is not None else None
        )
        self._queue: "queue.Queue[_Item]" = queue.Queue(maxsize=max_queue)
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._last_accepted = twin.snapshot.captured_at
        self.stats = DaemonStats()
        self.changes: List[TwinSyncResult] = []  # per-sync results, in order

    # -- lifecycle -----------------------------------------------------------------------------------------
    def start(self) -> None:
        if self._thread is not None:
            raise RuntimeError("daemon already started")
        self._thread = threading.Thread(target=self._run, name="twin-sync-daemon", daemon=True)
        self._thread.start()

    def stop(self, drain: bool = True, timeout: Optional[float] = None) -> None:
        """Stops the worker. `drain=True` first processes everything already queued; otherwise queued items are
        discarded (counted in `stats.discarded_on_stop`)."""
        if drain and self._thread is not None:
            self._join_queue(timeout)
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout)
        while True:
            try:
                self._queue.get_nowait()
            except queue.Empty:
                break
            self.stats.discarded_on_stop += 1
            self._queue.task_done()

    def wait_idle(self, timeout: Optional[float] = None) -> bool:
        """Blocks until every accepted submission has been processed. False on timeout."""
        return self._join_queue(timeout)

    def _join_queue(self, timeout: Optional[float]) -> bool:
        deadline = None if timeout is None else time.monotonic() + timeout
        while self._queue.unfinished_tasks:
            if deadline is not None and time.monotonic() >= deadline:
                return False
            time.sleep(0.001)
        return True

    # -- input ---------------------------------------------------------------------------------------------
    def submit(
        self,
        snapshot: NetworkSnapshot,
        fingerprints: Optional[List[BehavioralFingerprint]] = None,
        timeout: Optional[float] = None,
    ) -> bool:
        """Queues a snapshot. True if accepted. False if refused (queue full under "reject", `timeout` elapsed
        under "block", or the snapshot is older than the last accepted one)."""
        item = _Item(snapshot, list(fingerprints or []), self._clock())
        with self._lock:
            if snapshot.captured_at < self._last_accepted:
                self.stats.rejected_out_of_order += 1
                return False
            self._last_accepted = snapshot.captured_at
        try:
            if self._policy == "reject":
                self._queue.put_nowait(item)
            else:
                self._queue.put(item, timeout=timeout)
        except queue.Full:
            with self._lock:
                self.stats.rejected_full += 1
            return False
        with self._lock:
            self.stats.submitted += 1
            self.stats.max_queue_depth = max(self.stats.max_queue_depth, self._queue.qsize())
        return True

    # -- state ---------------------------------------------------------------------------------------------
    @property
    def twin(self) -> DigitalTwin:
        with self._lock:
            return self._twin

    # -- worker --------------------------------------------------------------------------------------------
    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                first = self._queue.get(timeout=0.02)
            except queue.Empty:
                continue
            batch = [first]
            if self._coalesce:
                while True:
                    try:
                        batch.append(self._queue.get_nowait())
                    except queue.Empty:
                        break
            try:
                self._process(batch)
            finally:
                for _ in batch:
                    self._queue.task_done()

    def _process(self, batch: List[_Item]) -> None:
        if self._bucket is not None:
            self._bucket.acquire()
        newest = batch[-1].snapshot
        merged: Dict[Tuple[str, Any], BehavioralFingerprint] = {}
        for item in batch:
            for fp in item.fingerprints:
                merged[(fp.node_id, fp.window)] = fp  # later submission replaces earlier
        started = time.perf_counter()
        try:
            result = sync_digital_twin(
                self._root, self._twin, newest, list(merged.values()) or None, **self._sync_kwargs
            )
        except Exception as exc:  # noqa: BLE001 - keep the daemon alive on its last good twin
            with self._lock:
                self.stats.errors += 1
                self.stats.errors_detail.append(f"{type(exc).__name__}: {exc}")
            return
        elapsed = time.perf_counter() - started
        with self._lock:
            self._twin = result.twin
            self.stats.synced += 1
            self.stats.coalesced += len(batch) - 1
            self.stats.sync_times_s.append(elapsed)
            self.stats.latencies_s.append(self._clock() - batch[0].submitted_at)
            self.changes.append(result)
        if self._on_sync is not None:
            self._on_sync(result)


def twin_state_equal(a: DigitalTwin, b: DigitalTwin) -> bool:
    """Equality of everything a twin *knows*, ignoring only `generated_at` (a wall-clock build stamp)."""
    return (
        a.capture_id == b.capture_id
        and a.snapshot == b.snapshot
        and a.topology == b.topology
        and a.behavioral_fingerprints == b.behavioral_fingerprints
        and a.history == b.history
        and a.dependencies == b.dependencies
    )

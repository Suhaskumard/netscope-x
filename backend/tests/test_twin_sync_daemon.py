"""Phase 88 digital-twin sync daemon tests (pure, no Docker)."""

from __future__ import annotations

import threading
from datetime import timedelta
from pathlib import Path

import pytest

from backend.digital_twin.daemon import TokenBucket, TwinSyncDaemon, twin_state_equal
from backend.digital_twin.twin import build_digital_twin
from experiments import twin_sync_daemon_benchmark as B


@pytest.fixture(scope="module")
def seq(tmp_path_factory):
    return B.build_sequence(tmp_path_factory.mktemp("daemon") / "artifacts", "small", 42, snapshots=6)


def _daemon(seq, **kw):
    twin0 = build_digital_twin(seq.root, B.CAPTURE, seq.snapshots[0], seq.fingerprints[0])
    return TwinSyncDaemon(seq.root, twin0, **kw)


def test_final_twin_matches_manual_chain_for_every_config(seq):
    manual = B.manual_chain(seq)
    for _, policy, coalesce, rate, max_queue in B.CONFIGS:
        twin, st, _, _ = B.run_daemon(seq, policy, coalesce, rate, max_queue)
        assert twin_state_equal(twin, manual)
        assert st.errors == 0 and st.max_queue_depth <= max_queue
        assert st.synced + st.coalesced == len(seq.snapshots) - 1


def test_token_bucket_spaces_acquires_with_fake_clock():
    now = [0.0]
    slept = []

    def sleep(s):
        slept.append(s)
        now[0] += s

    bucket = TokenBucket(rate=10.0, burst=2, clock=lambda: now[0], sleep=sleep)
    for _ in range(5):
        bucket.acquire()
    assert len(slept) == 3 and all(abs(s - 0.1) < 1e-9 for s in slept)  # 2 burst, then one per 0.1 s
    assert now[0] == pytest.approx(0.3)


def test_reject_policy_refuses_when_queue_full_and_counts(seq):
    d = _daemon(seq, max_queue=2, policy="reject")  # worker not started: nothing drains
    assert d.submit(seq.snapshots[1]) and d.submit(seq.snapshots[2])
    assert d.submit(seq.snapshots[3]) is False
    assert d.stats.submitted == 2 and d.stats.rejected_full == 1 and d.stats.max_queue_depth == 2
    d.stop(drain=False)
    assert d.stats.discarded_on_stop == 2


def test_block_policy_times_out_when_full(seq):
    d = _daemon(seq, max_queue=1, policy="block")
    assert d.submit(seq.snapshots[1])
    assert d.submit(seq.snapshots[2], timeout=0.05) is False
    assert d.stats.rejected_full == 1
    d.stop(drain=False)


def test_block_policy_waits_then_succeeds_once_worker_drains(seq):
    d = _daemon(seq, max_queue=1, policy="block", coalesce=False)
    assert d.submit(seq.snapshots[1])
    result = []
    t = threading.Thread(target=lambda: result.append(d.submit(seq.snapshots[2], timeout=5.0)))
    t.start()
    d.start()  # now something drains the queue
    t.join(10)
    d.stop(drain=True, timeout=30)
    assert result == [True] and d.stats.synced == 2


def test_out_of_order_snapshot_is_rejected(seq):
    d = _daemon(seq, max_queue=4)
    assert d.submit(seq.snapshots[3])
    assert d.submit(seq.snapshots[2]) is False
    assert d.stats.rejected_out_of_order == 1
    d.stop(drain=False)


def test_coalescing_merges_fingerprints_newest_wins(seq):
    d = _daemon(seq, max_queue=8, coalesce=True)
    for snap, fp in zip(seq.snapshots[1:], seq.fingerprints[1:]):
        assert d.submit(snap, fp)
    d.start()  # everything is already queued: one coalesced sync
    d.stop(drain=True, timeout=30)
    assert d.stats.synced == 1 and d.stats.coalesced == len(seq.snapshots) - 2
    assert twin_state_equal(d.twin, B.manual_chain(seq))


def test_failing_sync_keeps_daemon_alive_on_last_good_twin(seq, monkeypatch):
    import backend.digital_twin.daemon as mod

    real = mod.sync_digital_twin
    calls = {"n": 0}

    def flaky(*a, **k):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("boom")
        return real(*a, **k)

    monkeypatch.setattr(mod, "sync_digital_twin", flaky)
    d = _daemon(seq, max_queue=4, coalesce=False)
    d.start()
    d.submit(seq.snapshots[1], seq.fingerprints[1])
    d.wait_idle(30)
    assert d.stats.errors == 1 and d.twin.snapshot == seq.snapshots[0]
    d.submit(seq.snapshots[2], seq.fingerprints[2])
    d.stop(drain=True, timeout=30)
    assert d.stats.synced == 1 and d.twin.snapshot == seq.snapshots[2]
    assert "RuntimeError: boom" in d.stats.errors_detail[0]


def test_rate_limit_throttles_real_syncs(seq):
    d = _daemon(seq, max_queue=8, coalesce=False, max_syncs_per_second=20.0)
    d.start()
    for snap, fp in zip(seq.snapshots[1:], seq.fingerprints[1:]):
        d.submit(snap, fp)
    d.stop(drain=True, timeout=30)
    assert d.stats.synced == len(seq.snapshots) - 1
    # 5 syncs at 20/s, burst 1: the last one cannot be applied sooner than 4 x 50 ms after the first token
    assert d.stats.latencies_s[-1] >= (len(seq.snapshots) - 2) / 20.0 * 0.9


def test_start_twice_and_bad_config_raise(seq):
    d = _daemon(seq)
    d.start()
    with pytest.raises(RuntimeError):
        d.start()
    d.stop()
    with pytest.raises(ValueError):
        _daemon(seq, policy="nope")
    with pytest.raises(ValueError):
        _daemon(seq, max_queue=0)

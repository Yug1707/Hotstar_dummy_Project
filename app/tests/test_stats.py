import json
import os
import time

import pytest

import stats
import work


def test_rps_counts_arrivals_over_complete_seconds():
    s = stats.Stats()
    t0 = 1_000_000.0
    for sec in range(10):
        for _ in range(50):
            s.on_arrival(now=t0 + sec + 0.5)
    assert s.snapshot(now=t0 + 10.2)["rps"] == pytest.approx(50.0)


def test_rps_ignores_current_partial_second():
    s = stats.Stats()
    t0 = 2_000_000.0
    for _ in range(100):
        s.on_arrival(now=t0 + 0.1)
    assert s.snapshot(now=t0 + 0.5)["rps"] == 0.0
    assert s.snapshot(now=t0 + 1.5)["rps"] == pytest.approx(10.0)


def test_arrivals_differ_from_completions_under_saturation():
    s = stats.Stats()
    t0 = 3_000_000.0
    for sec in range(10):
        for _ in range(100):
            s.on_arrival(now=t0 + sec + 0.1)
        for _ in range(60):
            s.on_done(0.05, 200, now=t0 + sec + 0.2)
    snap = s.snapshot(now=t0 + 10.5)
    assert snap["rps"] == pytest.approx(100.0)
    assert snap["rps_completed"] == pytest.approx(60.0)


def test_p95_window():
    s = stats.Stats()
    now = time.time()
    for i in range(100):
        s.on_done((i + 1) / 1000, 200, now=now)  # 1..100 ms
    s.on_done(5.0, 200, now=now - 60)  # outside the window, ignored
    assert 90 <= s.p95_ms(now) <= 100


def test_errors_counted():
    s = stats.Stats()
    s.on_done(0.01, 500)
    s.on_done(0.01, 200)
    assert s.errors_total == 1


def test_aggregate_sums_other_worker_snapshots(stats_dir):
    now = time.time()
    other = {"pid": 999_999, "ts": now, "rps": 40.0, "rps_completed": 39.0, "in_flight": 3, "p95_ms": 900.0,
             "active_viewers": 10, "shed_total": 2, "rate_limited_total": 0, "errors_total": 0}  # fmt: skip
    stale = dict(other, pid=999_998, ts=now - 30, rps=1000.0)
    for snap in (other, stale):
        with open(os.path.join(stats_dir, f"streamlite-{snap['pid']}.json"), "w") as f:
            json.dump(snap, f)
    try:
        agg = stats.aggregate(now)
        own = stats.STATS.snapshot(now)
        assert agg["workers"] == 2  # own + fresh other; stale one dropped
        assert agg["rps"] == pytest.approx(own["rps"] + 40.0)
        assert agg["p95_ms"] >= 900.0
        assert agg["shed_total"] == own["shed_total"] + 2
    finally:
        for pid in (999_999, 999_998):
            os.remove(os.path.join(stats_dir, f"streamlite-{pid}.json"))


def test_fake_score_deterministic_per_bucket():
    assert stats.fake_score(now=1000.0) == stats.fake_score(now=1004.9)
    assert stats.fake_score(now=1000.0) != stats.fake_score(now=1005.0)


def test_work_iterations_scale(cfg):
    cfg(work_scale=2.0)
    assert work.iterations("reco") == 2 * work.ITER["reco"]
    cfg(work_scale=0.000001)
    assert work.iterations("state") == 1


@pytest.mark.slow
def test_work_burn_scales_with_work_scale(cfg):
    def timed(scale):
        cfg(work_scale=scale)
        t = time.perf_counter()
        for _ in range(5):
            work.burn("critical")
        return time.perf_counter() - t

    assert timed(2.0) >= 1.6 * timed(1.0)

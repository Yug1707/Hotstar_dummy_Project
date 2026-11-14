"""Request statistics for /internal/stats, the proactive scaler and the dashboard (plan §4.4).

Key design points
- ``rps`` counts **arrivals** (taken in the middleware before the thread-pool queue), so a saturated
  instance still reports the offered load, not its capacity (fix F5).
- Each worker process writes a snapshot file to STATS_DIR once per second; ``aggregate()`` sums all
  fresh snapshots, so running ``uvicorn --workers 2`` keeps the endpoint correct (fix F13).
"""

from __future__ import annotations

import glob
import json
import os
import statistics
import threading
import time
from collections import deque

import psutil

import config

WINDOW_S = 10  # sliding window for rps and p95
VIEWER_TTL_S = 30  # a viewer counts as active for 30 s after its last heartbeat
SNAPSHOT_MAX_AGE_S = 3.0


class _SecondBuckets:
    """Ring of 1-second counters; rate() averages the last WINDOW_S *complete* seconds."""

    def __init__(self) -> None:
        self._counts = [0] * WINDOW_S
        self._secs = [-1] * WINDOW_S

    def add(self, now: float) -> None:
        s = int(now)
        i = s % WINDOW_S
        if self._secs[i] != s:
            self._secs[i] = s
            self._counts[i] = 0
        self._counts[i] += 1

    def rate(self, now: float) -> float:
        cur = int(now)
        total = sum(c for c, s in zip(self._counts, self._secs, strict=True) if cur - WINDOW_S <= s < cur)
        return total / WINDOW_S


class Stats:
    def __init__(self) -> None:
        self.started = time.time()
        self.inflight = 0  # changed only from the event loop (async middleware)
        self.shed_total = 0
        self.rate_limited_total = 0
        self.errors_total = 0
        self.cpu_percent = 0.0  # system-wide, sampled once per second by the writer thread
        self._lock = threading.Lock()
        self._arrivals = _SecondBuckets()
        self._completions = _SecondBuckets()
        self._lat: deque[tuple[float, float]] = deque(maxlen=20_000)  # (t_end, duration_s)
        self._viewers: dict[int, float] = {}
        self._last_prune = 0.0

    # ---- hooks called by main.py -------------------------------------------------------------
    def on_arrival(self, now: float | None = None) -> None:
        with self._lock:
            self._arrivals.add(now or time.time())

    def on_done(self, duration_s: float, status: int, now: float | None = None) -> None:
        now = now or time.time()
        with self._lock:
            self._completions.add(now)
            self._lat.append((now, duration_s))
            if status >= 500:
                self.errors_total += 1

    def on_error(self) -> None:
        with self._lock:
            self.errors_total += 1

    def on_shed(self) -> None:
        with self._lock:
            self.shed_total += 1

    def on_rate_limited(self) -> None:
        with self._lock:
            self.rate_limited_total += 1

    def viewer_seen(self, user_id: int, now: float | None = None) -> None:
        now = now or time.time()
        with self._lock:
            self._viewers[user_id] = now
            if now - self._last_prune > 10:
                cutoff = now - VIEWER_TTL_S
                self._viewers = {u: t for u, t in self._viewers.items() if t >= cutoff}
                self._last_prune = now

    # ---- reads -------------------------------------------------------------------------------
    def p95_ms(self, now: float | None = None) -> float:
        now = now or time.time()
        with self._lock:
            durs = [d for t, d in self._lat if t >= now - WINDOW_S]
        if not durs:
            return 0.0
        if len(durs) == 1:
            return round(durs[0] * 1000, 2)
        return round(statistics.quantiles(durs, n=20)[-1] * 1000, 2)

    def active_viewers(self, now: float | None = None) -> int:
        now = now or time.time()
        with self._lock:
            return sum(1 for t in self._viewers.values() if t >= now - VIEWER_TTL_S)

    def snapshot(self, now: float | None = None) -> dict:
        now = now or time.time()
        with self._lock:
            rps = self._arrivals.rate(now)
            rps_done = self._completions.rate(now)
        return {
            "pid": os.getpid(),
            "ts": now,
            "rps": round(rps, 2),
            "rps_completed": round(rps_done, 2),
            "in_flight": self.inflight,
            "p95_ms": self.p95_ms(now),
            "active_viewers": self.active_viewers(now),
            "shed_total": self.shed_total,
            "rate_limited_total": self.rate_limited_total,
            "errors_total": self.errors_total,
            "cpu_percent": self.cpu_percent,
        }


STATS = Stats()
STARTED = STATS.started

# ---- per-process snapshot files (F13) ---------------------------------------------------------
_writer: threading.Thread | None = None
_stop = threading.Event()


def _snapshot_path(pid: int | None = None) -> str:
    return os.path.join(config.CFG.stats_dir, f"streamlite-{pid or os.getpid()}.json")


def write_snapshot() -> None:
    path = _snapshot_path()
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(STATS.snapshot(), f)
    os.replace(tmp, path)


def _writer_loop() -> None:
    # psutil keeps the cpu_percent baseline per thread, so always sample from this one thread.
    psutil.cpu_percent(None)
    while not _stop.wait(1.0):
        STATS.cpu_percent = psutil.cpu_percent(None)
        try:
            write_snapshot()
        except OSError:
            pass


def start_writer() -> None:
    global _writer
    if _writer is not None:
        return
    _stop.clear()
    write_snapshot()
    _writer = threading.Thread(target=_writer_loop, name="stats-writer", daemon=True)
    _writer.start()


def stop_writer() -> None:
    global _writer
    _stop.set()
    _writer = None
    try:
        os.remove(_snapshot_path())
    except OSError:
        pass


def _read_snapshots(now: float) -> list[dict]:
    snaps = []
    for p in glob.glob(os.path.join(config.CFG.stats_dir, "streamlite-*.json")):
        try:
            with open(p) as f:
                s = json.load(f)
        except (OSError, ValueError):
            continue
        if now - s.get("ts", 0) <= SNAPSHOT_MAX_AGE_S:
            snaps.append(s)
    return snaps


def aggregate(now: float | None = None) -> dict:
    """Combine fresh per-process snapshots: sum counters, max p95 (conservative)."""
    now = now or time.time()
    own = STATS.snapshot(now)
    others = [s for s in _read_snapshots(now) if s.get("pid") != own["pid"]]
    snaps = [own, *others]  # own process is always live, never stale
    summed = ("rps", "rps_completed", "in_flight", "active_viewers", "shed_total", "rate_limited_total", "errors_total")
    out = {k: sum(s.get(k, 0) for s in snaps) for k in summed}
    out["rps"] = round(out["rps"], 2)
    out["rps_completed"] = round(out["rps_completed"], 2)
    out["p95_ms"] = max(s.get("p95_ms", 0.0) for s in snaps)
    out["cpu_percent"] = max(s.get("cpu_percent", 0.0) for s in snaps)
    out["workers"] = len(snaps)
    return out


# ---- deterministic fake payloads ---------------------------------------------------------------
def fake_score(now: float | None = None) -> dict:
    """Same payload on every instance within a 5 s window (needed for the CDN experiment E7)."""
    k = int((now or time.time()) // 5)
    balls = k % 300
    return {
        "match_id": "m1",
        "teams": ["IND", "AUS"],
        "over": f"{balls // 6}.{balls % 6}",
        "score": f"{(balls * 13) // 10}/{min(9, balls // 40)}",
        "bucket": k,
    }


def fake_reco() -> list[dict]:
    return [{"id": f"r{i}", "title": f"Highlight #{i}", "kind": "clip"} for i in range(1, 11)]

#!/usr/bin/env python3
"""Synthetic run folders with the exact schemas of the real harness (plan section 8.2).

usage: fake_run.py [--out results] [--profile spike|fixed|step] [--mode reactive|proactive|static]
                   [--n 3] [--c1 100] [--exp FAKE_E3] [--run 1] [--seed 1]

Writes <out>/<exp>/run<run>/{meta.json, profile.json, raw/k6.csv.gz, asg_timeline.csv, instances.csv}.
Latency is lognormal and inflates when the offered rate exceeds the capacity in service, so the parser,
the plots and the dashboard can all be developed before any AWS run exists. Folders named FAKE_* are
git-ignored and are never committed.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import json
import math
import random
from pathlib import Path

BOOT_S = 150.0  # launch -> healthy
START_TS = 1_800_000_000.0  # fixed epoch so fake runs are reproducible
CLASSES = [
    ("critical", "heartbeat", 0.55),
    ("critical", "playback", 0.10),
    ("public", "state", 0.20),
    ("noncritical", "reco", 0.15),
]
BASE_MS = {"heartbeat": 4, "playback": 28, "state": 3, "reco": 70}
K6_COLS = ["metric_name", "timestamp", "metric_value", "check", "error", "error_code", "expected_response", "group",
           "method", "name", "proto", "scenario", "service", "status", "subproto", "tls_version", "url", "extra_tags",
           "metadata"]  # fmt: skip

# (second, multiple of C1): the spike profile of harness/spike.js
SPIKE_POINTS = [(0, 0.3), (120, 0.3), (210, 3.0), (300, 3.0), (305, 4.2), (325, 4.2), (330, 3.0), (420, 3.0),
                (425, 4.2), (445, 4.2), (450, 3.0), (540, 3.0), (545, 4.2), (565, 4.2), (570, 3.0), (570.5, 0.5),
                (750, 0.5)]  # fmt: skip


def spike_rate(t: float, c1: float) -> float:
    for (t0, r0), (t1, r1) in zip(SPIKE_POINTS, SPIKE_POINTS[1:], strict=False):
        if t0 <= t <= t1:
            return c1 * (r0 + (r1 - r0) * (t - t0) / max(t1 - t0, 1e-9))
    return c1 * 0.5


def profile_for(kind: str, c1: float, fixed_mult: float = 2.0, guess: float | None = None) -> dict:
    if kind == "spike":
        return {"name": "spike", "total_s": 750, "c1": c1, "speed": 1, "mix": "default",
                "events_s": {"ramp": [120, 210], "bursts": [[300, 330], [420, 450], [540, 570]]}}  # fmt: skip
    if kind == "fixed":
        return {"name": "fixed", "total_s": 330, "warmup_s": 30, "fixed_rps": round(fixed_mult * c1),
                "c1": c1, "speed": 1, "mix": "default"}  # fmt: skip
    g = guess or c1
    levels = [max(1, round((0.1 + i * 1.9 / 9) * g)) for i in range(10)]
    steps = [
        {"i": i, "rate": r, "start_s": i * 60, "hold_start_s": i * 60 + 5, "end_s": i * 60 + 60}
        for i, r in enumerate(levels)
    ]
    return {"name": "step", "guess": g, "total_s": 600, "steps": steps, "c1": c1, "speed": 1, "mix": "default"}


def rate_at(profile: dict, t: float, c1: float) -> float:
    if profile["name"] == "spike":
        return spike_rate(t, c1)
    if profile["name"] == "fixed":
        return profile["fixed_rps"] * min(1.0, t / 30.0)
    i = min(int(t // 60), len(profile["steps"]) - 1)
    return float(profile["steps"][i]["rate"])


def capacity_schedule(mode: str, n_static: int, profile: dict, rng: random.Random):
    """Returns (in_service(t), timeline rows, instance rows). Reactive adds capacity ~5 min after the ramp."""
    total = profile["total_s"]
    launches: list[tuple[float, float]] = []  # (launch t, healthy t), t relative to k6 start
    if mode == "static":
        base = n_static
    elif mode == "proactive":
        base = 4  # pre-warmed; the ladder adds two more when the arrival rate passes 3 x C1
        launches = [(150 + 5.0 * i, 150 + 5.0 * i + BOOT_S) for i in range(2)]
    else:
        base = 1
        launches = [(120 + 180 + 5.0 * i, 120 + 180 + 5.0 * i + BOOT_S) for i in range(5)]  # alarm = 3 x 1 min

    def in_service(t: float) -> int:
        return base + sum(1 for _, ht in launches if ht <= t)

    instances = []
    for k in range(base):
        instances.append({"instance_id": f"i-{k:017x}", "az": "ap-south-1a" if k % 2 == 0 else "ap-south-1b",
                          "launch_time": START_TS - 600, "first_seen_ts": START_TS - 590,
                          "in_service_ts": START_TS - 520, "first_healthy_ts": START_TS - 480,
                          "terminated_ts": ""})  # fmt: skip
    for k, (lt, ht) in enumerate(launches):
        instances.append({"instance_id": f"i-{base + k:017x}", "az": "ap-south-1a" if k % 2 == 0 else "ap-south-1b",
                          "launch_time": START_TS + lt, "first_seen_ts": START_TS + lt + 2,
                          "in_service_ts": START_TS + lt + 25 + rng.random() * 5, "first_healthy_ts": START_TS + ht,
                          "terminated_ts": START_TS + total + 240 + 10 * k})  # fmt: skip
    timeline = []
    for tick in range(0, int(total + 300) + 1, 2):
        t = float(tick)
        healthy = in_service(t)
        pending = sum(1 for lt, ht in launches if lt <= t < ht)
        desired = base + sum(1 for lt, _ in launches if lt <= t)
        if launches and t > total + 240:
            desired = max(base, desired - int((t - total - 240) // 10) - 1)
        timeline.append([f"{START_TS + t:.3f}", desired, healthy, pending, 0, healthy, 0, pending, 0])
    return in_service, timeline, instances


def write_k6_csv(
    path: Path,
    profile: dict,
    in_service,
    c1: float,
    rng: random.Random,
    load_factor: float = 1.0,
    match_only: bool = False,
) -> int:
    """Arrivals per second; latency lognormal, inflated and failing once the offered rate exceeds capacity."""
    n = 0
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", newline="") as f:
        w = csv.writer(f)
        w.writerow(K6_COLS)
        for sec in range(int(profile["total_s"])):
            rate = rate_at(profile, sec + 0.5, c1)
            rho = load_factor * rate / (max(1, in_service(sec + 0.5)) * c1)
            for _ in range(max(0, int(rng.gauss(rate, math.sqrt(max(rate, 1)))))):
                pool = [c for c in CLASSES if c[1] == "state"] if match_only else CLASSES
                cls, name, _ = rng.choices(pool, weights=[c[2] for c in pool])[0]
                inflate = 1.0 if rho < 0.85 else 1.0 + 400.0 * (rho - 0.85) ** 2
                dur = min(5000.0, rng.lognormvariate(math.log(BASE_MS[name] * inflate), 0.35))  # 5 s k6 timeout
                failed = 1 if (rho > 1.15 and rng.random() < min(0.6, (rho - 1.15) * 0.8)) else 0
                if failed:
                    dur = 5000.0
                ts = int((START_TS + sec + rng.random()) * 1000)
                tags = f"class={cls}&run_id=FAKE"
                for metric, val in (("http_req_duration", f"{dur:.3f}"), ("http_req_failed", str(failed))):
                    w.writerow([metric, ts, val, "", "", "", "", "", "", name, "", "match", "", 0 if failed else 200,
                                "", "", "", tags, ""])  # fmt: skip
                    n += 1
    return n


def make_run(
    out: Path,
    exp: str,
    run: int,
    kind: str,
    mode: str,
    n_static: int,
    c1: float,
    seed: int,
    fixed_mult: float = 2.0,
    load_factor: float = 1.0,
    match_only: bool = False,
) -> Path:
    rng = random.Random(f"{exp}-{run}-{seed}")
    profile = profile_for(kind, c1, fixed_mult, c1 * n_static)
    in_service, timeline, instances = capacity_schedule(mode, n_static, profile, rng)
    d = out / exp / f"run{run}"
    d.mkdir(parents=True, exist_ok=True)
    write_k6_csv(d / "raw" / "k6.csv.gz", profile, in_service, c1, rng, load_factor, match_only)
    with (d / "asg_timeline.csv").open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["ts", "desired", "in_service", "pending", "terminating", "healthy_targets", "unhealthy_targets",
                    "initial_targets", "draining_targets"])  # fmt: skip
        w.writerows(timeline)
    cols = ["instance_id", "az", "launch_time", "first_seen_ts", "in_service_ts", "first_healthy_ts", "terminated_ts"]
    with (d / "instances.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(instances)
    (d / "profile.json").write_text(json.dumps(profile, indent=1))
    meta = {"exp": exp, "run": run, "valid": True, "mode": f"static {n_static}" if mode == "static" else mode,
            "profile": profile["name"], "target": "alb", "k6_start_ts": START_TS,
            "k6_end_ts": START_TS + profile["total_s"], "k6_start_utc": "2027-01-15T08:00:00Z",
            "k6_end_utc": "2027-01-15T08:12:30Z", "c1": c1, "work_scale": 2.0, "instance_type": "c7i-flex.large",
            "ami_id": "ami-fake", "app_version": "fake", "harness_sha": "fake", "region": "local", "local": True,
            "speed": 1, "events_s": profile.get("events_s"), "steps": profile.get("steps"),
            "profile_total_s": profile["total_s"],
            "validity": {"dropped_iterations": 0, "loadgen_cpu_max": 35.0, "http_429": 0},
            "notes": "synthetic"}  # fmt: skip
    (d / "meta.json").write_text(json.dumps(meta, indent=1))
    return d


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default="results")
    ap.add_argument("--exp", default="FAKE_E3")
    ap.add_argument("--run", type=int, default=1)
    ap.add_argument("--profile", choices=["spike", "fixed", "step"], default="spike")
    ap.add_argument("--mode", choices=["reactive", "proactive", "static"], default="reactive")
    ap.add_argument("--n", type=int, default=3, help="instances for static mode")
    ap.add_argument("--c1", type=float, default=100)
    ap.add_argument("--seed", type=int, default=1)
    a = ap.parse_args(argv)
    print(make_run(Path(a.out), a.exp, a.run, a.profile, a.mode, a.n, a.c1, a.seed))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

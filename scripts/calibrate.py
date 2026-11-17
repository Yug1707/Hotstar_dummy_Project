#!/usr/bin/env python3
"""Calibrate the CPU work model (plan §4.6, task T2.7).

Run on the *target* instance type (c7i-flex.large on the Free plan), e.g. inside the image:
    docker run --rm -e IMDS_ENABLED=false -e SSM_MODE=off --entrypoint python \
        ghcr.io/<org>/streamlite:<sha> scripts/calibrate.py

Prints:
  1. ms per call for each class at the current ITER table and WORK_SCALE=1,
  2. the ITER values that hit the target ms (15 / 2 / 1 / 40),
  3. the 2-thread speed-up (>= 1.8x on 2 vCPUs proves the GIL is released),
  4. the theoretical rps ceiling for the traffic mix and the WORK_SCALE that puts C1 near 100 rps.
"""

from __future__ import annotations

import argparse
import os
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
for p in (os.path.join(HERE, "..", "app"), os.path.join(HERE, "..")):  # repo layout, container layout
    if os.path.isfile(os.path.join(p, "work.py")):
        sys.path.insert(0, os.path.abspath(p))
        break
os.environ["WORK_SCALE"] = "1.0"

import work  # noqa: E402

TARGET_MS = {"critical": 15.0, "heartbeat": 2.0, "state": 1.0, "reco": 40.0}
MIX = {"heartbeat": 0.55, "critical": 0.10, "state": 0.20, "reco": 0.15}  # critical = playback/start


def ms_per_call(kind: str, n: int) -> float:
    work.burn(kind)  # warm-up
    t = time.perf_counter()
    for _ in range(n):
        work.burn(kind)
    return (time.perf_counter() - t) * 1000 / n


def parallel_speedup(kind: str, n: int, threads: int) -> float:
    def run():
        for _ in range(n):
            work.burn(kind)

    t = time.perf_counter()
    run()
    serial = time.perf_counter() - t
    ts = [threading.Thread(target=run) for _ in range(threads)]
    t = time.perf_counter()
    for th in ts:
        th.start()
    for th in ts:
        th.join()
    par = time.perf_counter() - t
    return threads * serial / par


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--calls", type=int, default=200, help="calls per class")
    ap.add_argument("--target-c1", type=float, default=100.0, help="desired single-instance capacity (rps)")
    ap.add_argument("--overhead-ms", type=float, default=1.0, help="assumed per-request framework CPU (ms)")
    a = ap.parse_args()

    cpus = os.cpu_count() or 1
    print(f"cpus={cpus}  python={sys.version.split()[0]}\n")
    print(f"{'class':<10}{'iter':>9}{'ms/call':>10}{'target':>8}{'new iter':>10}")
    new_iter, measured = {}, {}
    for kind, target in TARGET_MS.items():
        ms = ms_per_call(kind, max(10, a.calls if kind != "reco" else a.calls // 4))
        measured[kind] = ms
        new_iter[kind] = max(1, round(work.ITER[kind] * target / ms))
        print(f"{kind:<10}{work.ITER[kind]:>9}{ms:>10.3f}{target:>8.1f}{new_iter[kind]:>10}")

    print("\nPaste into app/work.py:\nITER = {")
    for k, v in new_iter.items():
        print(f'    "{k}": {v:_},')
    print("}")

    sp = parallel_speedup("critical", 40, min(2, cpus))
    verdict = "ok, GIL released" if sp >= 1.8 or cpus < 2 else "LOW - check GIL / noisy host"
    print(f"\n{min(2, cpus)}-thread speed-up: {sp:.2f}x ({verdict})")

    mean_ms = sum(MIX[k] * TARGET_MS[k] for k in MIX) + a.overhead_ms
    ceiling = cpus * 1000 / mean_ms
    print(f"\nmix CPU/request ~ {mean_ms:.1f} ms (incl. {a.overhead_ms} ms overhead) -> ceiling ~ {ceiling:.0f} rps")
    print(f"WORK_SCALE for C1 ~ {a.target_c1:.0f} rps: ~ {ceiling / a.target_c1:.2f}  (confirm with k6 step.js, E1)")


if __name__ == "__main__":
    main()

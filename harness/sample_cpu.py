#!/usr/bin/env python3
"""Sample this machine's CPU % from /proc/stat (the loadgen validity check, plan §6.8 step 8).

usage: sample_cpu.py --out RUN_DIR/loadgen_cpu.csv [--interval 5]     (runs until SIGTERM)
       sample_cpu.py --max RUN_DIR/loadgen_cpu.csv                    (print the max, or -1 if empty)
"""

from __future__ import annotations

import argparse
import csv
import signal
import sys
import threading
import time
from pathlib import Path


def read_proc_stat(path: str = "/proc/stat") -> tuple[int, int]:
    """(busy, total) jiffies over all CPUs."""
    with open(path) as f:
        parts = [int(x) for x in f.readline().split()[1:]]
    idle = parts[3] + (parts[4] if len(parts) > 4 else 0)  # idle + iowait
    total = sum(parts[:8])  # user..steal; guest is already included in user
    return total - idle, total


def percent(prev: tuple[int, int], cur: tuple[int, int]) -> float:
    db, dt = cur[0] - prev[0], cur[1] - prev[1]
    return round(100.0 * db / dt, 1) if dt > 0 else 0.0


def max_of(path: Path) -> float:
    try:
        with path.open() as f:
            return max((float(r["cpu_percent"]) for r in csv.DictReader(f)), default=-1.0)
    except OSError:
        return -1.0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out")
    ap.add_argument("--interval", type=float, default=5.0)
    ap.add_argument("--max", metavar="CSV")
    a = ap.parse_args(argv)
    if a.max:
        print(max_of(Path(a.max)))
        return 0
    if not a.out:
        ap.error("--out or --max is required")

    stop = threading.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: stop.set())
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    with open(a.out, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["ts", "cpu_percent", "load1"])
        prev = read_proc_stat()
        while not stop.wait(a.interval):
            cur = read_proc_stat()
            with open("/proc/loadavg") as la:
                load1 = la.read().split()[0]
            w.writerow([f"{time.time():.3f}", percent(prev, cur), load1])
            f.flush()
            prev = cur
    return 0


if __name__ == "__main__":
    sys.exit(main())

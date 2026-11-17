#!/usr/bin/env python3
"""Proactive scaler for E4 (plan §6.6): pre-warm before the match, then a fast ladder on arrival rate.

usage: proactive_scaler.py --per-instance-rps C1 [--headroom 1.3] [--prewarm N] [--floor-until T]
                           [--hold-min 5] [--tick 10] [--out RUN_DIR/scaler.csv] [--duration S]
       proactive_scaler.py --prewarm-only N        set desired N and wait until stable, then exit

Every tick: sum the arrival rps reported by /internal/stats on each healthy instance (private IP),
extrapolating if some did not answer, then
    need   = ceil(rps * headroom / C1)
    floor  = prewarm until --floor-until, else 1
    target = clamp(max(floor, need), 1, 6)
Scale out at once (no cooldown). Scale in one step at a time, only after the target has been below
desired for --hold-min minutes and no change happened for --hold-min minutes. Desired is re-read from
the ASG every tick. Variants: E4a `--prewarm 4 --headroom 0`, E4b ladder only, E4c `--prewarm 3`.
"""

from __future__ import annotations

import argparse
import csv
import math
import signal
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path

import common
from common import MAX_CAP, log

LOG_COLS = [
    "ts",
    "in_service",
    "stats_ok",
    "rps",
    "need",
    "floor",
    "target",
    "desired_before",
    "desired_after",
    "action",
]


@dataclass
class Decision:
    rps: float
    need: int
    floor: int
    target: int
    desired_before: int
    desired_after: int
    action: str  # up | down | hold_down | steady | no_data


class Scaler:
    """Pure decision logic; the caller does the I/O (unit-tested with a fake ASG)."""

    def __init__(
        self,
        per_instance_rps: float,
        headroom: float = 1.3,
        prewarm: int = 1,
        floor_until: float = 0.0,
        hold_min: float = 5.0,
        max_cap: int = MAX_CAP,
    ) -> None:
        if per_instance_rps <= 0:
            raise ValueError("per_instance_rps must be > 0")
        self.c1 = per_instance_rps
        self.headroom = headroom
        self.prewarm = prewarm
        self.floor_until = floor_until
        self.hold_s = hold_min * 60
        self.max_cap = max_cap
        self.last_change = -math.inf
        self.below_since: float | None = None

    @staticmethod
    def total_rps(stats: list[dict | None], n_instances: int) -> float | None:
        ok = [s for s in stats if s]
        if not ok:
            return None
        return sum(float(s.get("rps", 0.0)) for s in ok) * (n_instances / len(ok))

    def decide(self, now: float, desired: int, rps: float | None) -> Decision:
        floor = self.prewarm if now < self.floor_until else 1
        if rps is None:  # no instance answered: never scale on missing data
            self.below_since = None
            return Decision(0.0, 0, floor, desired, desired, desired, "no_data")
        need = math.ceil(rps * self.headroom / self.c1 - 1e-9) if self.headroom > 0 else 0
        target = max(1, min(self.max_cap, max(floor, need)))
        if target > desired:
            self.last_change, self.below_since = now, None
            return Decision(rps, need, floor, target, desired, target, "up")
        if target < desired:
            if self.below_since is None:
                self.below_since = now
            if now - self.below_since >= self.hold_s and now - self.last_change >= self.hold_s:
                self.last_change, self.below_since = now, None
                return Decision(rps, need, floor, target, desired, desired - 1, "down")
            return Decision(rps, need, floor, target, desired, desired, "hold_down")
        self.below_since = None
        return Decision(rps, need, floor, target, desired, desired, "steady")


def set_desired(asg, name: str, n: int) -> None:
    asg.set_desired_capacity(AutoScalingGroupName=name, DesiredCapacity=n, HonorCooldown=False)


def run_loop(
    c, env: common.Env, scaler: Scaler, tick: float, out: Path | None, stop: threading.Event, deadline: float | None
) -> None:
    f = w = None
    if out:
        out.parent.mkdir(parents=True, exist_ok=True)
        f = out.open("a", newline="")
        w = csv.writer(f)
        if out.stat().st_size == 0:
            w.writerow(LOG_COLS)
    try:
        while not stop.is_set() and (deadline is None or time.time() < deadline):
            t0 = time.time()
            try:
                st = common.group_state(c, env, with_activities=False)
                insts = common.in_service_instances(c, st)
                stats = common.fetch_stats([i["ip"] for i in insts], timeout=1.0)
                rps = Scaler.total_rps(stats, len(insts))
                d = scaler.decide(t0, st.desired, rps)
                if d.desired_after != d.desired_before:
                    set_desired(c.asg, env.asg_name, d.desired_after)
                    log(f"scaler: {d.action} {d.desired_before} -> {d.desired_after} (rps={d.rps:.1f} need={d.need})")
                ok = sum(1 for s in stats if s)
                row = [
                    f"{t0:.3f}",
                    len(insts),
                    ok,
                    f"{d.rps:.2f}",
                    d.need,
                    d.floor,
                    d.target,
                    d.desired_before,
                    d.desired_after,
                    d.action,
                ]
            except Exception as e:  # noqa: BLE001 - one bad tick must not kill the scaler mid-run
                log("scaler: tick failed:", e)
                row = [f"{t0:.3f}", "", "", "", "", "", "", "", "", f"error: {e}"]
            if w is not None and f is not None:
                w.writerow(row)
                f.flush()
            stop.wait(max(0.0, tick - (time.time() - t0)))
    finally:
        if f:
            f.close()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--per-instance-rps", type=float, help="C1 from E1")
    ap.add_argument("--headroom", type=float, default=1.3)
    ap.add_argument("--prewarm", type=int, default=1)
    ap.add_argument("--floor-until", default="0", help="epoch seconds or ISO UTC; prewarm floor holds until then")
    ap.add_argument("--hold-min", type=float, default=1.0)
    ap.add_argument("--tick", type=float, default=10.0)
    ap.add_argument("--out", help="scaler.csv path")
    ap.add_argument("--duration", type=float, help="stop after this many seconds")
    ap.add_argument("--prewarm-only", type=int, metavar="N")
    ap.add_argument("--quiet-s", type=float, default=60, help="--prewarm-only: stable period to wait for")
    a = ap.parse_args(argv)

    env = common.Env.from_environ()
    c = common.clients(env.region)

    if a.prewarm_only is not None:
        n = max(1, min(MAX_CAP, a.prewarm_only))
        set_desired(c.asg, env.asg_name, n)
        log(f"scaler: prewarm desired={n}, waiting until stable ...")
        common.wait_stable(lambda: common.group_state(c, env), n, quiet_s=a.quiet_s)
        log("scaler: prewarm done")
        return 0

    if not a.per_instance_rps:
        ap.error("--per-instance-rps is required")
    if not 1 <= a.prewarm <= MAX_CAP:
        ap.error(f"--prewarm must be 1..{MAX_CAP}")
    scaler = Scaler(a.per_instance_rps, a.headroom, a.prewarm, common.parse_time(a.floor_until), a.hold_min)
    stop = threading.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: stop.set())
    deadline = time.time() + a.duration if a.duration else None
    log(
        f"scaler: C1={a.per_instance_rps} headroom={a.headroom} prewarm={a.prewarm} "
        f"floor_until={common.utc_iso(scaler.floor_until)} hold={a.hold_min}m tick={a.tick}s"
    )
    run_loop(c, env, scaler, a.tick, Path(a.out) if a.out else None, stop, deadline)
    log("scaler: stopped")
    return 0


if __name__ == "__main__":
    sys.exit(main())

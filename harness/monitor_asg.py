#!/usr/bin/env python3
"""Record the ASG and target-group state during a run (plan §6.5).

usage: monitor_asg.py --out RUN_DIR [--interval 5] [--stats]

  asg_timeline.csv  one row per tick: desired, in_service, pending, terminating, target states
  instances.csv     one row per instance: launch time (EC2 API), first seen, InService, first healthy,
                    terminated; rewritten atomically whenever a row changes
  stats.csv         (--stats) /internal/stats of every healthy instance per tick (E6 shed counts etc.)

Rows are flushed immediately; SIGTERM / SIGINT stop it cleanly.
"""

from __future__ import annotations

import argparse
import csv
import os
import signal
import sys
import threading
import time
from pathlib import Path

import common

TIMELINE_COLS = [
    "ts",
    "desired",
    "in_service",
    "pending",
    "terminating",
    "healthy_targets",
    "unhealthy_targets",
    "initial_targets",
    "draining_targets",
]
INSTANCE_COLS = [
    "instance_id",
    "az",
    "launch_time",
    "first_seen_ts",
    "in_service_ts",
    "first_healthy_ts",
    "terminated_ts",
]
STATS_COLS = [
    "ts",
    "instance_id",
    "rps",
    "rps_completed",
    "in_flight",
    "p95_ms",
    "cpu_percent",
    "active_viewers",
    "shed_total",
    "rate_limited_total",
    "errors_total",
    "degrade_level",
    "workers",
]


class InstanceTracker:
    """First-seen / InService / healthy / terminated timestamps per instance."""

    def __init__(self) -> None:
        self.rows: dict[str, dict] = {}

    def update(self, ts: float, asg_instances: list[dict], targets: dict[str, str], launch: dict[str, float]) -> bool:
        changed = False
        present = set()
        for inst in asg_instances:
            iid = inst["InstanceId"]
            present.add(iid)
            row = self.rows.get(iid)
            if row is None:
                row = {c: "" for c in INSTANCE_COLS}
                row.update(instance_id=iid, az=inst.get("AvailabilityZone", ""), first_seen_ts=f"{ts:.3f}")
                self.rows[iid] = row
                changed = True
            if not row["launch_time"] and iid in launch:
                row["launch_time"] = f"{launch[iid]:.3f}"
                changed = True
            state = inst["LifecycleState"]
            if state == "InService" and not row["in_service_ts"]:
                row["in_service_ts"] = f"{ts:.3f}"
                changed = True
            if targets.get(iid) == "healthy" and not row["first_healthy_ts"]:
                row["first_healthy_ts"] = f"{ts:.3f}"
                changed = True
            if state.startswith("Terminating") and not row["terminated_ts"]:
                row["terminated_ts"] = f"{ts:.3f}"
                changed = True
        for iid, row in self.rows.items():
            if iid not in present and not row["terminated_ts"]:
                row["terminated_ts"] = f"{ts:.3f}"
                changed = True
        return changed

    def missing_launch_times(self) -> list[str]:
        return [i for i, r in self.rows.items() if not r["launch_time"] and not r["terminated_ts"]]

    def write(self, path: Path) -> None:
        tmp = path.with_suffix(".tmp")
        with tmp.open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=INSTANCE_COLS)
            w.writeheader()
            w.writerows(self.rows.values())
        os.replace(tmp, path)


def timeline_row(ts: float, st: common.GroupState) -> list:
    return [
        f"{ts:.3f}",
        st.desired,
        st.in_service,
        st.pending,
        st.terminating,
        st.healthy,
        st.unhealthy,
        st.initial,
        st.draining,
    ]


def stats_rows(ts: float, insts: list[dict], stats: list[dict | None]) -> list[list]:
    rows = []
    for inst, s in zip(insts, stats, strict=True):
        if s is None:
            rows.append([f"{ts:.3f}", inst["id"], *[""] * (len(STATS_COLS) - 2)])
        else:
            rows.append([f"{ts:.3f}", inst["id"], *[s.get(k, "") for k in STATS_COLS[2:]]])
    return rows


def open_csv(path: Path, cols: list[str]):
    new = not path.exists()
    f = path.open("a", newline="")
    w = csv.writer(f)
    if new:
        w.writerow(cols)
        f.flush()
    return f, w


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", required=True)
    ap.add_argument("--interval", type=float, default=5.0)
    ap.add_argument("--stats", action="store_true", help="also sample /internal/stats of every healthy instance")
    a = ap.parse_args(argv)

    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    env = common.Env.from_environ()
    c = common.clients(env.region)
    stop = threading.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: stop.set())

    tl_f, tl = open_csv(out / "asg_timeline.csv", TIMELINE_COLS)
    st_f, stw = open_csv(out / "stats.csv", STATS_COLS) if a.stats else (None, None)
    tracker = InstanceTracker()
    common.log(f"monitor: {env.asg_name} every {a.interval}s -> {out}")
    try:
        while not stop.is_set():
            t0 = time.time()
            try:
                st = common.group_state(c, env, with_activities=False)
            except Exception as e:  # noqa: BLE001 - keep monitoring through API hiccups
                common.log("monitor: describe failed:", e)
                stop.wait(a.interval)
                continue
            tl.writerow(timeline_row(t0, st))
            tl_f.flush()

            launch: dict[str, float] = {}
            todo = [i["InstanceId"] for i in st.instances if i["InstanceId"] not in tracker.rows]
            todo += tracker.missing_launch_times()
            if todo:
                try:
                    for r in c.ec2.describe_instances(InstanceIds=sorted(set(todo)))["Reservations"]:
                        for i in r["Instances"]:
                            launch[i["InstanceId"]] = i["LaunchTime"].timestamp()
                except Exception as e:  # noqa: BLE001
                    common.log("monitor: describe_instances failed:", e)
            if tracker.update(t0, st.instances, st.targets, launch):
                tracker.write(out / "instances.csv")

            if stw is not None and st_f is not None:
                insts = common.in_service_instances(c, st)
                stats = common.fetch_stats([i["ip"] for i in insts], timeout=1.0)
                stw.writerows(stats_rows(t0, insts, stats))
                st_f.flush()

            stop.wait(max(0.0, a.interval - (time.time() - t0)))
    finally:
        tracker.write(out / "instances.csv")
        tl_f.close()
        if st_f:
            st_f.close()
        common.log("monitor: stopped")
    return 0


if __name__ == "__main__":
    sys.exit(main())

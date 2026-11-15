#!/usr/bin/env python3
"""Download the CloudWatch metrics of one run into RUN_DIR/cw/*.csv (plan §6.7).

usage: collect_cw.py --start T --end T --out RUN_DIR/cw [--period 60] [--no-wait]

T is epoch seconds or ISO UTC. The window is [start - 5 min, end + 10 min] because CloudWatch lags;
unless --no-wait, it first sleeps until end + 3 min so the last datapoints exist.
One CSV per metric/stat: ts,value (ts = epoch seconds of the period start, sorted).
"""

from __future__ import annotations

import argparse
import csv
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import common
from common import log


def metric_specs(env: common.Env) -> list[dict]:
    """(file name, namespace, metric, dimensions, stat) for every series of plan §6.7."""
    lb = [{"Name": "LoadBalancer", "Value": env.alb_suffix}]
    tg = [{"Name": "TargetGroup", "Value": env.tg_suffix}]
    tg_lb = tg + lb
    asg = [{"Name": "AutoScalingGroupName", "Value": env.asg_name}]
    specs = [
        ("alb_request_count_sum", "AWS/ApplicationELB", "RequestCount", lb, "Sum"),
        ("tg_request_count_per_target_sum", "AWS/ApplicationELB", "RequestCountPerTarget", tg, "Sum"),
        ("alb_target_response_time_p50", "AWS/ApplicationELB", "TargetResponseTime", lb, "p50"),
        ("alb_target_response_time_p95", "AWS/ApplicationELB", "TargetResponseTime", lb, "p95"),
        ("alb_target_response_time_p99", "AWS/ApplicationELB", "TargetResponseTime", lb, "p99"),
        ("alb_elb_5xx_sum", "AWS/ApplicationELB", "HTTPCode_ELB_5XX_Count", lb, "Sum"),
        ("alb_target_5xx_sum", "AWS/ApplicationELB", "HTTPCode_Target_5XX_Count", lb, "Sum"),
        ("tg_healthy_hosts_max", "AWS/ApplicationELB", "HealthyHostCount", tg_lb, "Maximum"),
        ("tg_unhealthy_hosts_max", "AWS/ApplicationELB", "UnHealthyHostCount", tg_lb, "Maximum"),
        ("asg_cpu_avg", "AWS/EC2", "CPUUtilization", asg, "Average"),
        ("asg_cpu_max", "AWS/EC2", "CPUUtilization", asg, "Maximum"),
        ("asg_desired_max", "AWS/AutoScaling", "GroupDesiredCapacity", asg, "Maximum"),
        ("asg_in_service_max", "AWS/AutoScaling", "GroupInServiceInstances", asg, "Maximum"),
        ("asg_pending_max", "AWS/AutoScaling", "GroupPendingInstances", asg, "Maximum"),
    ]
    return [
        {"name": n, "namespace": ns, "metric": m, "dims": d, "stat": s}
        for n, ns, m, d, s in specs
        if all(x["Value"] for x in d)
    ]


def queries(specs: list[dict], period: int) -> list[dict]:
    return [
        {
            "Id": f"m{i}",
            "Label": s["name"],
            "MetricStat": {
                "Metric": {"Namespace": s["namespace"], "MetricName": s["metric"], "Dimensions": s["dims"]},
                "Period": period,
                "Stat": s["stat"],
            },
            "ReturnData": True,
        }
        for i, s in enumerate(specs)
    ]


def fetch(cw, qs: list[dict], start: float, end: float) -> dict[str, list[tuple[float, float]]]:
    out: dict[str, list[tuple[float, float]]] = {q["Label"]: [] for q in qs}
    by_id = {q["Id"]: q["Label"] for q in qs}
    kwargs = {
        "MetricDataQueries": qs,
        "StartTime": datetime.fromtimestamp(start, UTC),
        "EndTime": datetime.fromtimestamp(end, UTC),
        "ScanBy": "TimestampAscending",
    }
    while True:
        resp = cw.get_metric_data(**kwargs)
        for r in resp["MetricDataResults"]:
            out[by_id[r["Id"]]].extend((t.timestamp(), v) for t, v in zip(r["Timestamps"], r["Values"], strict=True))
        token = resp.get("NextToken")
        if not token:
            return out
        kwargs["NextToken"] = token


def write(out_dir: Path, series: dict[str, list[tuple[float, float]]]) -> int:
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, pts in series.items():
        with (out_dir / f"{name}.csv").open("w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["ts", "value"])
            w.writerows((f"{t:.0f}", v) for t, v in sorted(pts))
    return len(series)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--start", required=True)
    ap.add_argument("--end", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--period", type=int, default=60)
    ap.add_argument("--no-wait", action="store_true")
    a = ap.parse_args(argv)

    start, end = common.parse_time(a.start), common.parse_time(a.end)
    env = common.Env.from_environ()
    specs = metric_specs(env)
    if len(specs) < 14:
        log("collect_cw: ALB_ARN_SUFFIX / TG_ARN_SUFFIX missing, collecting only", len(specs), "series")
    if not a.no_wait and time.time() < end + 180:
        wait = end + 180 - time.time()
        log(f"collect_cw: waiting {wait:.0f}s for CloudWatch to catch up")
        time.sleep(wait)
    c = common.clients(env.region)
    series = fetch(c.cw, queries(specs, a.period), start - 300, min(time.time(), end + 600))
    n = write(Path(a.out), series)
    log(f"collect_cw: wrote {n} series, {sum(len(v) for v in series.values())} datapoints -> {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

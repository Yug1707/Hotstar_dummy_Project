#!/usr/bin/env python3
"""Turn one run folder into aggregates.csv.gz and summary.json (plan section 8.3).

usage: parse_k6.py RUN_DIR [RUN_DIR ...]      parse these run folders
       parse_k6.py --all [--results DIR]      every results/E*/run*/ (idempotent; skips fresh summaries)
       parse_k6.py --all --pattern 'FAKE_*'   fake data from fake_run.py

Metric definitions (copied into the report, section 4):
- per-second bucket: requests grouped by floor(timestamp - k6_start); the first warmup_discard_s are dropped
  for fixed and step profiles, never for spike (there the start is the test).
- SLO-violation second: a bucket with >= 10 critical requests where critical p95 > slo p95 or error rate > slo.
- error: http_req_failed = 1 (status >= 400, 5 s timeout or connection error).
- time to first new instance: first asg_timeline row with healthy_targets > baseline, minus the ramp start.
- instance-minutes: integral of (in_service + pending) over [k6_start, k6_end + observe_s].
- capacity (step profile): the highest step rate before the first step that breaks the SLO.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

try:
    from analysis import common
except ImportError:  # run as a script
    import common  # type: ignore[no-redef]

MIN_REQ_PER_BUCKET = 10
OBSERVE_S = 300
CHUNK = 1_000_000
TAG_CLASS = r"class=([A-Za-z_]+)"


def read_metrics(path: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(durations, failures): both with columns ts (s, float), cls, value. Chunked to stay under 1 GB."""
    dur, fail = [], []
    reader = pd.read_csv(
        path,
        compression="gzip" if str(path).endswith(".gz") else None,
        chunksize=CHUNK,
        usecols=["metric_name", "timestamp", "metric_value", "extra_tags"],
        dtype={"metric_name": "string", "extra_tags": "string"},
    )
    for ch in reader:
        ch = ch[ch["metric_name"].isin(["http_req_duration", "http_req_failed"])]
        ch = ch.assign(
            ts=ch["timestamp"].astype("float64") / 1000.0,
            cls=ch["extra_tags"].str.extract(TAG_CLASS, expand=False).fillna("other"),
            value=ch["metric_value"].astype("float64"),
        )[["metric_name", "ts", "cls", "value"]]
        dur.append(ch[ch["metric_name"] == "http_req_duration"].drop(columns="metric_name"))
        fail.append(ch[ch["metric_name"] == "http_req_failed"].drop(columns="metric_name"))
    empty = pd.DataFrame({"ts": [], "cls": [], "value": []})
    return (pd.concat(dur) if dur else empty), (pd.concat(fail) if fail else empty)


def aggregate(dur: pd.DataFrame, fail: pd.DataFrame, start_ts: float) -> pd.DataFrame:
    """One row per (second, class): count, p50, p95, p99, err_rate, rps."""
    cols = ["sec", "cls", "count", "p50", "p95", "p99", "err_rate", "rps"]
    if dur.empty:
        return pd.DataFrame(columns=cols)
    d = dur.assign(sec=np.floor(dur["ts"] - start_ts).astype(int))
    g = d.groupby(["sec", "cls"])["value"]
    agg = pd.DataFrame(
        {
            "count": g.size(),
            "p50": g.quantile(0.50),
            "p95": g.quantile(0.95),
            "p99": g.quantile(0.99),
        }
    )
    if fail.empty:
        agg["err_rate"] = 0.0
    else:
        f = fail.assign(sec=np.floor(fail["ts"] - start_ts).astype(int))
        agg["err_rate"] = f.groupby(["sec", "cls"])["value"].mean()
        agg["err_rate"] = agg["err_rate"].fillna(0.0)
    agg["rps"] = agg["count"].astype(float)
    return agg.reset_index()[cols].sort_values(["sec", "cls"]).reset_index(drop=True)


def window_stats(dur: pd.DataFrame, fail: pd.DataFrame, cls: str, lo: float, hi: float) -> dict:
    """p50/p95/p99 and error rate of one class inside [lo, hi) seconds from k6 start (ts already relative)."""
    d = dur[(dur["cls"] == cls) & (dur["ts"] >= lo) & (dur["ts"] < hi)]["value"]
    f = fail[(fail["cls"] == cls) & (fail["ts"] >= lo) & (fail["ts"] < hi)]["value"]
    if d.empty:
        return {"p50_ms": None, "p95_ms": None, "p99_ms": None, "error_rate": None, "requests": 0}
    q = d.quantile([0.5, 0.95, 0.99])
    return {
        "p50_ms": round(float(q[0.5]), 2),
        "p95_ms": round(float(q[0.95]), 2),
        "p99_ms": round(float(q[0.99]), 2),
        "error_rate": round(float(f.mean()) if not f.empty else 0.0, 5),
        "requests": int(len(d)),
    }


def slo_violation_seconds(agg: pd.DataFrame, slo: dict, lo: float = 0, hi: float = float("inf")) -> int:
    c = agg[(agg["cls"] == "critical") & (agg["sec"] >= lo) & (agg["sec"] < hi) & (agg["count"] >= MIN_REQ_PER_BUCKET)]
    bad = (c["p95"] > slo["critical_p95_ms"]) | (c["err_rate"] > slo["error_rate"])
    return int(bad.sum())


def read_csv_rows(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(newline="") as f:
        return list(csv.DictReader(f))


def fnum(x) -> float | None:
    try:
        return float(x) if x not in ("", None) else None
    except ValueError:
        return None


def asg_metrics(run: Path, start_ts: float, end_ts: float, ramp_start_s: float | None) -> dict:
    rows = read_csv_rows(run / "asg_timeline.csv")
    out = {"time_to_first_new_instance_s": None, "instance_minutes": None, "peak_instances": None}
    if not rows:
        return out
    ts = np.array([float(r["ts"]) for r in rows])
    healthy = np.array([float(r["healthy_targets"]) for r in rows])
    billed = np.array([float(r["in_service"]) + float(r["pending"]) for r in rows])
    before = ts <= start_ts
    baseline = healthy[before][-1] if before.any() else healthy[0]
    if ramp_start_s is not None:
        later = (ts >= start_ts + ramp_start_s) & (healthy > baseline)
        if later.any():
            out["time_to_first_new_instance_s"] = round(float(ts[later][0] - (start_ts + ramp_start_s)), 1)
    hi = end_ts + OBSERVE_S
    sel = (ts >= start_ts) & (ts <= hi)
    if sel.sum() >= 2:
        # step integration: each sample holds until the next one
        t, b = ts[sel], billed[sel]
        out["instance_minutes"] = round(float(np.sum(b[:-1] * np.diff(t)) / 60.0), 2)
    out["peak_instances"] = (
        int(billed[(ts >= start_ts) & (ts <= end_ts)].max())
        if ((ts >= start_ts) & (ts <= end_ts)).any()
        else int(billed.max())
    )
    return out


def shed_total(run: Path) -> int | None:
    rows = read_csv_rows(run / "stats.csv")
    if not rows:
        return None
    best: dict[str, float] = {}
    for r in rows:
        v = fnum(r.get("shed_total"))
        if v is not None:
            best[r["instance_id"]] = max(best.get(r["instance_id"], 0.0), v)
    return int(sum(best.values())) if best else None


def step_results(
    dur: pd.DataFrame, fail: pd.DataFrame, steps: list[dict], slo: dict
) -> tuple[list[dict], float | None]:
    out, capacity, broken = [], None, False
    for s in steps:
        w = window_stats(dur, fail, "critical", s["hold_start_s"], s["end_s"])
        ok = w["p95_ms"] is not None and w["p95_ms"] < slo["critical_p95_ms"] and w["error_rate"] < slo["error_rate"]
        out.append({"i": s["i"], "rate": s["rate"], "ok": bool(ok), **w})
        if not ok:
            broken = True
        if ok and not broken:
            capacity = float(s["rate"])
    return out, capacity


def parse_run(run: Path, slo: dict, warmup_s: float) -> dict:
    meta = common.read_json(run / "meta.json")
    start = float(meta["k6_start_ts"])
    end = float(meta.get("k6_end_ts") or start + float(meta.get("profile_total_s") or 0))
    dur, fail = read_metrics(run / "raw" / "k6.csv.gz")
    agg = aggregate(dur, fail, start)
    agg.to_csv(run / "aggregates.csv.gz", index=False)
    # relative timestamps for window statistics
    dur = dur.assign(ts=dur["ts"] - start)
    fail = fail.assign(ts=fail["ts"] - start)

    profile = meta.get("profile")
    lo = warmup_s if profile in ("fixed", "step") else 0.0
    hi = float("inf")
    crit = window_stats(dur, fail, "critical", lo, hi)
    c_agg = agg[agg["cls"] == "critical"]
    c_agg = c_agg[c_agg["sec"] >= lo]
    ev = meta.get("events_s") or {}
    ramp = ev.get("ramp") or [None]
    total = agg.groupby("sec")["count"].sum() if not agg.empty else pd.Series(dtype=float)
    summary = {
        "exp": meta["exp"],
        "run": meta["run"],
        "valid": meta.get("valid"),
        "mode": meta.get("mode"),
        "profile": profile,
        "c1": meta.get("c1"),
        "duration_s": round(end - start, 1),
        "requests": int(agg["count"].sum()) if not agg.empty else 0,
        "critical": {k: crit[k] for k in ("p50_ms", "p95_ms", "p99_ms", "error_rate")},
        "slo_violation_s": slo_violation_seconds(agg, slo, lo),
        "peak_p95_ms": round(float(c_agg["p95"].max()), 1) if not c_agg.empty else None,
        "throughput_rps_max": int(total[total.index >= lo].max()) if len(total) else None,
        "shed_total": shed_total(run),
        **asg_metrics(run, start, end, ramp[0]),
    }
    if profile == "step" and meta.get("steps"):
        summary["steps"], summary["capacity_rps"] = step_results(dur, fail, meta["steps"], slo)
    if profile == "fixed" and meta.get("k6_env"):
        summary["k6_env"] = meta["k6_env"]
    (run / "summary.json").write_text(json.dumps(summary, indent=1) + "\n")
    return summary


def parse_boot(run: Path) -> dict:
    """E5: per new instance launch -> InService -> first healthy (seconds), from instances.csv."""
    meta = common.read_json(run / "meta.json")
    rows = {r["instance_id"]: r for r in read_csv_rows(run / "instances.csv")}
    inst = []
    for iid in meta.get("new_instances", []):
        r = rows.get(iid)
        if not r:
            continue
        launch, ins, healthy = fnum(r["launch_time"]), fnum(r["in_service_ts"]), fnum(r["first_healthy_ts"])
        if launch is None or ins is None or healthy is None:
            continue
        inst.append(
            {
                "instance_id": iid,
                "launch_to_in_service_s": round(ins - launch, 1),
                "in_service_to_healthy_s": round(healthy - ins, 1),
                "launch_to_healthy_s": round(healthy - launch, 1),
            }
        )
    totals = [i["launch_to_healthy_s"] for i in inst]
    summary = {
        "exp": meta["exp"],
        "run": meta["run"],
        "valid": meta.get("valid"),
        "label": meta.get("label"),
        "instances": inst,
        "median_launch_to_healthy_s": common.median(totals),
        "max_launch_to_healthy_s": max(totals) if totals else None,
        "all_healthy_s": meta.get("all_healthy_s"),
    }
    (run / "summary.json").write_text(json.dumps(summary, indent=1) + "\n")
    return summary


def is_fresh(run: Path) -> bool:
    s = run / "summary.json"
    if not s.exists():
        return False
    newest = max(
        (
            p.stat().st_mtime
            for p in (run / "raw" / "k6.csv.gz", run / "asg_timeline.csv", run / "meta.json")
            if p.exists()
        ),
        default=0,
    )
    return s.stat().st_mtime >= newest


def parse_any(run: Path, cfg: dict, force: bool = False) -> dict | None:
    if not force and is_fresh(run):
        return None
    meta = common.read_json(run / "meta.json")
    if meta.get("profile") == "none":
        return parse_boot(run)
    if not (run / "raw" / "k6.csv.gz").exists():
        print(f"skip {run}: raw/k6.csv.gz not here (make results-pull RAW=1)", file=sys.stderr)
        return None
    return parse_run(run, cfg["slo"], float(cfg.get("warmup_discard_s", 30)))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("runs", nargs="*", type=Path)
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--results", type=Path, default=common.RESULTS)
    ap.add_argument("--pattern", default="E*")
    ap.add_argument("--force", action="store_true", help="reparse even if summary.json is newer")
    a = ap.parse_args(argv)
    cfg = common.global_cfg()
    runs = common.run_dirs(a.results, a.pattern) if a.all else a.runs
    if not runs:
        print("nothing to parse (give run folders or --all)", file=sys.stderr)
        return 1
    n = 0
    for r in runs:
        s = parse_any(r, cfg, a.force)
        if s:
            n += 1
            crit = (s.get("critical") or {}).get("p95_ms")
            print(f"{r}: critical p95={crit} slo_violation_s={s.get('slo_violation_s')}")
    print(f"parsed {n} of {len(runs)} run folders")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

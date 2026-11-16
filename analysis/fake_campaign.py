#!/usr/bin/env python3
"""A whole synthetic campaign (E1..E7) under results/FAKE_*, so make_plots / export / the dashboard can be
developed before any AWS run exists. Uses a small C1 (default 10) to stay fast.

usage: fake_campaign.py [--out results] [--c1 10] [--runs 3]

Folder names are the real ones with a FAKE_ prefix (FAKE_E2a_N3, FAKE_E5_baked, ...). The analysis
tools take --prefix FAKE_ to read them. FAKE_* is git-ignored.
"""

from __future__ import annotations

import argparse
import csv
import json
import random
from pathlib import Path

try:
    from analysis import fake_run
except ImportError:  # run as a script
    import fake_run  # type: ignore[no-redef]


def boot_run(out: Path, exp: str, run: int, label: str, seed: int) -> None:
    rng = random.Random(f"{exp}-{run}-{seed}")
    boot = {"baked": (28, 20), "naive": (35, 120)}[label]  # (launch->InService, InService->healthy) in seconds
    d = out / exp / f"run{run}"
    d.mkdir(parents=True, exist_ok=True)
    t0 = fake_run.START_TS
    cols = ["instance_id", "az", "launch_time", "first_seen_ts", "in_service_ts", "first_healthy_ts", "terminated_ts"]
    ids, rows = [], []
    for k in range(4):
        iid = f"i-{k + 10:017x}"
        ids.append(iid)
        launch = t0 + 2 + rng.random()
        ins = launch + boot[0] + rng.random() * 6
        rows.append(
            {
                "instance_id": iid,
                "az": "ap-south-1a",
                "launch_time": f"{launch:.3f}",
                "first_seen_ts": f"{launch + 2:.3f}",
                "in_service_ts": f"{ins:.3f}",
                "first_healthy_ts": f"{ins + boot[1] + rng.random() * 12:.3f}",
                "terminated_ts": "",
            }
        )
    with (d / "instances.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)
    all_healthy = max(float(r["first_healthy_ts"]) for r in rows) - t0
    meta = {"exp": exp, "run": run, "valid": True, "mode": f"boot {label}", "profile": "none", "label": label,
            "from": 1, "to": 5, "scale_start_ts": t0,
            "all_healthy_s": all_healthy, "new_instances": ids, "notes": "synthetic"}  # fmt: skip
    (d / "meta.json").write_text(json.dumps(meta, indent=1))


def add_stats(d: Path, shed_per_s: float, total_s: int = 330) -> None:
    cols = ["ts", "instance_id", "rps", "rps_completed", "in_flight", "p95_ms", "cpu_percent", "active_viewers",
            "shed_total", "rate_limited_total", "errors_total", "degrade_level", "workers"]  # fmt: skip
    with (d / "stats.csv").open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(cols)
        for t in range(0, total_s, 10):
            for k in range(2):
                w.writerow(
                    [fake_run.START_TS + t, f"i-{k:017x}", 0, 0, 0, 0, 0, 0, int(shed_per_s * t / 2), 0, 0, 0, 2]
                )


def add_cw(d: Path, origin_per_s: float, total_s: int) -> None:
    (d / "cw").mkdir(exist_ok=True)
    with (d / "cw" / "alb_request_count_sum.csv").open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["ts", "value"])
        for t in range(0, total_s, 60):
            w.writerow([int(fake_run.START_TS + t), int(origin_per_s * 60)])


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, default=Path("results"))
    ap.add_argument("--c1", type=float, default=10)
    ap.add_argument("--runs", type=int, default=3)
    a = ap.parse_args(argv)
    c1, out, n = a.c1, a.out, a.runs

    def mk(exp, run, kind, mode, nst, **kw):
        return fake_run.make_run(out, f"FAKE_{exp}", run, kind, mode, nst, c1, seed=7, **kw)

    for r in range(1, n + 1):
        mk("E1", r, "step", "static", 1)
        for k in range(1, 6):
            mk(f"E2a_N{k}", r, "fixed", "static", k, fixed_mult=2.0)
        mk("E3", r, "spike", "reactive", 1)
        mk("E4c", r, "spike", "proactive", 4)
        for label in ("naive", "baked"):
            boot_run(out, f"FAKE_E5_{label}", r, label, 7)
        for variant, lf, shed in (("none", 1.0, 0), ("ssm_level1", 0.8, 20), ("auto_shed", 0.65, 40)):
            d = mk(f"E6_{variant}", r, "fixed", "static", 2, fixed_mult=3.0, load_factor=lf)
            add_stats(d, shed)
        for target, lf, origin in (("alb", 1.0, 3.0 * c1), ("cloudfront", 0.02, 0.4)):
            d = mk(f"E7_{target}", r, "fixed", "static", 2, fixed_mult=3.0, load_factor=lf, match_only=True)
            add_cw(d, origin, 480)
    for k in range(1, 6):
        mk(f"E2b_N{k}", 1, "step", "static", k)
    mk("E4a", 1, "spike", "proactive", 4)
    mk("E4b", 1, "spike", "reactive", 1)
    print(f"synthetic campaign written to {out}/FAKE_*")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

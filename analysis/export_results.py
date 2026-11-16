#!/usr/bin/env python3
"""Write web/data/results.json for the dashboard and copy the figures to web/img/ (plan section 8.6).

usage: export_results.py [--results results] [--prefix ""] [--web web] [--figures results/figures]
                         [--model config/model.yaml] [--prices config/prices.yaml]

With no analysed runs yet the file is {"pending": true, ...}: the dashboard then shows "results pending" and
still works. Everything in the file comes from the committed summary.json / timeline.json files.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path

try:
    from analysis import common, cost_model, make_plots
except ImportError:  # run as a script
    import common  # type: ignore[no-redef]
    import cost_model  # type: ignore[no-redef]
    import make_plots  # type: ignore[no-redef]


def fmt(x, unit: str = "", nd: int = 0) -> str:
    return "n/a" if x is None else f"{x:.{nd}f}{unit}"


def spread(xs: list[float]) -> str:
    return f"{min(xs):g}-{max(xs):g}" if xs else "n/a"


def key_numbers(d: make_plots.Data, cost: dict | None) -> list[dict]:
    out = []
    caps = d.values("E1", lambda s: s.get("capacity_rps"))
    if caps:
        out.append({"label": "Single-instance capacity (C1)", "value": f"{common.median(caps):g} rps", "exp": "E1",
                    "detail": f"median of {len(caps)} runs, range {spread(caps)}"})  # fmt: skip
    n1 = d.values("E2a_N1", lambda s: s["critical"]["p95_ms"])
    n3 = d.values("E2a_N3", lambda s: s["critical"]["p95_ms"])
    if n1 and n3:
        out.append({"label": "Critical p95 at 2 x C1: 1 vs 3 instances",
                    "value": f"{common.median(n1):,.0f} ms vs {common.median(n3):,.0f} ms", "exp": "E2"})  # fmt: skip
    t = d.values("E3", lambda s: s.get("time_to_first_new_instance_s"))
    if t:
        out.append({"label": "Reactive: first new instance after the ramp starts", "value": f"{common.median(t):.0f} s",
                    "exp": "E3", "detail": "Hotstar's window was about 90 s"})  # fmt: skip
    v3, v4 = d.values("E3", lambda s: s["slo_violation_s"]), d.values("E4c", lambda s: s["slo_violation_s"])
    if v3 and v4:
        out.append({"label": "SLO-violation seconds: reactive vs proactive",
                    "value": f"{common.median(v3):.0f} s vs {common.median(v4):.0f} s", "exp": "E3/E4"})  # fmt: skip
    if cost:
        pro = next((s for s in cost["strategies"] if s["exp"] == "E4c"), None)
        if pro and pro.get("extra_instance_minutes_pct_vs_reactive") is not None:
            out.append({"label": "Price of safety (extra instance-minutes)",
                        "value": f"{pro['extra_instance_minutes_pct_vs_reactive']:+.0f} %", "exp": "E4"})  # fmt: skip
    bn = d.values("E5_naive", lambda s: s.get("median_launch_to_healthy_s"))
    bb = d.values("E5_baked", lambda s: s.get("median_launch_to_healthy_s"))
    if bn and bb:
        out.append({"label": "Launch to healthy: naive vs baked AMI",
                    "value": f"{common.median(bn):.0f} s vs {common.median(bb):.0f} s", "exp": "E5"})  # fmt: skip
    return out


def captions(d: make_plots.Data, c1: float, runs: dict[str, dict]) -> dict[str, str]:
    n = lambda fid: runs.get(fid, {}).get("runs", "?")  # noqa: E731
    cap = {
        "F1": f"F1: Critical latency vs instance count at a fixed 2 x C1 load, and capacity vs N. "
        f"The knee sits between one and two instances. N = {n('F1')} runs, C1 = {c1:g} rps, c6i.large.",
        "F2": f"F2: Match-day spike, reactive vs proactive. Reactive capacity arrives late; "
        f"proactive stays inside the SLO. N = {n('F2')} runs, median run shown.",
        "F3": "F3: SLO-violation seconds and critical error rate per scaling strategy. Pre-warming removes the violations.",
        "F4": f"F4: Time from launch to first healthy target for each new instance, naive vs baked AMI. "
        f"N = {n('F4')} runs per mode.",
        "F5": f"F5: Critical p95 and shed requests with no degradation, a manual degrade level and auto-shed. "
        f"N = {n('F5')} runs per variant.",
        "F6": f"F6: Requests that reach the origin and the viewer's p95, ALB directly vs through CloudFront. "
        f"N = {n('F6')} runs per arm.",
        "F7": "F7: Cost per strategy at test scale, and the fleet needed for the real peaks. "
        "Assumptions are in the footer and in docs/report.",
    }
    return cap


def series(d: make_plots.Data, c1: float) -> dict:
    out: dict = {}
    ns = [n for n in range(1, 7) if d.get(f"E2a_N{n}")]
    if ns:
        p95 = [d.values(f"E2a_N{n}", lambda s: s["critical"]["p95_ms"]) for n in ns]
        caps = [common.median(d.values(f"E2b_N{n}", lambda s: s.get("capacity_rps"))) for n in ns]
        out["F1"] = {
            "n": ns,
            "p95_ms": [common.median(v) for v in p95],
            "p95_min": [min(v) if v else None for v in p95],
            "p95_max": [max(v) if v else None for v in p95],
            "capacity": caps,
            "ideal": [c1 * n for n in ns],
        }
    f2 = {}
    for label, exp in (("reactive", "E3"), ("proactive", "E4c")):
        s = d.median_run(exp)
        tl = d.dirs.get((exp, int(s["run"])), Path()) / "timeline.json" if s else None
        if tl and tl.exists():
            t = common.read_json(tl)
            f2.setdefault("t", t["t"])
            f2[f"{label}_p95"] = t["p95_ms"]
            f2[f"{label}_n"] = t["healthy"]
            meta = common.read_json(tl.parent / "meta.json")
            f2.setdefault("events_s", meta.get("events_s"))
    if "reactive_p95" in f2 and "proactive_p95" in f2:
        out["F2"] = f2
    return out


def build(results: Path, prefix: str, model_path: Path, prices_path: Path, figures: Path) -> dict:
    cfg = common.global_cfg()
    d = make_plots.Data(results, prefix)
    c1 = common.median([s["c1"] for s in d.get("E1") + d.get("E2a_N1") if s.get("c1")]) or float(cfg["c1"])
    model, prices = common.load_yaml(model_path), common.load_yaml(prices_path)
    price = cost_model.price_per_h(prices, cfg["instance_type"])
    strategies = cost_model.strategy_costs(d, price, model["match_hours"])
    cost = cost_model.compute(c1, cfg["instance_type"], model, prices, strategies)
    figs = sorted(p.stem for p in figures.glob("F*.png")) if figures.exists() else []
    pending = not d.by_exp
    made = {fid: {"runs": max((len(v) for v in d.by_exp.values()), default=0)} for fid in figs}
    caps = captions(d, c1, made)
    return {
        "generated_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "pending": pending,
        "c1": c1,
        "instance_type": cfg["instance_type"],
        "slo": cfg["slo"],
        "key_numbers": key_numbers(d, cost),
        "figures": [
            {
                "id": f,
                "title": make_plots.FIGURE_TITLES.get(f, "Cost and extrapolation"),
                "png": f"img/{f}.png",
                "caption": caps.get(f, ""),
            }
            for f in figs
        ],  # fmt: skip
        "series": series(d, c1),
        "cost": {
            "price_c6i_large": price,
            "spot_discount_pct": cost["spot_discount_pct"],
            "viewers_per_instance": cost["assumptions"]["viewers_per_instance"],
            "viewers_per_rps": model["viewers_per_rps"],
            "planning_utilisation": model["planning_utilisation"],
            "match_hours": model["match_hours"],
            "peaks": {k: v["peak_viewers"] for k, v in cost["peaks"].items()},
            "prices_retrieved": cost["prices_retrieved"],
            "strategies": strategies,
        },
    }


def export(results: Path, prefix: str, web: Path, figures: Path, model_path: Path, prices_path: Path) -> dict:
    res = build(results, prefix, model_path, prices_path, figures)
    (web / "data").mkdir(parents=True, exist_ok=True)
    (web / "img").mkdir(parents=True, exist_ok=True)
    (web / "data" / "results.json").write_text(json.dumps(res, indent=1) + "\n")
    for f in res["figures"]:
        shutil.copyfile(figures / f"{f['id']}.png", web / f["png"])
    return res


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--results", type=Path, default=common.RESULTS)
    ap.add_argument("--prefix", default="")
    ap.add_argument("--web", type=Path, default=common.ROOT / "web")
    ap.add_argument("--figures", type=Path, default=common.RESULTS / "figures")
    ap.add_argument("--model", type=Path, default=common.CONFIG_DIR / "model.yaml")
    ap.add_argument("--prices", type=Path, default=common.CONFIG_DIR / "prices.yaml")
    a = ap.parse_args(argv)
    r = export(a.results, a.prefix, a.web, a.figures, a.model, a.prices)
    state = (
        "pending (no analysed runs)"
        if r["pending"]
        else f"{len(r['figures'])} figures, {len(r['key_numbers'])} key numbers"
    )
    print(f"{a.web / 'data' / 'results.json'}: {state}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

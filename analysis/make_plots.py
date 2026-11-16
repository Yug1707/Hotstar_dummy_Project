#!/usr/bin/env python3
"""Figures F1-F6 from the committed summary.json / timeline.json files (plan section 8.4).

usage: make_plots.py [--results results] [--prefix ""] [--out results/figures] [--only F1,F2]

150 dpi PNG + SVG, one palette, every axis with units. A figure whose experiment has no data yet is
skipped with a message, so `make analyze` works at any point of the campaign.
--prefix FAKE_ reads the synthetic campaign from fake_campaign.py.
F7 (cost) is made by cost_model.py.
"""

from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

try:
    from analysis import common
except ImportError:  # run as a script
    import common  # type: ignore[no-redef]

PALETTE = {
    "reactive": "#d95f02",
    "proactive": "#1b9e77",
    "prewarm_only": "#7570b3",
    "ladder_only": "#e7298a",
    "naive": "#d95f02",
    "baked": "#1b9e77",
    "none": "#7f7f7f",
    "ssm_level1": "#7570b3",
    "auto_shed": "#1b9e77",
    "alb": "#d95f02",
    "cloudfront": "#1b9e77",
    "slo": "#c0392b",
    "ink": "#222222",
}
FIGURE_TITLES = {
    "F1": "Response time and capacity vs instance count",
    "F2": "Match-day spike: reactive vs proactive",
    "F3": "SLO violations and errors per strategy",
    "F4": "Time to ready: naive vs baked",
    "F5": "Graceful degradation under overload",
    "F6": "CDN offload: ALB vs CloudFront",
}


def style() -> None:
    plt.rcParams.update(
        {
            "figure.dpi": 100,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "axes.grid": True,
            "grid.alpha": 0.25,
            "font.size": 10,
            "axes.titlesize": 11,
        }
    )


class Data:
    """summary.json of every valid run, grouped by experiment folder name (prefix stripped)."""

    def __init__(self, results: Path, prefix: str = "") -> None:
        self.results, self.prefix = results, prefix
        self.by_exp: dict[str, list[dict]] = defaultdict(list)
        self.dirs: dict[tuple[str, int], Path] = {}
        for run in sorted(results.glob(f"{prefix}E*/run*")):
            f = run / "summary.json"
            if not f.exists():
                continue
            s = common.read_json(f)
            if s.get("valid") is False:
                continue
            exp = run.parent.name.removeprefix(prefix)
            self.by_exp[exp].append(s)
            self.dirs[(exp, int(s["run"]))] = run

    def get(self, exp: str) -> list[dict]:
        return self.by_exp.get(exp, [])

    def values(self, exp: str, getter) -> list[float]:
        out = []
        for s in self.get(exp):
            try:
                v = getter(s)
            except (KeyError, TypeError):
                v = None
            if v is not None:
                out.append(float(v))
        return out

    def median_run(self, exp: str, key: str = "slo_violation_s") -> dict | None:
        runs = sorted(self.get(exp), key=lambda s: s.get(key) or 0)
        return runs[len(runs) // 2] if runs else None


def med(xs: list[float]) -> float | None:
    return common.median(xs)


def whisker(ax, x, xs: list[float], color: str, **kw) -> None:
    """Median dot with a min-max whisker."""
    m = med(xs)
    if m is None:
        return
    ax.errorbar([x], [m], yerr=[[m - min(xs)], [max(xs) - m]], fmt="o", color=color, capsize=4, **kw)


def footer(fig, text: str) -> None:
    fig.get_layout_engine().set(rect=(0, 0.06, 1, 0.94))
    fig.text(0.01, 0.005, text, fontsize=7.5, color="#555", ha="left", va="bottom")


def save(fig, out: Path, name: str) -> None:
    out.mkdir(parents=True, exist_ok=True)
    fig.savefig(out / f"{name}.png", dpi=150, bbox_inches="tight")
    fig.savefig(out / f"{name}.svg", bbox_inches="tight")
    plt.close(fig)


def f1(d: Data, c1: float, slo: dict, out: Path) -> dict | None:
    ns = [n for n in range(1, 7) if d.get(f"E2a_N{n}")]
    if not ns:
        return None
    fig, (a, b) = plt.subplots(1, 2, figsize=(10, 4), constrained_layout=True)
    for q, col, lab in (("p50_ms", "#7fb3d5", "p50"), ("p95_ms", PALETTE["ink"], "p95"), ("p99_ms", "#c39bd3", "p99")):
        for n in ns:
            whisker(
                a, n, d.values(f"E2a_N{n}", lambda s, q=q: s["critical"][q]), col, markersize=6 if q == "p95" else 4
            )
        a.plot(ns, [med(d.values(f"E2a_N{n}", lambda s, q=q: s["critical"][q])) for n in ns], "-", color=col,
               label=lab, lw=2 if q == "p95" else 1.2)  # fmt: skip
    a.axhline(slo["critical_p95_ms"], color=PALETTE["slo"], ls="--", lw=1)
    a.text(
        ns[-1],
        slo["critical_p95_ms"] * 1.08,
        f"SLO p95 = {slo['critical_p95_ms']} ms",
        color=PALETTE["slo"],
        ha="right",
        fontsize=8,
    )
    a.set_yscale("log")
    a.set_xticks(ns)
    a.set_xlabel("instances in service (N)")
    a.set_ylabel("critical latency (ms, log)")
    a.set_title(f"A. Fixed load 2 x C1 = {2 * c1:g} rps")
    a.legend(loc="upper right", frameon=False)

    caps = {n: med(d.values(f"E2b_N{n}", lambda s: s.get("capacity_rps"))) for n in range(1, 7) if d.get(f"E2b_N{n}")}
    cn = sorted(caps)
    b.plot([1, max(ns + cn)], [c1, c1 * max(ns + cn)], "--", color="#888", label=f"ideal N x C1 (C1 = {c1:g})")
    if cn:
        b.plot(cn, [caps[n] for n in cn], "o-", color=PALETTE["proactive"], label="measured capacity at SLO")
    else:
        b.text(0.5, 0.5, "E2b pending", transform=b.transAxes, ha="center", color="#888")
    b.set_xlabel("instances in service (N)")
    b.set_ylabel("capacity at SLO (rps)")
    b.set_title("B. Scaling efficiency")
    b.legend(loc="upper left", frameon=False)
    runs = max(len(d.get(f"E2a_N{n}")) for n in ns)
    footer(fig, f"Median with min-max whisker, N = {runs} runs per point; C1 = {c1:g} rps (E1); c6i.large.")
    save(fig, out, "F1")
    return {"runs": runs}


def f2(d: Data, out: Path, slo: dict) -> dict | None:
    pairs = [("reactive", "E3"), ("proactive", "E4c")]
    series = {}
    for label, exp in pairs:
        s = d.median_run(exp)
        if not s:
            continue
        tl = d.dirs[(exp, int(s["run"]))] / "timeline.json"
        meta = d.dirs[(exp, int(s["run"]))] / "meta.json"
        if tl.exists():
            series[label] = (common.read_json(tl), common.read_json(meta).get("events_s") or {}, s)
    if len(series) < 2:
        return None
    fig, ax = plt.subplots(figsize=(10, 4.2), constrained_layout=True)
    ax2 = ax.twinx()
    ax2.spines["right"].set_visible(True)
    ev = next(iter(series.values()))[1]
    if ev.get("ramp"):
        ax.axvspan(*ev["ramp"], color="#f1c40f", alpha=0.15, label="ramp (90 s)")
    for i, (a_, b_) in enumerate(ev.get("bursts") or []):
        ax.axvspan(a_, b_, color="#e74c3c", alpha=0.10, label="wicket burst" if i == 0 else None)
    for label, (tl, _, s) in series.items():
        t = tl["t"]
        ax.plot(t, [v if v is not None else float("nan") for v in tl["p95_ms"]], color=PALETTE[label], lw=1.6,
                label=f"{label} p95 ({s['slo_violation_s']} SLO-violation s)")  # fmt: skip
        ax2.step(t, [v if v is not None else float("nan") for v in tl["healthy"]], where="post", color=PALETTE[label],
                 ls=":", lw=1.4)  # fmt: skip
    ax.axhline(slo["critical_p95_ms"], color=PALETTE["slo"], ls="--", lw=1)
    ax.set_yscale("log")
    ax.set_xlabel("time since k6 start (s)")
    ax.set_ylabel("critical p95 (ms, log)")
    ax2.set_ylabel("healthy instances (dotted)")
    ax2.grid(False)
    ax.legend(loc="upper left", frameon=False, fontsize=8)
    ax.set_title("Reactive vs proactive (c), median run of each")
    n = len(d.get("E3"))
    footer(fig, f"N = {n} runs per strategy, median run by SLO-violation seconds shown.")
    save(fig, out, "F2")
    return {"runs": n}


def f3(d: Data, out: Path) -> dict | None:
    arms = [("reactive", "E3"), ("prewarm_only", "E4a"), ("ladder_only", "E4b"), ("proactive", "E4c")]
    arms = [(lab, e) for lab, e in arms if d.get(e)]
    if len(arms) < 2:
        return None
    labels = {"reactive": "reactive\n(E3)", "prewarm_only": "pre-warm only\n(E4a)", "ladder_only": "ladder only\n(E4b)",
              "proactive": "pre-warm + ladder\n(E4c)"}  # fmt: skip
    fig, (a, b) = plt.subplots(1, 2, figsize=(10, 4), constrained_layout=True)
    for i, (lab, exp) in enumerate(arms):
        v = d.values(exp, lambda s: s["slo_violation_s"])
        e = [x * 100 for x in d.values(exp, lambda s: s["critical"]["error_rate"])]
        a.bar(i, med(v), color=PALETTE[lab], alpha=0.85)
        whisker(a, i, v, PALETTE["ink"], markersize=3)
        b.bar(i, med(e), color=PALETTE[lab], alpha=0.85)
        whisker(b, i, e, PALETTE["ink"], markersize=3)
    for ax in (a, b):
        ax.set_xticks(range(len(arms)), [labels[lab] for lab, _ in arms], fontsize=8)
    a.set_ylabel("SLO-violation seconds (s)")
    a.set_title("A. Seconds out of SLO")
    b.set_ylabel("critical error rate (%)")
    b.set_title("B. Errors")
    footer(fig, "Bar = median; whisker = min-max of the runs (E3, E4c: 3 runs; E4a, E4b: 1 run, no whisker).")
    save(fig, out, "F3")
    return {"runs": max(len(d.get(e)) for _, e in arms)}


def f4(d: Data, out: Path) -> dict | None:
    if not (d.get("E5_naive") and d.get("E5_baked")):
        return None
    fig, ax = plt.subplots(figsize=(9, 3.6), constrained_layout=True)
    ypos, ylab = 0, []
    for label in ("baked", "naive"):
        insts = [i for s in d.get(f"E5_{label}") for i in s["instances"]]
        for i in sorted(insts, key=lambda x: x["launch_to_healthy_s"]):
            ax.barh(ypos, i["launch_to_in_service_s"], color="#bbbbbb", height=0.7)
            ax.barh(
                ypos, i["in_service_to_healthy_s"], left=i["launch_to_in_service_s"], color=PALETTE[label], height=0.7
            )
            ypos += 1
        ylab.append((ypos - len(insts) / 2 - 0.5, f"{label} (n={len(insts)})"))
        ypos += 1
    ax.axvline(90, color=PALETTE["slo"], ls="--", lw=1)
    ax.text(91, ypos - 1, "Hotstar's ~90 s window", color=PALETTE["slo"], fontsize=8, va="top")
    ax.set_yticks([y for y, _ in ylab], [t for _, t in ylab])
    ax.set_xlabel("seconds after launch (grey: launch to InService; colour: InService to first healthy)")
    ax.grid(False, axis="y")
    ax.set_title("Each bar is one new instance")
    footer(fig, f"E5: scale 1 to 5, {len(d.get('E5_baked'))} runs per AMI mode, monitor at 2 s.")
    save(fig, out, "F4")
    return {"runs": len(d.get("E5_baked"))}


def f5(d: Data, out: Path, slo: dict) -> dict | None:
    arms = [v for v in ("none", "ssm_level1", "auto_shed") if d.get(f"E6_{v}")]
    if len(arms) < 2:
        return None
    names = {"none": "no degradation", "ssm_level1": "degrade level 1\n(SSM)", "auto_shed": "auto-shed"}
    fig, (a, b) = plt.subplots(1, 2, figsize=(10, 4), constrained_layout=True)
    for i, v in enumerate(arms):
        p95 = d.values(f"E6_{v}", lambda s: s["critical"]["p95_ms"])
        shed = d.values(f"E6_{v}", lambda s: s.get("shed_total"))
        a.bar(i, med(p95), color=PALETTE[v], alpha=0.85)
        whisker(a, i, p95, PALETTE["ink"], markersize=3)
        if shed:
            b.bar(i, med(shed), color=PALETTE[v], alpha=0.85)
            whisker(b, i, shed, PALETTE["ink"], markersize=3)
    a.axhline(slo["critical_p95_ms"], color=PALETTE["slo"], ls="--", lw=1)
    a.set_yscale("log")
    a.set_ylabel("critical p95 (ms, log)")
    a.set_title("A. Critical latency at 3 x C1 on 2 instances")
    b.set_ylabel("requests shed (count)")
    b.set_title("B. Non-critical work dropped")
    for ax in (a, b):
        ax.set_xticks(range(len(arms)), [names[v] for v in arms], fontsize=8)
    footer(
        fig,
        f"Bar = median, whisker = min-max of {len(d.get(f'E6_{arms[0]}'))} runs; shedding spares critical requests.",
    )
    save(fig, out, "F5")
    return {"runs": len(d.get(f"E6_{arms[0]}"))}


def f6(d: Data, out: Path) -> dict | None:
    if not (d.get("E7_alb") and d.get("E7_cloudfront")):
        return None
    fig, (a, b) = plt.subplots(1, 2, figsize=(9, 3.8), constrained_layout=True)
    for i, t in enumerate(("alb", "cloudfront")):
        o = d.values(f"E7_{t}", lambda s: s.get("origin_requests"))
        p = d.values(f"E7_{t}", lambda s: s["by_class"]["public"]["p95_ms"])
        if o:
            a.bar(i, med(o), color=PALETTE[t], alpha=0.85)
            whisker(a, i, o, PALETTE["ink"], markersize=3)
        if p:
            b.bar(i, med(p), color=PALETTE[t], alpha=0.85)
            whisker(b, i, p, PALETTE["ink"], markersize=3)
    a.set_yscale("log")
    a.set_ylabel("requests reaching the origin (count, log)")
    a.set_title("A. Origin load")
    b.set_ylabel("client p95 of /match/state (ms)")
    b.set_title("B. What the viewer sees")
    for ax in (a, b):
        ax.set_xticks([0, 1], ["ALB direct", "CloudFront"])
    footer(fig, f"Same load (match state only, 3 x C1, 3 min); median and min-max of {len(d.get('E7_alb'))} runs.")
    save(fig, out, "F6")
    return {"runs": len(d.get("E7_alb"))}


def make_all(results: Path, prefix: str, out: Path, only: set[str] | None = None) -> dict[str, dict]:
    style()
    cfg = common.global_cfg()
    slo = cfg["slo"]
    d = Data(results, prefix)
    # C1 of the runs that were actually analysed (the yaml value can move after a re-calibration)
    c1 = med([s["c1"] for s in d.get("E2a_N1") + d.get("E1") if s.get("c1")]) or float(cfg["c1"])
    jobs = {
        "F1": lambda: f1(d, c1, slo, out),
        "F2": lambda: f2(d, out, slo),
        "F3": lambda: f3(d, out),
        "F4": lambda: f4(d, out),
        "F5": lambda: f5(d, out, slo),
        "F6": lambda: f6(d, out),
    }
    made = {}
    for fid, job in jobs.items():
        if only and fid not in only:
            continue
        info = job()
        if info is None:
            print(f"{fid}: skipped (no data yet)")
        else:
            made[fid] = info
            print(f"{fid}: {out / (fid + '.png')}")
    return made


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--results", type=Path, default=common.RESULTS)
    ap.add_argument("--prefix", default="")
    ap.add_argument("--out", type=Path, default=common.RESULTS / "figures")
    ap.add_argument("--only", default="")
    a = ap.parse_args(argv)
    only = {x.strip() for x in a.only.split(",") if x.strip()} or None
    make_all(a.results, a.prefix, a.out, only)
    return 0


if __name__ == "__main__":
    sys.exit(main())

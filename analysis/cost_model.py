#!/usr/bin/env python3
"""E8 cost model and F7 (plan section 8.5).

usage: cost_model.py [--results results] [--prefix ""] [--prices config/prices.yaml] [--model config/model.yaml]
                     [--out results/E8] [--figures results/figures]

Formulas (every intermediate value is printed):
  viewers_per_instance = C1 x planning_utilisation x viewers_per_rps
  instances(peak)      = ceil(peak / viewers_per_instance)
  strategy_cost_match  = (measured instance-minutes / measured window minutes) x match_hours x price_per_h
  always_on_cost_24h   = instances(peak) x 24 x price_per_h
  spot_cost            = cost x (1 - spot_share x spot_discount)
  hulk_cost            = vcpus x hours x price_per_h / vcpus_per_instance

No price is stored in code: prices come from config/prices.yaml. With a null price the cost fields are null and
only the instance counts are produced.
Out of scope (listed under every table): CDN and egress, databases, caches, Kubernetes control plane, support, people.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

try:
    from analysis import common, make_plots
except ImportError:  # run as a script
    import common  # type: ignore[no-redef]
    import make_plots  # type: ignore[no-redef]

OUT_OF_SCOPE = "CDN and egress, databases, caches, Kubernetes control plane, support, people"
STRATEGIES = [("E3", "reactive"), ("E4a", "pre-warm only"), ("E4b", "ladder only"), ("E4c", "pre-warm + ladder")]


def viewers_per_instance(c1: float, utilisation: float, viewers_per_rps: float) -> float:
    return c1 * utilisation * viewers_per_rps


def instances_for(peak: float, per_instance: float) -> int:
    return math.ceil(peak / per_instance)


def spot_cost(cost: float | None, share: float, discount_pct: float | None) -> float | None:
    if cost is None or discount_pct is None:
        return None
    return cost * (1 - share * discount_pct / 100.0)


def price_per_h(prices: dict, itype: str) -> float | None:
    return (prices.get("ec2_on_demand_usd_per_h") or {}).get(itype)


def strategy_costs(d: make_plots.Data, price: float | None, match_hours: float) -> list[dict]:
    rows = []
    for exp, label in STRATEGIES:
        runs = d.get(exp)
        if not runs:
            continue
        im = common.median([s["instance_minutes"] for s in runs])
        window_min = common.median([s["duration_s"] / 60.0 + 5.0 for s in runs])  # + observe_s (300 s)
        avg_inst = im / window_min
        rows.append(
            {
                "exp": exp,
                "strategy": label,
                "runs": len(runs),
                "instance_minutes_measured": round(im, 2),
                "window_min": round(window_min, 2),
                "avg_instances": round(avg_inst, 3),
                "cost_match_usd": None if price is None else round(avg_inst * match_hours * price, 4),
                "slo_violation_s": common.median([s["slo_violation_s"] for s in runs]),
            }
        )
    base = next((r for r in rows if r["exp"] == "E3"), None)
    for r in rows:
        r["extra_instance_minutes_pct_vs_reactive"] = (
            round(100 * (r["instance_minutes_measured"] / base["instance_minutes_measured"] - 1), 1) if base else None
        )
    return rows


def compute(c1: float, itype: str, model: dict, prices: dict, strategies: list[dict]) -> dict:
    price = price_per_h(prices, itype)
    discount = (prices.get("spot_discount_pct") or {}).get(itype)
    util, vpr = model["planning_utilisation"], model["viewers_per_rps"]
    vpi = viewers_per_instance(c1, util, vpr)
    peaks = {}
    for name, peak in model["peaks"].items():
        n = instances_for(peak, vpi)
        always_on = None if price is None else n * 24 * price
        match = None if price is None else n * model["match_hours"] * price
        peaks[name] = {
            "peak_viewers": peak,
            "instances": n,
            "always_on_24h_usd": always_on,
            "peak_hours_match_usd": match,
            "spot": {str(sh): spot_cost(match, sh, discount) for sh in model["spot_shares"]},
        }
    sens = []
    peak = max(model["peaks"].values())
    for v in model["sensitivity_viewers_per_rps"]:
        per = viewers_per_instance(c1, util, v)
        n = instances_for(peak, per)
        for sh in model["spot_shares"]:
            match = None if price is None else n * model["match_hours"] * price
            sens.append(
                {"viewers_per_rps": v, "spot_share": sh, "instances": n, "match_usd": spot_cost(match, sh, discount)}
            )
    per_vcpu = vcpu_count = None
    if price is not None:
        vcpu_count = model["vcpus_per_instance"][itype]
        per_vcpu = price / vcpu_count
    hulk = model["hulk"]
    hulk_cost = None if per_vcpu is None else hulk["vcpus"] * hulk["test_hours"] * per_vcpu
    return {
        "instance_type": itype,
        "c1": c1,
        "price_usd_per_h": price,
        "spot_discount_pct": discount,
        "assumptions": {
            "viewers_per_rps": vpr,
            "planning_utilisation": util,
            "viewers_per_instance": vpi,
            "match_hours": model["match_hours"],
            "out_of_scope": OUT_OF_SCOPE,
        },
        "strategies": strategies,
        "peaks": peaks,
        "sensitivity_peak_viewers": peak,
        "sensitivity": sens,
        "hulk": {
            "vcpus": hulk["vcpus"],
            "hours": hulk["test_hours"],
            "vcpus_per_instance": vcpu_count,
            "cost_usd": hulk_cost,
        },  # fmt: skip
        "prices_retrieved": prices.get("retrieved"),
        "prices_source": prices.get("source"),
    }


def money(x: float | None) -> str:
    return "price missing" if x is None else f"${x:,.2f}"


def markdown(r: dict) -> str:
    a = r["assumptions"]
    price_txt = "not set" if r["price_usd_per_h"] is None else money(r["price_usd_per_h"]) + "/h"
    out = [
        "# E8: cost model",
        "",
        f"Instance **{r['instance_type']}**, C1 = {r['c1']:g} rps, price {price_txt} "
        f"(retrieved {r['prices_retrieved'] or 'n/a'}).",
        f"viewers per instance = C1 x {a['planning_utilisation']} x {a['viewers_per_rps']} = "
        f"**{a['viewers_per_instance']:,.0f}**.",
        "",
        "## Strategies (cost of a 4-hour match, from the measured spike runs)",
        "",
        "| Strategy | Runs | Instance-minutes | Avg instances | SLO-violation s | vs reactive | Cost / match |",
        "|---|---|---|---|---|---|---|",
    ]
    for s in r["strategies"]:
        pct = s["extra_instance_minutes_pct_vs_reactive"]
        out.append(
            f"| {s['strategy']} | {s['runs']} | {s['instance_minutes_measured']} | {s['avg_instances']} | "
            f"{s['slo_violation_s']} | {'+' if pct and pct > 0 else ''}{pct}% | {money(s['cost_match_usd'])} |"
        )
    out += ["", "## Instances needed at each peak", "", "| Peak | Viewers | Instances | Always-on 24 h | 4-h match |",
            "|---|---|---|---|---|"]  # fmt: skip
    for name, p in r["peaks"].items():
        out.append(
            f"| {name} | {p['peak_viewers'] / 1e6:g} M | {p['instances']:,} | {money(p['always_on_24h_usd'])} | "
            f"{money(p['peak_hours_match_usd'])} |"
        )
    out += ["", f"## Sensitivity at {r['sensitivity_peak_viewers'] / 1e6:g} M viewers", "",
            "| Viewers per rps | Spot share | Instances | 4-h match |", "|---|---|---|---|"]  # fmt: skip
    for s in r["sensitivity"]:
        out.append(f"| {s['viewers_per_rps']} | {s['spot_share']:.0%} | {s['instances']:,} | {money(s['match_usd'])} |")
    h = r["hulk"]
    out += ["", f"HULK-style load test: {h['vcpus']:,} vCPU x {h['hours']} h = {money(h['cost_usd'])}.", "",
            f"Out of scope: {a['out_of_scope']}. Spot share 70 % is an unverified claim being tested.", ""]  # fmt: skip
    return "\n".join(out)


def f7(r: dict, figures: Path) -> None:
    import matplotlib.pyplot as plt

    make_plots.style()
    fig, (a, b) = plt.subplots(1, 2, figsize=(10, 4), constrained_layout=True)
    strat = [s for s in r["strategies"] if s["cost_match_usd"] is not None]
    if strat:
        cols = {"reactive": "reactive", "pre-warm + ladder": "proactive", "pre-warm only": "prewarm_only",
                "ladder only": "ladder_only"}  # fmt: skip
        for i, s in enumerate(strat):
            a.bar(i, s["cost_match_usd"], color=make_plots.PALETTE[cols[s["strategy"]]], alpha=0.85)
        a.set_xticks(range(len(strat)), [s["strategy"].replace(" + ", "\n+ ") for s in strat], fontsize=8)
        a.set_ylabel("cost of a 4-hour match (USD, test scale)")
    else:
        a.text(0.5, 0.5, "price missing\n(fill config/prices.yaml)", ha="center", transform=a.transAxes, color="#888")
        a.set_xticks([])
    a.set_title("A. Cost per strategy")
    names = list(r["peaks"])
    b.bar(range(len(names)), [r["peaks"][n]["instances"] for n in names], color="#4c78a8")
    b.set_yscale("log")
    b.set_xticks(range(len(names)), [f"{r['peaks'][n]['peak_viewers'] / 1e6:g} M" for n in names])
    b.set_xlabel("concurrent viewers")
    b.set_ylabel(f"{r['instance_type']} instances needed (log)")
    for i, n in enumerate(names):
        b.text(i, r["peaks"][n]["instances"], f"{r['peaks'][n]['instances']:,}", ha="center", va="bottom", fontsize=8)
    b.set_title("B. Fleet size at each peak")
    a_ = r["assumptions"]
    make_plots.footer(
        fig,
        f"C1 = {r['c1']:g} rps, utilisation {a_['planning_utilisation']}, {a_['viewers_per_rps']} viewers per rps "
        f"(derived, not measured). Out of scope: {a_['out_of_scope']}.",
    )
    make_plots.save(fig, figures, "F7")


def run(results: Path, prefix: str, prices_path: Path, model_path: Path, out: Path, figures: Path) -> dict:
    model, prices = common.load_yaml(model_path), common.load_yaml(prices_path)
    cfg = common.global_cfg()
    d = make_plots.Data(results, prefix)
    c1 = common.median([s["c1"] for s in d.get("E1") + d.get("E2a_N1") if s.get("c1")]) or float(cfg["c1"])
    r = compute(c1, cfg["instance_type"], model, prices, strategy_costs(d, price_per_h(prices, cfg["instance_type"]),
                                                                        model["match_hours"]))  # fmt: skip
    out.mkdir(parents=True, exist_ok=True)
    (out / "summary.json").write_text(json.dumps(r, indent=1) + "\n")
    (out / "cost.md").write_text(markdown(r))
    f7(r, figures)
    return r


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--results", type=Path, default=common.RESULTS)
    ap.add_argument("--prefix", default="")
    ap.add_argument("--prices", type=Path, default=common.CONFIG_DIR / "prices.yaml")
    ap.add_argument("--model", type=Path, default=common.CONFIG_DIR / "model.yaml")
    ap.add_argument("--out", type=Path, default=common.RESULTS / "E8")
    ap.add_argument("--figures", type=Path, default=common.RESULTS / "figures")
    a = ap.parse_args(argv)
    r = run(a.results, a.prefix, a.prices, a.model, a.out, a.figures)
    print(markdown(r))
    return 0


if __name__ == "__main__":
    sys.exit(main())

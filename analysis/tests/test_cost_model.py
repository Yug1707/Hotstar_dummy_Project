from __future__ import annotations

import pytest

from analysis import common, cost_model, fake_campaign, parse_k6

# the lab instance type from harness/experiments.yaml, so the fake campaign and the prices agree
ITYPE = common.global_cfg()["instance_type"]

MODEL = {
    "viewers_per_rps": 25,
    "planning_utilisation": 0.8,
    "peaks": {"a": 10e6, "b": 59e6},
    "match_hours": 4,
    "spot_shares": [0.0, 0.5],
    "sensitivity_viewers_per_rps": [10, 25],
    "vcpus_per_instance": {ITYPE: 2},
    "hulk": {"vcpus": 1000, "test_hours": 1},
}
# test-only numbers, not AWS prices
PRICES = {"ec2_on_demand_usd_per_h": {ITYPE: 0.10}, "spot_discount_pct": {ITYPE: 60}}


def test_formulas():
    assert cost_model.viewers_per_instance(100, 0.8, 25) == 2000
    assert cost_model.instances_for(59e6, 2000) == 29_500
    assert cost_model.instances_for(10.3e6, 2000) == 5150
    assert cost_model.spot_cost(10.0, 0.5, 60) == pytest.approx(7.0)
    assert cost_model.spot_cost(None, 0.5, 60) is None


def test_compute_with_prices():
    r = cost_model.compute(100, ITYPE, MODEL, PRICES, [])
    assert r["peaks"]["b"]["instances"] == 29_500
    assert r["peaks"]["b"]["always_on_24h_usd"] == pytest.approx(29_500 * 24 * 0.10)
    assert r["peaks"]["b"]["spot"]["0.5"] == pytest.approx(29_500 * 4 * 0.10 * 0.7)
    assert r["hulk"]["cost_usd"] == pytest.approx(1000 * 0.05)
    # sensitivity: fewer viewers per rps means more instances
    by = {(s["viewers_per_rps"], s["spot_share"]): s["instances"] for s in r["sensitivity"]}
    assert by[(10, 0.0)] > by[(25, 0.0)]


def test_missing_price_keeps_instance_counts():
    r = cost_model.compute(100, ITYPE, MODEL, {}, [])
    assert r["peaks"]["b"]["instances"] == 29_500
    assert r["peaks"]["b"]["always_on_24h_usd"] is None
    assert r["hulk"]["cost_usd"] is None
    assert "price missing" in cost_model.markdown(r)


def test_strategy_costs_from_fake_campaign(tmp_path):
    res = tmp_path / "results"
    fake_campaign.main(["--out", str(res), "--runs", "1"])
    cfg = common.global_cfg()
    for run in common.run_dirs(res, "FAKE_E*"):
        parse_k6.parse_any(run, cfg, force=True)
    import yaml

    (tmp_path / "prices.yaml").write_text(yaml.safe_dump(PRICES))
    (tmp_path / "model.yaml").write_text(yaml.safe_dump(MODEL))
    r = cost_model.run(
        res, "FAKE_", tmp_path / "prices.yaml", tmp_path / "model.yaml", tmp_path / "E8", tmp_path / "fig"
    )
    names = {s["exp"]: s for s in r["strategies"]}
    assert names["E4c"]["avg_instances"] > names["E3"]["avg_instances"]  # the price of safety
    assert names["E4c"]["cost_match_usd"] > names["E3"]["cost_match_usd"]
    assert (tmp_path / "E8" / "summary.json").exists() and (tmp_path / "E8" / "cost.md").exists()
    assert (tmp_path / "fig" / "F7.png").stat().st_size > 5000

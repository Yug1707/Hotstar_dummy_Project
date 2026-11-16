from __future__ import annotations

import json

import pytest

from analysis import common, fake_run, parse_k6

SLO = {"critical_p95_ms": 300, "error_rate": 0.01}


@pytest.fixture(scope="module")
def runs(tmp_path_factory):
    out = tmp_path_factory.mktemp("results")
    return {
        "reactive": fake_run.make_run(out, "FAKE_E3", 1, "spike", "reactive", 1, 100, 1),
        "proactive": fake_run.make_run(out, "FAKE_E4c", 1, "spike", "proactive", 4, 100, 1),
        "fixed1": fake_run.make_run(out, "FAKE_E2a_N1", 1, "fixed", "static", 1, 100, 1),
        "fixed4": fake_run.make_run(out, "FAKE_E2a_N4", 1, "fixed", "static", 4, 100, 1),
        "step": fake_run.make_run(out, "FAKE_E1", 1, "step", "static", 1, 100, 1),
    }


def test_reactive_run_violates_slo_and_is_late(runs):
    s = parse_k6.parse_run(runs["reactive"], SLO, 30)
    assert s["slo_violation_s"] > 60
    assert s["critical"]["p95_ms"] > 300
    # capacity arrives ~ alarm lag (180 s) + boot (150 s) after the ramp starts
    assert 280 <= s["time_to_first_new_instance_s"] <= 380
    assert s["peak_instances"] == 6
    assert s["instance_minutes"] > 40


def test_proactive_run_stays_inside_slo(runs):
    s = parse_k6.parse_run(runs["proactive"], SLO, 30)
    assert s["slo_violation_s"] == 0
    assert s["critical"]["p95_ms"] < 300
    # the pre-warmed floor already carries the ramp; the ladder only adds the burst headroom
    assert s["time_to_first_new_instance_s"] <= 200


def test_proactive_costs_more_instance_minutes_than_reactive(runs):
    r = json.loads((runs["reactive"] / "summary.json").read_text())
    p = parse_k6.parse_run(runs["proactive"], SLO, 30)
    assert p["instance_minutes"] > r["instance_minutes"]


def test_fixed_rate_saturates_one_instance_only(runs):
    one = parse_k6.parse_run(runs["fixed1"], SLO, 30)
    four = parse_k6.parse_run(runs["fixed4"], SLO, 30)
    assert one["critical"]["p95_ms"] > 300 and one["critical"]["error_rate"] > 0.01
    assert four["critical"]["p95_ms"] < 300
    assert four["slo_violation_s"] == 0


def test_step_profile_finds_the_knee(runs):
    s = parse_k6.parse_run(runs["step"], SLO, 30)
    assert len(s["steps"]) == 10
    # one instance with c1=100: steps up to ~0.8*c1 pass, higher ones do not
    assert 70 <= s["capacity_rps"] <= 100
    assert not s["steps"][-1]["ok"]


def test_aggregates_schema(runs):
    import pandas as pd

    agg = pd.read_csv(runs["reactive"] / "aggregates.csv.gz")
    assert list(agg.columns) == ["sec", "cls", "count", "p50", "p95", "p99", "err_rate", "rps"]
    assert set(agg["cls"]) == {"critical", "public", "noncritical"}
    assert (agg["p50"] <= agg["p95"]).all() and (agg["p95"] <= agg["p99"]).all()


def test_warmup_discarded_for_fixed_not_spike(runs):
    # fixed: first 30 s ramp is dropped; the summary counts only judged critical requests
    s = parse_k6.parse_run(runs["fixed4"], SLO, 30)
    assert s["profile"] == "fixed"
    assert s["throughput_rps_max"] >= 150


def test_summary_is_idempotent_and_fresh(runs):
    run = runs["proactive"]
    assert parse_k6.is_fresh(run)
    assert parse_k6.parse_any(run, common.global_cfg()) is None  # skipped
    assert parse_k6.parse_any(run, common.global_cfg(), force=True) is not None


def test_parse_boot(tmp_path):
    d = tmp_path / "E5_baked" / "run1"
    d.mkdir(parents=True)
    (d / "meta.json").write_text(
        json.dumps(
            {
                "exp": "E5_baked",
                "run": 1,
                "valid": True,
                "profile": "none",
                "label": "baked",
                "new_instances": ["i-a", "i-b"],
                "all_healthy_s": 95.0,
            }
        )  # fmt: skip
    )
    (d / "instances.csv").write_text(
        "instance_id,az,launch_time,first_seen_ts,in_service_ts,first_healthy_ts,terminated_ts\n"
        "i-a,a,100,101,130,160,\n"
        "i-b,b,100,101,135,170,\n"
        "i-old,a,0,1,2,3,\n"
    )
    s = parse_k6.parse_boot(d)
    assert [i["launch_to_healthy_s"] for i in s["instances"]] == [60.0, 70.0]
    assert s["median_launch_to_healthy_s"] == 65.0

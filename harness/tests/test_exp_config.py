import shlex

import pytest

import collect_cw
import common
import exp_config
from fakes import FakeCW


def test_evaluate_arithmetic_only():
    assert exp_config.evaluate("2.0*c1*N", {"c1": 100, "N": 3}) == 600
    assert exp_config.evaluate(150, {}) == 150
    for bad in ("__import__('os')", "c1.real", "2**10", "N"):
        with pytest.raises((ValueError, SyntaxError)):
            exp_config.evaluate(bad, {"c1": 1})


def test_real_config_every_entry_resolves():
    cfg = exp_config.load()
    assert cfg["global"]["c1"] > 0
    for name, e in cfg["experiments"].items():
        choices = e.get("mode_sweep") or e.get("variants") or [None]
        for arg in choices:
            cmd = exp_config.command(cfg, name, 1, None if arg is None else str(arg))
            assert cmd[0] in ("run_experiment.sh", "boot_test.sh")


def test_sweep_and_variants():
    cfg = {
        "global": {"c1": 100},
        "experiments": {
            "E2a": {"mode_sweep": [1, 2, 3], "profile": "fixed", "env": {"FIXED_RPS": "2.0*c1"}},
            "E2b": {"mode_sweep": [1, 2, 3], "profile": "step", "env": {"GUESS": "1.0*c1*N"}},
            "E6": {
                "mode": "static 2",
                "profile": "fixed",
                "env": {"FIXED_RPS": "3.0*c1"},
                "variants": ["none", "ssm_level1", "auto_shed"],
            },
            "E7": {
                "mode": "static 2",
                "profile": "fixed",
                "env": {"MIX": "match_only", "HOLD": "3m"},
                "variants": ["alb", "cloudfront"],
            },
            "E5": {"boot_test": {"from": 1, "to": 5}, "variants": ["naive", "baked"]},
        },
    }
    assert exp_config.command(cfg, "E2a", 2, "3") == [
        "run_experiment.sh",
        "E2a_N3",
        "2",
        "static 3",
        "fixed",
        "FIXED_RPS=200",
    ]
    assert exp_config.command(cfg, "E2b", 1, "2")[-1] == "GUESS=200"
    assert exp_config.command(cfg, "E6", 1, "auto_shed")[:3] == ["run_experiment.sh", "--auto-shed", "E6_auto_shed"]
    assert exp_config.command(cfg, "E6", 1, "ssm_level1")[1:3] == ["--degrade", "1"]
    e7 = exp_config.command(cfg, "E7", 3, "cloudfront")
    assert e7[1:4] == ["--target", "cloudfront", "E7_cloudfront"] and "MIX=match_only" in e7 and "HOLD=3m" in e7
    assert exp_config.command(cfg, "E5", 1, "naive") == [
        "boot_test.sh",
        "--label",
        "naive",
        "--from",
        "1",
        "--to",
        "5",
        "E5_naive",
        "1",
    ]
    with pytest.raises(SystemExit):
        exp_config.command(cfg, "E2a", 1, None)  # sweep needs N
    with pytest.raises(SystemExit):
        exp_config.command(cfg, "E9", 1)


def test_cmd_output_is_shell_safe(capsys):
    assert exp_config.main(["cmd", "E4c", "1"]) == 0
    line = capsys.readouterr().out.strip()
    assert shlex.split(line)[3] == "proactive --prewarm 3"


# ---- collect_cw ----------------------------------------------------------------------------------
ENV = common.Env(
    region="ap-south-1",
    asg_name="hsl-asg",
    tg_arn="arn:tg",
    tg_suffix="targetgroup/hsl-tg/1",
    alb_suffix="app/hsl-alb/2",
)


def test_metric_specs_cover_plan_table():
    specs = collect_cw.metric_specs(ENV)
    assert len(specs) == 14
    assert {s["stat"] for s in specs if s["metric"] == "TargetResponseTime"} == {"p50", "p95", "p99"}
    hh = next(s for s in specs if s["metric"] == "HealthyHostCount")
    assert [d["Name"] for d in hh["dims"]] == ["TargetGroup", "LoadBalancer"]
    no_suffix = common.Env(region="ap-south-1", asg_name="hsl-asg", tg_arn="arn:tg")
    assert {s["namespace"] for s in collect_cw.metric_specs(no_suffix)} == {"AWS/EC2", "AWS/AutoScaling"}


def test_fetch_paginates_and_writes(tmp_path):
    qs = collect_cw.queries(collect_cw.metric_specs(ENV), 60)
    assert len({q["Id"] for q in qs}) == len(qs)
    series = collect_cw.fetch(FakeCW(), qs, 1_000_000.0, 1_000_600.0)
    assert all(len(v) == 2 for v in series.values())  # two pages merged
    assert collect_cw.write(tmp_path, series) == 14
    lines = (tmp_path / "alb_request_count_sum.csv").read_text().splitlines()
    assert lines[0] == "ts,value" and len(lines) == 3

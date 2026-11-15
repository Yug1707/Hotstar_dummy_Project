from datetime import UTC, datetime

import pytest

import asg_mode
from fakes import FakeASG


def run(asg, mode, *args):
    desired, policies, scheduled = asg_mode.apply(asg, "hsl-asg", mode, list(args))
    cfg = asg_mode.snapshot(asg, "hsl-asg")
    return desired, asg_mode.self_check(cfg, policies, scheduled), cfg


def test_static_sets_min_max_desired():
    asg = FakeASG()
    desired, errs, cfg = run(asg, "static", "3")
    assert desired == 3 and errs == []
    assert (cfg["min"], cfg["max"], cfg["desired"]) == (3, 3, 3)


@pytest.mark.parametrize("n", ["0", "7"])
def test_static_rejects_out_of_range(n):
    with pytest.raises(SystemExit):
        asg_mode.apply(FakeASG(), "hsl-asg", "static", [n])


def test_reactive_installs_exactly_cpu50():
    asg = FakeASG()
    asg.policies["leftover"] = {}
    desired, errs, cfg = run(asg, "reactive")
    assert desired == 1 and errs == []
    assert cfg["policies"] == ["cpu50"] and (cfg["min"], cfg["max"]) == (1, 6)
    pol = asg.policies["cpu50"]
    assert pol["PolicyType"] == "TargetTrackingScaling"
    assert pol["TargetTrackingConfiguration"]["TargetValue"] == 50.0
    assert pol["EstimatedInstanceWarmup"] == 120


def test_proactive_has_no_policies():
    asg = FakeASG()
    asg.policies["cpu50"] = {}
    _, errs, cfg = run(asg, "proactive")
    assert errs == [] and cfg["policies"] == [] and cfg["max"] == 6


def test_scheduled_adds_reactive_and_one_action():
    asg = FakeASG()
    _, errs, cfg = run(asg, "scheduled", "2026-11-18T10:44:05Z", "4")
    assert errs == []
    assert cfg["policies"] == ["cpu50"] and cfg["scheduled_actions"] == ["hsl-prewarm"]
    a = asg.scheduled["hsl-prewarm"]
    assert a["StartTime"] == datetime(2026, 11, 18, 10, 44, 5, tzinfo=UTC)
    assert (a["MinSize"], a["DesiredCapacity"]) == (4, 4)


def test_static_reactive_reset_leaves_nothing_attached():
    """Phase 3 acceptance: static 3 -> reactive -> reset leaves describe-policies empty."""
    asg = FakeASG()
    run(asg, "static", "3")
    run(asg, "reactive")
    _, errs, cfg = run(asg, "reset")
    assert errs == []
    assert cfg["policies"] == [] and cfg["scheduled_actions"] == []
    assert (cfg["min"], cfg["max"], cfg["desired"]) == (1, 6, 1)


def test_desired_only_changes_desired():
    asg = FakeASG()
    run(asg, "proactive")
    asg.calls.clear()
    desired, errs, cfg = run(asg, "desired", "5")
    assert desired == 5 and errs == []
    assert [c[0] for c in asg.calls] == ["set_desired"]
    assert (cfg["min"], cfg["max"]) == (1, 6)


def test_self_check_reports_unexpected_policy():
    cfg = {"policies": ["cpu50", "rogue"], "scheduled_actions": []}
    errs = asg_mode.self_check(cfg, {"cpu50"}, set())
    assert len(errs) == 1 and "rogue" in errs[0]

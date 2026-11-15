"""Proactive scaler decision logic (plan §6.6 unit tests) with a fake ASG."""

from collections.abc import Sequence

import pytest

import proactive_scaler as ps
from fakes import FakeASG
from proactive_scaler import Scaler


def drive(scaler: Scaler, asg: FakeASG, schedule: Sequence[tuple[float, float | None]]) -> list[int]:
    """Feed (t, rps) ticks; apply each decision to the fake ASG; return desired after each tick."""
    out = []
    for t, rps in schedule:
        d = scaler.decide(t, asg.desired, rps)
        if d.desired_after != d.desired_before:
            ps.set_desired(asg, "hsl-asg", d.desired_after)
        out.append(asg.desired)
    return out


def test_ramp_30_to_300_scales_1_2_4_5():
    asg = FakeASG(desired=1)
    s = Scaler(per_instance_rps=100, headroom=1.6)
    assert drive(s, asg, [(0, 30), (10, 100), (20, 200), (30, 300)]) == [1, 2, 4, 5]
    assert all(kw["HonorCooldown"] is False for name, kw in asg.calls if name == "set_desired")


def test_scale_out_jumps_straight_to_target():
    asg = FakeASG(desired=1)
    s = Scaler(per_instance_rps=100, headroom=1.6)
    assert drive(s, asg, [(0, 300)]) == [5]  # one call, not a ladder of +1 steps


def test_load_drop_scales_in_one_step_per_hold_period():
    asg = FakeASG(desired=1)
    s = Scaler(per_instance_rps=100, headroom=1.6, hold_min=5)
    drive(s, asg, [(0, 300)])  # -> 5
    ticks = [(t, 30.0) for t in range(10, 1300, 10)]
    hist = drive(s, asg, ticks)
    by_t = dict(zip([t for t, _ in ticks], hist, strict=True))
    assert by_t[290] == 5  # still holding before 5 min below target
    assert by_t[310] == 4  # first step down after 5 min
    assert by_t[600] == 4  # no second step before another 5 min
    assert by_t[620] == 3
    assert min(hist) >= 1


def test_target_back_at_desired_resets_the_hold_timer():
    asg = FakeASG(desired=1)
    s = Scaler(per_instance_rps=100, headroom=1.6, hold_min=5)
    drive(s, asg, [(0, 300)])  # -> 5, last_change = 0
    drive(s, asg, [(t, 30.0) for t in range(10, 200, 10)])  # below for 190 s
    drive(s, asg, [(200, 300.0)])  # load is back: below_since cleared
    ticks = list(range(210, 520, 10))
    hist = dict(zip(ticks, drive(s, asg, [(t, 30.0) for t in ticks]), strict=True))
    assert hist[500] == 5  # the hold restarted at t=210, so 5 min have not passed yet
    assert hist[510] == 4


def test_extrapolates_when_one_instance_times_out():
    assert Scaler.total_rps([{"rps": 50.0}, {"rps": 50.0}, None], 3) == pytest.approx(150.0)


def test_no_stats_at_all_never_scales():
    asg = FakeASG(desired=3)
    s = Scaler(per_instance_rps=100)
    rps = Scaler.total_rps([None, None, None], 3)
    assert rps is None
    d = s.decide(0, asg.desired, rps)
    assert (d.action, d.desired_after) == ("no_data", 3)


def test_never_above_max_cap():
    asg = FakeASG(desired=1)
    s = Scaler(per_instance_rps=100, headroom=1.6)
    assert drive(s, asg, [(0, 10_000)]) == [6]


def test_prewarm_floor_holds_until_floor_until_then_releases():
    asg = FakeASG(desired=1)
    s = Scaler(per_instance_rps=100, headroom=1.6, prewarm=4, floor_until=100, hold_min=5)
    assert drive(s, asg, [(0, 10)]) == [4]
    assert drive(s, asg, [(t, 10.0) for t in range(10, 100, 10)])[-1] == 4  # floor holds
    # after the floor ends: one step down per 5 min, starting 5 min after it ends
    hist = drive(s, asg, [(t, 10.0) for t in range(100, 720, 10)])
    assert hist[0] == 4 and hist[-1] == 2


def test_headroom_zero_means_floor_only_variant_e4a():
    asg = FakeASG(desired=1)
    s = Scaler(per_instance_rps=100, headroom=0, prewarm=4, floor_until=1000)
    d = s.decide(0, asg.desired, 900.0)
    assert (d.need, d.target) == (0, 4)


def test_spike_profile_step_is_answered_within_one_tick():
    """Acceptance: desired rises within 10-20 s of a rate step (tick = 10 s, stats window lags <= 10 s)."""
    asg = FakeASG(desired=1)
    s = Scaler(per_instance_rps=100, headroom=1.6)
    pre, match = 30.0, 300.0
    ticks = [(t, pre) for t in range(0, 120, 10)] + [(t, match) for t in range(120, 200, 10)]
    hist = drive(s, asg, ticks)
    assert hist[ticks.index((120, match))] == 5


def test_rejects_bad_c1():
    with pytest.raises(ValueError):
        Scaler(per_instance_rps=0)

import pytest

import common
from common import GroupState
from fakes import FakeASG, FakeELB, clients, instance


class Clock:
    def __init__(self):
        self.t = 0.0

    def now(self):
        return self.t

    def sleep(self, s):
        self.t += s


def stable(n):
    return GroupState(desired=n, in_service=n, healthy=n)


def test_returns_after_quiet_period():
    clk = Clock()
    seq = iter([GroupState(desired=3, in_service=1, pending=2, healthy=1)] * 3 + [stable(3)] * 100)
    st = common.wait_stable(lambda: next(seq), 3, quiet_s=30, poll_s=5, clock=clk.now, sleep=clk.sleep)
    assert st.healthy == 3
    assert clk.t == pytest.approx(15 + 30)  # 3 unstable polls, then 30 s of quiet


def test_change_restarts_quiet_timer():
    clk = Clock()
    flap = [stable(2)] * 3 + [GroupState(desired=2, in_service=2, healthy=1)] + [stable(2)] * 100
    seq = iter(flap)
    common.wait_stable(lambda: next(seq), 2, quiet_s=20, poll_s=5, clock=clk.now, sleep=clk.sleep)
    assert clk.t == pytest.approx(20 + 20)  # the unhealthy blip at t=15 restarts the timer at t=20


def test_activity_in_progress_is_not_stable():
    assert not GroupState(desired=1, in_service=1, healthy=1, activity_in_progress=True).is_stable(1)


def test_timeout():
    clk = Clock()
    with pytest.raises(TimeoutError):
        common.wait_stable(
            lambda: GroupState(desired=2, in_service=1, healthy=1),
            2,
            timeout_s=60,
            poll_s=5,
            clock=clk.now,
            sleep=clk.sleep,
        )


def test_group_state_counts():
    asg = FakeASG(desired=3, instances=[instance("i-1"), instance("i-2"), instance("i-3", "Pending:Wait")])
    elb = FakeELB({"i-1": "healthy", "i-2": "draining", "i-3": "initial"})
    asg.activities = [{"StatusCode": "InProgress"}]
    env = common.Env(region="ap-south-1", asg_name="hsl-asg", tg_arn="arn:tg")
    st = common.group_state(clients(asg=asg, elb=elb), env)
    assert (st.desired, st.in_service, st.pending, st.healthy, st.draining, st.initial) == (3, 2, 1, 1, 1, 1)
    assert st.activity_in_progress


def test_in_service_instances_needs_inservice_and_healthy():
    asg = FakeASG(instances=[instance("i-1"), instance("i-2"), instance("i-3", "Pending")])
    elb = FakeELB({"i-1": "healthy", "i-2": "unhealthy", "i-3": "healthy"})
    env = common.Env(region="ap-south-1", asg_name="hsl-asg", tg_arn="arn:tg")
    c = clients(asg=asg, elb=elb)
    st = common.group_state(c, env, with_activities=False)
    assert [i["id"] for i in common.in_service_instances(c, st)] == ["i-1"]


def test_env_reads_dotenv(tmp_path, monkeypatch):
    for k in ("ASG_NAME", "TG_ARN", "TARGET_GROUP_ARN", "REGION", "AWS_REGION"):
        monkeypatch.delenv(k, raising=False)
    (tmp_path / ".env.tf").write_text("ASG_NAME=hsl-asg\nTARGET_GROUP_ARN=arn:tg\nREGION=ap-south-1\n")
    monkeypatch.chdir(tmp_path)
    env = common.Env.from_environ()
    assert (env.asg_name, env.tg_arn, env.region) == ("hsl-asg", "arn:tg", "ap-south-1")


def test_parse_time():
    assert common.parse_time("1763460125") == 1763460125.0
    assert common.parse_time("2026-11-18T10:42:05Z") == pytest.approx(1794998525.0)


def test_reset_stamp(tmp_path, monkeypatch):
    monkeypatch.setattr(common, "STATE_DIR", tmp_path)
    monkeypatch.setattr(common, "RESET_STAMP", tmp_path / "last_reset")
    assert common.seconds_since_reset() is None
    common.mark_reset()
    since = common.seconds_since_reset()
    assert since is not None and 0 <= since < 5

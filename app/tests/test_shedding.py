import degrade
import stats
from conftest import TOKEN_HDR


def test_degrade_level_1_returns_fallback(client):
    before = stats.STATS.shed_total
    degrade.set_level(1, "test")
    j = client.get("/api/v1/recommendations", headers=TOKEN_HDR).json()
    assert j == {"items": [], "degraded": True}
    assert stats.STATS.shed_total == before + 1


def test_degrade_does_not_touch_critical_path(client):
    degrade.set_level(1, "test")
    r = client.post("/api/v1/playback/start", json={"user_id": 1, "match_id": "m1"}, headers=TOKEN_HDR)
    assert r.status_code == 200 and "manifest" in r.json()


def test_auto_shed_above_threshold(client, cfg, monkeypatch):
    cfg(auto_shed=True, shed_inflight=4)
    # In-flight during the request = forced value + the request itself.
    monkeypatch.setattr(stats.STATS, "inflight", 10)
    j = client.get("/api/v1/recommendations", headers=TOKEN_HDR).json()
    assert j["degraded"] is True


def test_auto_shed_below_threshold(client, cfg):
    cfg(auto_shed=True, shed_inflight=4)
    j = client.get("/api/v1/recommendations", headers=TOKEN_HDR).json()
    assert j["degraded"] is False


def test_auto_shed_off_never_sheds(client, cfg, monkeypatch):
    cfg(auto_shed=False, shed_inflight=4)
    monkeypatch.setattr(stats.STATS, "inflight", 10)
    assert client.get("/api/v1/recommendations", headers=TOKEN_HDR).json()["degraded"] is False


class _FakeSSM:
    def __init__(self, value):
        self.value = value

    def get_parameter(self, Name):  # noqa: N803 - boto3 signature
        return {"Parameter": {"Name": Name, "Value": self.value}}


def test_degrade_poll_reads_ssm():
    degrade.poll_once(_FakeSSM("1"))
    assert degrade.level() == 1 and degrade.source() == "ssm"
    degrade.poll_once(_FakeSSM("0"))
    assert degrade.level() == 0

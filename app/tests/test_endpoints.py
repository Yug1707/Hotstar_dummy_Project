from conftest import TOKEN_HDR

BODY = {"user_id": 7, "match_id": "m1"}


def test_healthz(client):
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json()["ok"] is True
    assert r.headers["x-instance-id"].startswith("local-")


def test_whoami_shape(client):
    j = client.get("/api/v1/whoami", headers=TOKEN_HDR).json()
    assert set(j) >= {"instance_id", "az", "uptime_s", "os_uptime_s", "in_flight", "degrade_level", "version"}
    assert j["az"] == "local"


def test_playback_start(client):
    r = client.post("/api/v1/playback/start", json=BODY, headers=TOKEN_HDR)
    assert r.status_code == 200
    j = r.json()
    assert j["manifest"].endswith("/m1/master.m3u8")
    assert len(j["token"]) == 16


def test_playback_rejects_bad_body(client):
    r = client.post("/api/v1/playback/start", json={"user_id": -1}, headers=TOKEN_HDR)
    assert r.status_code == 422


def test_heartbeat_counts_active_viewers(client):
    for uid in (1, 2, 2, 3):
        assert client.post("/api/v1/heartbeat", json={"user_id": uid, "match_id": "m1"}, headers=TOKEN_HDR).is_success
    assert client.get("/internal/stats").json()["active_viewers"] >= 3


def test_match_state_is_cacheable_and_stable(client):
    a = client.get("/api/v1/match/state", headers=TOKEN_HDR)
    b = client.get("/api/v1/match/state", headers=TOKEN_HDR)
    assert a.headers["cache-control"] == "public, max-age=5"
    assert a.json()["match_id"] == "m1"
    # same 5-second bucket -> identical payload on every instance (E7 relies on this)
    if a.json()["bucket"] == b.json()["bucket"]:
        assert a.json() == b.json()


def test_non_cacheable_endpoints_are_no_store(client):
    assert client.get("/api/v1/recommendations", headers=TOKEN_HDR).headers["cache-control"] == "no-store"
    assert client.post("/api/v1/playback/start", json=BODY, headers=TOKEN_HDR).headers["cache-control"] == "no-store"
    assert client.get("/api/v1/whoami", headers=TOKEN_HDR).headers["cache-control"] == "no-store"


def test_recommendations_normal(client):
    j = client.get("/api/v1/recommendations", headers=TOKEN_HDR).json()
    assert j["degraded"] is False
    assert len(j["items"]) == 10


def test_static_index_served(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "Hotstar Scale Lab" in r.text


def test_internal_stats_keys(client):
    for _ in range(5):
        client.get("/api/v1/match/state", headers=TOKEN_HDR)
    j = client.get("/internal/stats").json()
    expected = {
        "instance_id", "az", "ts", "rps", "rps_completed", "in_flight", "p95_ms", "active_viewers",
        "cpu_percent", "degrade_level", "auto_shed", "shed_total", "rate_limited_total", "workers", "version",
    }  # fmt: skip
    assert expected <= set(j)
    assert j["workers"] >= 1

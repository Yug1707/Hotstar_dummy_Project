import ratelimit
from conftest import TOKEN_HDR


def test_rate_limit_kicks_in_without_token(client):
    codes = [client.get("/api/v1/match/state").status_code for _ in range(45)]
    assert 429 in codes
    assert codes.count(200) >= 40  # burst of 40 is honoured


def test_token_bypasses_rate_limit(client):
    codes = [client.get("/api/v1/match/state", headers=TOKEN_HDR).status_code for _ in range(60)]
    assert set(codes) == {200}


def test_wrong_token_is_limited(client):
    codes = [client.get("/api/v1/match/state", headers={"X-Load-Test": "nope"}).status_code for _ in range(45)]
    assert 429 in codes


def test_non_api_paths_not_limited(client):
    assert {client.get("/healthz").status_code for _ in range(60)} == {200}


def test_separate_buckets_per_viewer_address(client):
    a = [client.get("/api/v1/match/state", headers={"CloudFront-Viewer-Address": "1.1.1.1:5000"}) for _ in range(41)]
    b = client.get("/api/v1/match/state", headers={"CloudFront-Viewer-Address": "2.2.2.2:5000"})
    assert a[-1].status_code == 429
    assert b.status_code == 200


def test_rate_limited_counter(client):
    before = client.get("/internal/stats").json()["rate_limited_total"]
    for _ in range(45):
        client.get("/api/v1/match/state")
    assert client.get("/internal/stats").json()["rate_limited_total"] > before


def test_client_key_rules():
    k = ratelimit.client_key
    assert k({"cloudfront-viewer-address": "203.0.113.9:443"}, "10.0.0.1") == "203.0.113.9"
    assert k({"cloudfront-viewer-address": "2001:db8::1:443"}, None) == "2001:db8::1"
    # via CloudFront: "<spoofed>, <real client>, <edge>" -> real client
    assert k({"x-forwarded-for": "6.6.6.6, 203.0.113.9, 130.176.0.1"}, "10.0.0.1") == "203.0.113.9"
    assert k({"x-forwarded-for": "203.0.113.9"}, "10.0.0.1") == "203.0.113.9"
    assert k({}, "10.0.0.1") == "10.0.0.1"


def test_token_bucket_refills():
    ratelimit.reset()
    h = {"cloudfront-viewer-address": "9.9.9.9:1"}
    assert all(ratelimit.allow(h, None, now=100.0) for _ in range(40))
    assert not ratelimit.allow(h, None, now=100.0)
    assert ratelimit.allow(h, None, now=100.1)  # 0.1 s x 20 rps = 2 tokens back

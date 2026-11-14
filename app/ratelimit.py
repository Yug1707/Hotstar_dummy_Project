"""Per-client token bucket on /api/* for the public site, with a load-test bypass header.

Client key (fix F4): behind CloudFront + ALB the socket peer is the ALB, and X-Forwarded-For[0]
is whatever the client sent. CloudFront appends the real client IP and the ALB appends the edge IP,
so the real client is the 2nd entry from the right. CloudFront-Viewer-Address wins when forwarded.
"""

from __future__ import annotations

import hmac
import logging
import threading
import time
from collections.abc import Mapping

import config
import degrade

log = logging.getLogger("streamlite.ratelimit")

TOKEN = ""
_buckets: dict[str, tuple[float, float]] = {}  # key -> (tokens, last_monotonic)
_lock = threading.Lock()
_last_prune = 0.0
IDLE_PRUNE_S = 60.0


def load_token() -> None:
    """Token from SSM SecureString on EC2 (fix F10), else from LOADTEST_TOKEN."""
    global TOKEN
    TOKEN = config.CFG.loadtest_token
    if not degrade.ssm_enabled():
        return
    try:
        resp = degrade.ssm_client().get_parameter(Name=config.CFG.ssm_token_param, WithDecryption=True)
        TOKEN = resp["Parameter"]["Value"]
    except Exception as e:  # noqa: BLE001
        log.warning("ratelimit: could not read load-test token from SSM (%s)", e)


def client_key(headers: Mapping[str, str], peer: str | None) -> str:
    cva = headers.get("cloudfront-viewer-address")
    if cva:
        return cva.rsplit(":", 1)[0]  # "ip:port" (IPv6 ip contains ':' too, so split once from the right)
    xff = headers.get("x-forwarded-for")
    if xff:
        parts = [p.strip() for p in xff.split(",") if p.strip()]
        if parts:
            return parts[-2] if len(parts) >= 2 else parts[-1]
    return peer or "unknown"


def is_load_test(headers: Mapping[str, str]) -> bool:
    sent = headers.get("x-load-test", "")
    return bool(TOKEN) and hmac.compare_digest(sent.encode(), TOKEN.encode())


def allow(headers: Mapping[str, str], peer: str | None, now: float | None = None) -> bool:
    rps = config.CFG.rate_limit_rps
    if rps <= 0 or is_load_test(headers):
        return True
    burst = float(config.CFG.rate_limit_burst)
    key = client_key(headers, peer)
    now = time.monotonic() if now is None else now
    with _lock:
        tokens, last = _buckets.get(key, (burst, now))
        tokens = min(burst, tokens + (now - last) * rps)
        allowed = tokens >= 1.0
        _buckets[key] = (tokens - 1.0 if allowed else tokens, now)
        _prune(now)
    return allowed


def _prune(now: float) -> None:
    global _last_prune
    if now - _last_prune < 10:
        return
    for k in [k for k, (_, t) in _buckets.items() if now - t > IDLE_PRUNE_S]:
        del _buckets[k]
    _last_prune = now


def reset() -> None:
    global _last_prune
    with _lock:
        _buckets.clear()
        _last_prune = 0.0

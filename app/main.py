"""StreamLite: a tiny streaming-platform hot path with predictable, tunable CPU cost (plan §4.5)."""

from __future__ import annotations

import logging
import os
import secrets
import time
from contextlib import asynccontextmanager

import anyio.to_thread
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

import config
import degrade
import imds
import ratelimit
import stats
import work

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
NO_STORE = {"Cache-Control": "no-store"}


@asynccontextmanager
async def lifespan(_app: FastAPI):
    anyio.to_thread.current_default_thread_limiter().total_tokens = config.CFG.threads
    imds.load()
    degrade.start()
    ratelimit.load_token()
    stats.start_writer()
    yield
    stats.stop_writer()
    degrade.stop()


app = FastAPI(title="StreamLite", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
S = stats.STATS


@app.middleware("http")
async def track(request: Request, call_next):
    path = request.url.path
    S.on_arrival()  # arrivals, not completions (F5)
    if path.startswith("/api/"):
        peer = request.client.host if request.client else None
        if not ratelimit.allow(request.headers, peer):
            S.on_rate_limited()
            return JSONResponse(
                {"error": "rate_limited"},
                status_code=429,
                headers={"Retry-After": "1", "X-Instance-Id": imds.INSTANCE_ID, **NO_STORE},
            )
    S.inflight += 1
    t0 = time.perf_counter()
    try:
        resp = await call_next(request)
    except Exception:
        S.on_error()
        raise
    finally:
        S.inflight -= 1
    S.on_done(time.perf_counter() - t0, resp.status_code)
    resp.headers["X-Instance-Id"] = imds.INSTANCE_ID
    return resp


class PlayReq(BaseModel):
    user_id: int = Field(ge=0)
    match_id: str = Field(min_length=1, max_length=64)


# ---- infra ------------------------------------------------------------------------------------
@app.get("/healthz")
def healthz():
    return JSONResponse({"ok": True, "instance_id": imds.INSTANCE_ID}, headers=NO_STORE)


@app.get("/api/v1/whoami")
def whoami():
    return JSONResponse(
        {
            "instance_id": imds.INSTANCE_ID,
            "az": imds.AZ,
            "uptime_s": round(time.time() - stats.STARTED, 1),
            "os_uptime_s": imds.os_uptime(),
            "in_flight": S.inflight,
            "degrade_level": degrade.level(),
            "version": config.CFG.app_version,
        },
        headers=NO_STORE,
    )


# ---- critical path ----------------------------------------------------------------------------
@app.post("/api/v1/playback/start")
def playback_start(body: PlayReq):
    work.burn("critical")
    return JSONResponse(
        {
            "manifest": f"https://cdn.example.invalid/{body.match_id}/master.m3u8",
            "token": secrets.token_hex(8),
            "instance_id": imds.INSTANCE_ID,
        },
        headers=NO_STORE,
    )


@app.post("/api/v1/heartbeat")
def heartbeat(body: PlayReq):
    work.burn("heartbeat")
    S.viewer_seen(body.user_id)
    return JSONResponse({"ok": True}, headers=NO_STORE)


# ---- public, cacheable ------------------------------------------------------------------------
@app.get("/api/v1/match/state")
def match_state():
    work.burn("state")
    return JSONResponse(stats.fake_score(), headers={"Cache-Control": "public, max-age=5"})


# ---- non-critical, degradable -----------------------------------------------------------------
def should_shed() -> bool:
    return degrade.level() >= 1 or (config.CFG.auto_shed and S.inflight > config.CFG.shed_inflight)


@app.get("/api/v1/recommendations")
def recommendations():
    if should_shed():
        S.on_shed()
        return JSONResponse({"items": [], "degraded": True}, headers=NO_STORE)
    work.burn("reco")
    return JSONResponse({"items": stats.fake_reco(), "degraded": False}, headers=NO_STORE)


# ---- internal (blocked at the ALB by a listener rule; reached on the private IP) ---------------
@app.get("/internal/stats")
def internal_stats():
    body = stats.aggregate()
    body.update(
        {
            "instance_id": imds.INSTANCE_ID,
            "az": imds.AZ,
            "ts": round(time.time(), 3),
            "degrade_level": degrade.level(),
            "degrade_source": degrade.source(),
            "auto_shed": config.CFG.auto_shed,
            "version": config.CFG.app_version,
        }
    )
    return JSONResponse(body, headers=NO_STORE)


# ---- static dashboard (local dev; production serves web/ from S3 via CloudFront) ---------------
if os.path.isdir(config.CFG.web_dir):
    app.mount("/", StaticFiles(directory=config.CFG.web_dir, html=True), name="web")

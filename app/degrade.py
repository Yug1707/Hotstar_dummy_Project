"""Degrade level (0 = normal, 1 = non-critical endpoints return the cheap fallback).

A daemon thread polls the SSM parameter every 5 s. When SSM is unreachable it keeps the last good
value, or falls back to the DEGRADE_LEVEL env var if it never got one. SSM_MODE=auto polls only on
EC2, so local dev and tests never call AWS.
"""

from __future__ import annotations

import logging
import threading

import config
import imds

log = logging.getLogger("streamlite.degrade")

_level: int | None = None
_source = "env"
_thread: threading.Thread | None = None
_stop = threading.Event()


def level() -> int:
    return _level if _level is not None else config.CFG.degrade_level


def source() -> str:
    return _source


def set_level(value: int, src: str = "manual") -> None:
    global _level, _source
    _level, _source = (1 if int(value) >= 1 else 0), src


def ssm_enabled() -> bool:
    mode = config.CFG.ssm_mode
    return mode == "on" or (mode == "auto" and imds.ON_EC2)


def ssm_client():
    import boto3
    from botocore.config import Config as BotoConfig

    return boto3.client(
        "ssm",
        region_name=config.CFG.region,
        config=BotoConfig(connect_timeout=1, read_timeout=1, retries={"max_attempts": 1}),
    )


def poll_once(client) -> None:
    resp = client.get_parameter(Name=config.CFG.ssm_degrade_param)
    set_level(int(resp["Parameter"]["Value"]), "ssm")


def _loop(interval: float) -> None:
    client = None
    warned = False
    while True:
        try:
            client = client or ssm_client()
            poll_once(client)
            warned = False
        except Exception as e:  # noqa: BLE001 - keep last good value on any failure
            if not warned:
                log.warning("degrade: SSM poll failed (%s); keeping level=%s", e, level())
                warned = True
        if _stop.wait(interval):
            return


def start(interval: float = 5.0) -> None:
    global _thread
    if _thread is not None or not ssm_enabled():
        return
    _stop.clear()
    _thread = threading.Thread(target=_loop, args=(interval,), name="degrade-poller", daemon=True)
    _thread.start()


def stop() -> None:
    global _thread
    _stop.set()
    _thread = None

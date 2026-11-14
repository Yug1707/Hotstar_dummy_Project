"""EC2 instance metadata via IMDSv2, read once at start-up. Falls back to 'local-<hostname>'."""

from __future__ import annotations

import socket
import urllib.request

import config

BASE = "http://169.254.169.254/latest"
INSTANCE_ID = "local-" + socket.gethostname()
AZ = "local"
ON_EC2 = False


def _get(path: str, token: str, timeout: float) -> str:
    req = urllib.request.Request(f"{BASE}/{path}", headers={"X-aws-ec2-metadata-token": token})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode()


def load(timeout: float = 0.3) -> None:
    global INSTANCE_ID, AZ, ON_EC2
    if not config.CFG.imds_enabled:
        return
    try:
        req = urllib.request.Request(
            f"{BASE}/api/token",
            method="PUT",
            headers={"X-aws-ec2-metadata-token-ttl-seconds": "21600"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as r:
            token = r.read().decode()
        INSTANCE_ID = _get("meta-data/instance-id", token, timeout)
        AZ = _get("meta-data/placement/availability-zone", token, timeout)
        ON_EC2 = True
    except Exception:  # noqa: BLE001 - any failure means "not on EC2"
        pass


def os_uptime() -> float | None:
    try:
        with open("/proc/uptime") as f:
            return round(float(f.read().split()[0]), 1)
    except OSError:
        return None

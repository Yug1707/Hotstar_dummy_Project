"""Predictable, tunable CPU cost per request class (plan §4.3).

PBKDF2 does a fixed amount of CPU work and the OpenSSL implementation releases the GIL, so two
threads really use two vCPUs. A wall-clock spin loop would do *less* work on a contended core and
hide saturation.
"""

from __future__ import annotations

import hashlib

import config

# Iterations per class at WORK_SCALE=1, aiming at: critical 15 ms, heartbeat 2 ms, state 1 ms, reco 40 ms.
# Measured with scripts/calibrate.py on a laptop (~9,000 PBKDF2-SHA256 iterations per ms). Re-run it on
# c7i-flex.large (task T2.7; the Free-plan type), paste the new table here, then tune WORK_SCALE so one
# instance saturates near C1 = 100 rps (expect WORK_SCALE ~ 2 on 2 vCPUs).
ITER: dict[str, int] = {
    "critical": 135_000,
    "heartbeat": 18_000,
    "state": 9_000,
    "reco": 360_000,
}


def iterations(kind: str) -> int:
    return max(1, int(ITER[kind] * config.CFG.work_scale))


def burn(kind: str) -> None:
    hashlib.pbkdf2_hmac("sha256", b"streamlite", b"salt", iterations(kind))

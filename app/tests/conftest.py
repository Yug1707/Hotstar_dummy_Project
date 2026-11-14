import os
import tempfile

# Must be set before any app module is imported: config.CFG is read once at import time.
_STATS_DIR = tempfile.mkdtemp(prefix="streamlite-test-")
os.environ.update(
    {
        "IMDS_ENABLED": "false",
        "SSM_MODE": "off",
        "LOADTEST_TOKEN": "test-token",
        "STATS_DIR": _STATS_DIR,
        "WORK_SCALE": "0.01",  # keep CPU burn tiny in tests
        "RATE_LIMIT_RPS": "20",
        "RATE_LIMIT_BURST": "40",
    }
)

import dataclasses  # noqa: E402

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import config  # noqa: E402
import degrade  # noqa: E402
import main  # noqa: E402
import ratelimit  # noqa: E402
import stats  # noqa: E402

TOKEN_HDR = {"X-Load-Test": "test-token"}


@pytest.fixture
def client():
    ratelimit.reset()
    degrade.set_level(0, "env")
    stats.STATS.inflight = 0
    with TestClient(main.app) as c:
        yield c


@pytest.fixture
def cfg(monkeypatch):
    """Swap config fields for one test: cfg(auto_shed=True)."""

    def _set(**kw):
        monkeypatch.setattr(config, "CFG", dataclasses.replace(config.CFG, **kw))

    return _set


@pytest.fixture
def stats_dir():
    return _STATS_DIR

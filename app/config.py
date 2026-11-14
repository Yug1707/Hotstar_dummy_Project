"""Environment-only configuration (plan §1.2). Access it as ``config.CFG`` so tests can swap it."""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass


def _bool(name: str, default: bool) -> bool:
    return os.getenv(name, str(default)).strip().lower() in ("1", "true", "yes", "on")


def _default_stats_dir() -> str:
    return "/dev/shm" if os.path.isdir("/dev/shm") else tempfile.gettempdir()


@dataclass(frozen=True)
class Config:
    work_scale: float
    degrade_level: int
    ssm_mode: str  # "auto" (only on EC2) | "on" | "off"
    ssm_degrade_param: str
    ssm_token_param: str
    loadtest_token: str
    auto_shed: bool
    shed_inflight: int
    threads: int
    rate_limit_rps: float
    rate_limit_burst: int
    app_version: str
    region: str
    stats_dir: str
    imds_enabled: bool
    web_dir: str

    @classmethod
    def from_env(cls) -> Config:
        here = os.path.dirname(os.path.abspath(__file__))
        web_default = next(
            (p for p in (os.path.join(here, "web"), os.path.join(here, "..", "web")) if os.path.isdir(p)),
            os.path.join(here, "web"),
        )
        cfg = cls(
            work_scale=float(os.getenv("WORK_SCALE", "1.0")),
            degrade_level=int(os.getenv("DEGRADE_LEVEL", "0")),
            ssm_mode=os.getenv("SSM_MODE", "auto").lower(),
            ssm_degrade_param=os.getenv("SSM_DEGRADE_PARAM", "/streamlite/degrade_level"),
            ssm_token_param=os.getenv("SSM_TOKEN_PARAM", "/streamlite/loadtest_token"),
            loadtest_token=os.getenv("LOADTEST_TOKEN", ""),
            auto_shed=_bool("AUTO_SHED", False),
            shed_inflight=int(os.getenv("SHED_INFLIGHT", "48")),
            threads=int(os.getenv("THREADS", "64")),
            rate_limit_rps=float(os.getenv("RATE_LIMIT_RPS", "20")),
            rate_limit_burst=int(os.getenv("RATE_LIMIT_BURST", "40")),
            app_version=os.getenv("APP_VERSION", "dev"),
            region=os.getenv("AWS_REGION", "ap-south-1"),
            stats_dir=os.getenv("STATS_DIR", _default_stats_dir()),
            imds_enabled=_bool("IMDS_ENABLED", True),
            web_dir=os.getenv("WEB_DIR", web_default),
        )
        cfg.validate()
        return cfg

    def validate(self) -> None:
        if self.work_scale <= 0:
            raise ValueError("WORK_SCALE must be > 0")
        if self.degrade_level not in (0, 1):
            raise ValueError("DEGRADE_LEVEL must be 0 or 1")
        if self.ssm_mode not in ("auto", "on", "off"):
            raise ValueError("SSM_MODE must be auto, on or off")
        if not 0 < self.shed_inflight < self.threads:
            raise ValueError("SHED_INFLIGHT must be > 0 and < THREADS")


CFG = Config.from_env()

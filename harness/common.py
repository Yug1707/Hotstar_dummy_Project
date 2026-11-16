"""Shared helpers for the lab automation (plan §6.3).

Names come from the environment: on the loadgen /etc/profile.d/hsl.sh exports them; on a laptop
`make env` writes .env.tf, which load_env() reads. Every AWS call goes through clients() with
adaptive retries, so a throttled Describe call slows down instead of failing a run.
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

MAX_CAP = 4  # hard cap (Free plan: credit + vCPU quota), also Terraform's asg_max validation (F1)
HERE = Path(__file__).resolve().parent
STATE_DIR = Path(os.environ.get("HSL_STATE_DIR", Path.home() / ".hsl"))
RESET_STAMP = STATE_DIR / "last_reset"


# ---- logging / time ------------------------------------------------------------------------------
def utc_iso(ts: float | None = None) -> str:
    return datetime.fromtimestamp(time.time() if ts is None else ts, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_time(value: str | float | int) -> float:
    """Epoch seconds from an epoch number or an ISO-8601 UTC string."""
    if isinstance(value, int | float):
        return float(value)
    try:
        return float(value)
    except ValueError:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()


def log(*parts: Any) -> None:
    print(utc_iso(), *parts, file=sys.stderr, flush=True)


# ---- environment ---------------------------------------------------------------------------------
def load_env(path: str | os.PathLike | None = None) -> None:
    """Read KEY=VALUE lines from .env.tf into os.environ without overriding what is already set."""
    candidates = [Path(path)] if path else [Path.cwd() / ".env.tf", HERE.parent / ".env.tf"]
    for p in candidates:
        if p.is_file():
            for line in p.read_text().splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip().strip('"'))
            return


@dataclass(frozen=True)
class Env:
    region: str
    asg_name: str
    tg_arn: str
    tg_suffix: str = ""
    alb_suffix: str = ""
    alb_dns: str = ""
    cloudfront_url: str = ""
    results_bucket: str = ""

    @classmethod
    def from_environ(cls) -> Env:
        load_env()
        e = os.environ
        missing = [k for k in ("ASG_NAME",) if not e.get(k)]
        tg = e.get("TG_ARN") or e.get("TARGET_GROUP_ARN", "")
        if not tg:
            missing.append("TG_ARN/TARGET_GROUP_ARN")
        if missing:
            hint = "run `make env` or source /etc/profile.d/hsl.sh"
            raise SystemExit(f"missing environment: {', '.join(missing)} ({hint})")
        return cls(
            region=e.get("AWS_REGION") or e.get("REGION") or "ap-south-1",
            asg_name=e["ASG_NAME"],
            tg_arn=tg,
            tg_suffix=e.get("TG_ARN_SUFFIX", ""),
            alb_suffix=e.get("ALB_ARN_SUFFIX", ""),
            alb_dns=e.get("ALB_DNS", ""),
            cloudfront_url=e.get("CLOUDFRONT_URL", ""),
            results_bucket=e.get("RESULTS_BUCKET", ""),
        )


def clients(region: str) -> SimpleNamespace:
    import boto3
    from botocore.config import Config

    cfg = Config(region_name=region, retries={"mode": "adaptive", "max_attempts": 10})
    return SimpleNamespace(
        asg=boto3.client("autoscaling", config=cfg),
        elb=boto3.client("elbv2", config=cfg),
        ec2=boto3.client("ec2", config=cfg),
        cw=boto3.client("cloudwatch", config=cfg),
        ssm=boto3.client("ssm", config=cfg),
    )


# ---- group state ---------------------------------------------------------------------------------
@dataclass
class GroupState:
    desired: int = 0
    min_size: int = 0
    max_size: int = 0
    in_service: int = 0
    pending: int = 0
    terminating: int = 0
    healthy: int = 0
    unhealthy: int = 0
    initial: int = 0
    draining: int = 0
    activity_in_progress: bool = False
    instances: list[dict] = field(default_factory=list)  # ASG instance records
    targets: dict[str, str] = field(default_factory=dict)  # instance id -> target health state

    def signature(self) -> tuple:
        return (self.desired, self.in_service, self.pending, self.terminating, self.healthy, self.activity_in_progress)

    def is_stable(self, desired: int) -> bool:
        return (
            self.desired == desired
            and self.in_service == desired
            and self.healthy == desired
            and self.pending == 0
            and self.terminating == 0
            and not self.activity_in_progress
        )


def describe_group(asg, name: str) -> dict:
    groups = asg.describe_auto_scaling_groups(AutoScalingGroupNames=[name])["AutoScalingGroups"]
    if not groups:
        raise SystemExit(f"auto scaling group {name!r} not found")
    return groups[0]


def group_state(c: SimpleNamespace, env: Env, with_activities: bool = True) -> GroupState:
    g = describe_group(c.asg, env.asg_name)
    th = c.elb.describe_target_health(TargetGroupArn=env.tg_arn)["TargetHealthDescriptions"]
    targets = {t["Target"]["Id"]: t["TargetHealth"]["State"] for t in th}
    states = [i["LifecycleState"] for i in g["Instances"]]
    busy = False
    if with_activities:
        acts = c.asg.describe_scaling_activities(AutoScalingGroupName=env.asg_name, MaxRecords=10)["Activities"]
        busy = any(a["StatusCode"] not in ("Successful", "Failed", "Cancelled") for a in acts)
    count = lambda s: sum(1 for v in targets.values() if v == s)  # noqa: E731
    return GroupState(
        desired=g["DesiredCapacity"],
        min_size=g["MinSize"],
        max_size=g["MaxSize"],
        in_service=states.count("InService"),
        pending=sum(1 for s in states if s.startswith("Pending")),
        terminating=sum(1 for s in states if s.startswith("Terminating")),
        healthy=count("healthy"),
        unhealthy=count("unhealthy"),
        initial=count("initial"),
        draining=count("draining"),
        activity_in_progress=busy,
        instances=g["Instances"],
        targets=targets,
    )


def wait_stable(
    state_fn,
    desired: int,
    quiet_s: float = 120,
    timeout_s: float = 900,
    poll_s: float = 5,
    clock=time.monotonic,
    sleep=time.sleep,
) -> GroupState:
    """Wait until the group is stable at `desired` and stays unchanged for `quiet_s` seconds.

    Stable = desired/in-service/healthy all equal `desired`, nothing pending or terminating and no
    scaling activity in progress. Any change in the state restarts the quiet timer.
    """
    start = clock()
    stable_since: float | None = None
    last_sig = None
    while True:
        st = state_fn()
        now = clock()
        sig = st.signature()
        if st.is_stable(desired):
            if stable_since is None or sig != last_sig:
                stable_since = now
            if now - stable_since >= quiet_s:
                return st
        else:
            stable_since = None
        last_sig = sig
        if now - start > timeout_s:
            raise TimeoutError(f"group not stable at {desired} after {timeout_s:.0f}s (last: {sig})")
        sleep(poll_s)


# ---- instances and their /internal/stats ---------------------------------------------------------
def in_service_instances(c: SimpleNamespace, st: GroupState) -> list[dict]:
    """InService in the ASG and healthy in the target group, with private IPs."""
    ids = [i["InstanceId"] for i in st.instances if i["LifecycleState"] == "InService"]
    ids = [i for i in ids if st.targets.get(i) == "healthy"]
    if not ids:
        return []
    res = c.ec2.describe_instances(InstanceIds=ids)["Reservations"]
    out = []
    for r in res:
        for i in r["Instances"]:
            out.append(
                {
                    "id": i["InstanceId"],
                    "ip": i.get("PrivateIpAddress", ""),
                    "az": i["Placement"]["AvailabilityZone"],
                    "launch_time": i["LaunchTime"].timestamp() if hasattr(i["LaunchTime"], "timestamp") else None,
                }
            )
    return out


def fetch_json(url: str, timeout: float = 1.0) -> dict | None:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:  # noqa: S310 - private IPs only
            return json.loads(r.read())
    except (OSError, ValueError):
        return None


def fetch_stats(ips: list[str], timeout: float = 1.0, port: int = 8000) -> list[dict | None]:
    """Parallel GET http://<ip>:8000/internal/stats; None for a timeout or error."""
    if not ips:
        return []
    with ThreadPoolExecutor(max_workers=min(16, len(ips))) as pool:
        return list(pool.map(lambda ip: fetch_json(f"http://{ip}:{port}/internal/stats", timeout), ips))


# ---- reset timestamp (pre-flight cool-down between runs) -----------------------------------------
def mark_reset(ts: float | None = None) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    RESET_STAMP.write_text(f"{time.time() if ts is None else ts!r}\n")  # full precision: never negative


def seconds_since_reset() -> float | None:
    try:
        return time.time() - float(RESET_STAMP.read_text().strip())
    except (OSError, ValueError):
        return None

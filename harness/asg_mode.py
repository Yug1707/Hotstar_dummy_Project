#!/usr/bin/env python3
"""Switch the ASG between the scaling strategies of the experiments (plan §6.4).

usage: asg_mode.py static N | reactive | proactive | scheduled AT_UTC N | desired N | reset
                   [--no-wait] [--quiet-s 120] [--timeout-s 900]

Every mode (except `desired`) first deletes all scaling policies and scheduled actions, then sets the
group, waits until it is stable (unless --no-wait), checks that exactly the expected policies and
scheduled actions exist (exit 2 otherwise) and prints the final configuration as JSON on stdout.

  static N        min = max = desired = N                     (E1, E2, E6, E7)
  reactive        1..6, desired 1, target tracking CPU 50 %    (E3)
  proactive       1..6, desired 1, no policy: proactive_scaler.py owns desired (E4)
  scheduled AT N  reactive + scheduled action at AT: min = desired = N   (E4d, AWS-native pre-warm)
  desired N       only set desired within the current min/max (E5 boot test)
  reset           1..6, desired 1, nothing attached; records the time for the runner's cool-down
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime

import common
from common import MAX_CAP, log

REACTIVE_POLICY = "cpu50"
SCHEDULED_ACTION = "hsl-prewarm"


def clear(asg, name: str) -> None:
    for p in asg.describe_policies(AutoScalingGroupName=name).get("ScalingPolicies", []):
        asg.delete_policy(AutoScalingGroupName=name, PolicyName=p["PolicyName"])
        log("deleted policy", p["PolicyName"])
    for a in asg.describe_scheduled_actions(AutoScalingGroupName=name).get("ScheduledUpdateGroupActions", []):
        asg.delete_scheduled_action(AutoScalingGroupName=name, ScheduledActionName=a["ScheduledActionName"])
        log("deleted scheduled action", a["ScheduledActionName"])


def check_n(n: int) -> int:
    if not 1 <= n <= MAX_CAP:
        raise SystemExit(f"N must be between 1 and {MAX_CAP}, got {n}")
    return n


def put_reactive(asg, name: str) -> None:
    asg.put_scaling_policy(
        AutoScalingGroupName=name,
        PolicyName=REACTIVE_POLICY,
        PolicyType="TargetTrackingScaling",
        EstimatedInstanceWarmup=120,
        TargetTrackingConfiguration={
            "PredefinedMetricSpecification": {"PredefinedMetricType": "ASGAverageCPUUtilization"},
            "TargetValue": 50.0,
        },
    )


def apply(asg, name: str, mode: str, args: list[str]) -> tuple[int, set[str], set[str]]:
    """Apply a mode. Returns (desired to wait for, expected policy names, expected scheduled actions)."""
    if mode == "desired":
        n = check_n(int(args[0]))
        asg.set_desired_capacity(AutoScalingGroupName=name, DesiredCapacity=n, HonorCooldown=False)
        return (
            n,
            {p["PolicyName"] for p in asg.describe_policies(AutoScalingGroupName=name)["ScalingPolicies"]},
            {
                a["ScheduledActionName"]
                for a in asg.describe_scheduled_actions(AutoScalingGroupName=name)["ScheduledUpdateGroupActions"]
            },
        )

    clear(asg, name)
    if mode == "static":
        n = check_n(int(args[0]))
        asg.update_auto_scaling_group(AutoScalingGroupName=name, MinSize=n, MaxSize=n, DesiredCapacity=n)
        return n, set(), set()
    if mode in ("proactive", "reset"):
        asg.update_auto_scaling_group(AutoScalingGroupName=name, MinSize=1, MaxSize=MAX_CAP, DesiredCapacity=1)
        return 1, set(), set()
    if mode == "reactive":
        asg.update_auto_scaling_group(AutoScalingGroupName=name, MinSize=1, MaxSize=MAX_CAP, DesiredCapacity=1)
        put_reactive(asg, name)
        return 1, {REACTIVE_POLICY}, set()
    if mode == "scheduled":
        at = datetime.fromisoformat(args[0].replace("Z", "+00:00"))
        n = check_n(int(args[1]))
        asg.update_auto_scaling_group(AutoScalingGroupName=name, MinSize=1, MaxSize=MAX_CAP, DesiredCapacity=1)
        put_reactive(asg, name)
        asg.put_scheduled_update_group_action(
            AutoScalingGroupName=name, ScheduledActionName=SCHEDULED_ACTION, StartTime=at, MinSize=n, DesiredCapacity=n
        )
        return 1, {REACTIVE_POLICY}, {SCHEDULED_ACTION}
    raise SystemExit(f"unknown mode {mode!r}")


def snapshot(asg, name: str) -> dict:
    g = common.describe_group(asg, name)
    return {
        "asg_name": name,
        "min": g["MinSize"],
        "max": g["MaxSize"],
        "desired": g["DesiredCapacity"],
        "policies": sorted(
            p["PolicyName"] for p in asg.describe_policies(AutoScalingGroupName=name)["ScalingPolicies"]
        ),
        "scheduled_actions": sorted(
            a["ScheduledActionName"]
            for a in asg.describe_scheduled_actions(AutoScalingGroupName=name)["ScheduledUpdateGroupActions"]
        ),
        "captured_utc": common.utc_iso(),
    }


def self_check(cfg: dict, policies: set[str], scheduled: set[str]) -> list[str]:
    errs = []
    if set(cfg["policies"]) != policies:
        errs.append(f"policies {cfg['policies']} != expected {sorted(policies)}")
    if set(cfg["scheduled_actions"]) != scheduled:
        errs.append(f"scheduled actions {cfg['scheduled_actions']} != expected {sorted(scheduled)}")
    return errs


ARITY = {"static": 1, "reactive": 0, "proactive": 0, "scheduled": 2, "desired": 1, "reset": 0}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("mode", choices=sorted(ARITY))
    ap.add_argument("args", nargs="*")
    ap.add_argument("--no-wait", action="store_true")
    ap.add_argument("--quiet-s", type=float, default=120)
    ap.add_argument("--timeout-s", type=float, default=900)
    a = ap.parse_args(argv)
    if len(a.args) != ARITY[a.mode]:
        ap.error(f"{a.mode} takes {ARITY[a.mode]} argument(s)")

    env = common.Env.from_environ()
    c = common.clients(env.region)
    desired, policies, scheduled = apply(c.asg, env.asg_name, a.mode, a.args)
    log(f"mode {a.mode} {' '.join(a.args)} applied; desired={desired}")
    if not a.no_wait:
        log(f"waiting for {desired} healthy instance(s) and {a.quiet_s:.0f}s of quiet ...")
        common.wait_stable(lambda: common.group_state(c, env), desired, quiet_s=a.quiet_s, timeout_s=a.timeout_s)
        log("stable")
    if a.mode == "reset":
        common.mark_reset()
    cfg = snapshot(c.asg, env.asg_name)
    cfg["mode"] = " ".join([a.mode, *a.args])
    print(json.dumps(cfg))
    errs = self_check(cfg, policies, scheduled)
    for e in errs:
        log("SELF-CHECK FAILED:", e)
    return 2 if errs else 0


if __name__ == "__main__":
    sys.exit(main())

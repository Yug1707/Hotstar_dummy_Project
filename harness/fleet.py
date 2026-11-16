#!/usr/bin/env python3
"""Run commands on the app instances through SSM Run Command (no SSH anywhere).

usage: fleet.py auto-shed on|off          E6: set AUTO_SHED in /etc/streamlite.env, restart the service,
                                          wait until every target is healthy again (baked AMI only)
       fleet.py boot-logs --out DIR [--ids i-1,i-2]
                                          E5: save /var/log/hsl-boot.log of each instance to DIR/<id>.log
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import common
from common import log

AUTO_SHED_CMD = (
    "set -e; sed -i '/^AUTO_SHED=/d' /etc/streamlite.env; echo AUTO_SHED={value} >> /etc/streamlite.env; "
    "systemctl restart streamlite"
)


def run_command(ssm, ids: list[str], commands: list[str], timeout_s: float = 120) -> dict[str, dict]:
    """send_command + poll get_command_invocation; returns {instance_id: {status, stdout, stderr}}."""
    cmd_id = ssm.send_command(
        InstanceIds=ids,
        DocumentName="AWS-RunShellScript",
        Parameters={"commands": commands},
        TimeoutSeconds=max(30, int(timeout_s)),
    )["Command"]["CommandId"]
    done: dict[str, dict] = {}
    deadline = time.time() + timeout_s
    while len(done) < len(ids) and time.time() < deadline:
        time.sleep(2)
        for iid in ids:
            if iid in done:
                continue
            try:
                r = ssm.get_command_invocation(CommandId=cmd_id, InstanceId=iid)
            except ssm.exceptions.InvocationDoesNotExist:
                continue
            if r["Status"] not in ("Pending", "InProgress", "Delayed"):
                done[iid] = {
                    "status": r["Status"],
                    "stdout": r.get("StandardOutputContent", ""),
                    "stderr": r.get("StandardErrorContent", ""),
                }
    for iid in ids:
        done.setdefault(iid, {"status": "TimedOut", "stdout": "", "stderr": ""})
    return done


def in_service_ids(c, env) -> list[str]:
    st = common.group_state(c, env, with_activities=False)
    return [i["InstanceId"] for i in st.instances if i["LifecycleState"] == "InService"]


def auto_shed(c, env, on: bool) -> int:
    ids = in_service_ids(c, env)
    if not ids:
        raise SystemExit("no InService instances")
    value = "true" if on else "false"
    res = run_command(c.ssm, ids, [AUTO_SHED_CMD.format(value=value)])
    bad = {i: r for i, r in res.items() if r["status"] != "Success"}
    for i, r in bad.items():
        log(f"fleet: {i} {r['status']} {r['stderr'][:200]}")
    log(f"fleet: AUTO_SHED={value} on {len(ids) - len(bad)}/{len(ids)} instances; waiting for healthy targets")
    st = common.group_state(c, env)
    common.wait_stable(lambda: common.group_state(c, env), st.desired, quiet_s=20, timeout_s=300)
    return 1 if bad else 0


def boot_logs(c, env, out: Path, ids: list[str] | None) -> int:
    ids = ids or in_service_ids(c, env)
    out.mkdir(parents=True, exist_ok=True)
    res = run_command(c.ssm, ids, ["cat /var/log/hsl-boot.log"])
    for iid, r in res.items():
        (out / f"{iid}.log").write_text(r["stdout"])
        log(f"fleet: boot log {iid}: {r['status']}, {len(r['stdout'].splitlines())} lines")
    return 0 if all(r["status"] == "Success" for r in res.values()) else 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s1 = sub.add_parser("auto-shed")
    s1.add_argument("state", choices=["on", "off"])
    s2 = sub.add_parser("boot-logs")
    s2.add_argument("--out", required=True)
    s2.add_argument("--ids", help="comma-separated instance ids (default: all InService)")
    a = ap.parse_args(argv)

    env = common.Env.from_environ()
    c = common.clients(env.region)
    if a.cmd == "auto-shed":
        return auto_shed(c, env, a.state == "on")
    return boot_logs(c, env, Path(a.out), a.ids.split(",") if a.ids else None)


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Lab lock: only one experiment may drive the single ASG at a time (TEAM plan §1, "Lab lock").

usage: lab_lock.py acquire EXP RUN      exit 0 = acquired, 3 = held by someone else (holder printed)
       lab_lock.py release
       lab_lock.py show

The lock is s3://$RESULTS_BUCKET/lab.lock, created with a conditional write (If-None-Match: *),
so two runners can never both acquire it.
"""

from __future__ import annotations

import getpass
import json
import os
import socket
import sys

import common

KEY = "lab.lock"


def s3():
    import boto3

    return boto3.client("s3", region_name=os.environ.get("AWS_REGION", "ap-south-1"))


def body(exp: str, run: str) -> bytes:
    owner = f"{getpass.getuser()}@{socket.gethostname().split('.')[0]}"
    return json.dumps({"owner": owner, "exp": exp, "run": run, "started": common.utc_iso()}).encode()


def acquire(client, bucket: str, exp: str, run: str) -> bool:
    from botocore.exceptions import ClientError

    try:
        client.put_object(Bucket=bucket, Key=KEY, Body=body(exp, run), IfNoneMatch="*")
        return True
    except ClientError as e:
        code = e.response.get("Error", {}).get("Code", "")
        if code in ("PreconditionFailed", "ConditionalRequestConflict", "412"):
            return False
        raise


def show(client, bucket: str) -> str | None:
    from botocore.exceptions import ClientError

    try:
        return client.get_object(Bucket=bucket, Key=KEY)["Body"].read().decode()
    except ClientError:
        return None


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    common.load_env()
    bucket = os.environ.get("RESULTS_BUCKET")
    if not bucket or not argv or argv[0] not in ("acquire", "release", "show"):
        print(__doc__, file=sys.stderr)
        return 2
    c = s3()
    if argv[0] == "acquire":
        if len(argv) != 3:
            print("usage: lab_lock.py acquire EXP RUN", file=sys.stderr)
            return 2
        if acquire(c, bucket, argv[1], argv[2]):
            common.log("lab lock acquired")
            return 0
        common.log("lab lock HELD by:", show(c, bucket) or "?")
        return 3
    if argv[0] == "release":
        c.delete_object(Bucket=bucket, Key=KEY)
        common.log("lab lock released")
        return 0
    print(show(c, bucket) or "free")
    return 0


if __name__ == "__main__":
    sys.exit(main())

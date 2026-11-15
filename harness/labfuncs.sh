#!/bin/bash
# Shared shell helpers for run_experiment.sh and boot_test.sh. Source it; do not run it.
# Expects HERE (harness dir) and PY (python interpreter) to be set by the caller.
# shellcheck disable=SC2034  # variables are used by the scripts that source this file

LOCKED=0

say() { printf '%s %s\n' "$(date -u +%FT%TZ)" "$*" >&2; }
die() { say "ERROR: $*"; exit "${2:-1}"; }

# Names from .env.tf (laptop) or /etc/profile.d/hsl.sh (loadgen, already in the environment).
load_stack_env() {
  local f
  for f in ./.env.tf "$HERE/../.env.tf"; do
    if [ -f "$f" ]; then
      set -a
      # shellcheck disable=SC1090
      source "$f"
      set +a
      break
    fi
  done
  export AWS_REGION="${AWS_REGION:-${REGION:-ap-south-1}}"
  export AWS_DEFAULT_REGION="$AWS_REGION"
  TG_ARN="${TG_ARN:-${TARGET_GROUP_ARN:-}}"
  export TG_ARN
}

cfg() { "$PY" "$HERE/exp_config.py" get "$1"; }

harness_sha() {
  if [ -f "$HERE/VERSION" ]; then cat "$HERE/VERSION"
  else git -C "$HERE" rev-parse --short HEAD 2>/dev/null || echo unknown
  fi
}

# ---- lab lock (one experiment at a time; plan TEAM §1 "Lab lock") -----------------------------
# Atomic S3 conditional write, done in boto3 (lab_lock.py) so it does not depend on the CLI version.
lock_acquire() {
  local rc=0
  "$PY" "$HERE/lab_lock.py" acquire "$1" "$2" || rc=$?
  [ "$rc" = 0 ] || die "lab lock not acquired (exit $rc); if it is stale: make lab-unlock" 3
  LOCKED=1
}

lock_release() {
  if [ "$LOCKED" = 1 ]; then
    "$PY" "$HERE/lab_lock.py" release
    LOCKED=0
  fi
}

# ---- meta.json ---------------------------------------------------------------------------------
meta_set() { # meta_set FILE jq-args... ; e.g. meta_set m.json --arg x 1 '.x = $x'
  local f=$1
  shift
  jq "$@" "$f" >"$f.tmp" && mv "$f.tmp" "$f"
}

# AMIs of the running app instances (records what was really tested).
app_amis() {
  aws ec2 describe-instances \
    --filters "Name=tag:aws:autoscaling:groupName,Values=$ASG_NAME" Name=instance-state-name,Values=running \
    --query 'Reservations[].Instances[].ImageId' --output text 2>/dev/null | tr '\t' '\n' | sort -u | paste -sd, -
}

# Background helpers: start_bg NAME cmd... ; stop_bg stops all of them (SIGTERM, then wait).
BG_PIDS=()
start_bg() {
  local name=$1
  shift
  "$@" &
  BG_PIDS+=("$!")
  say "started $name (pid $!)"
}
stop_bg() {
  local p
  for p in "${BG_PIDS[@]}"; do kill -TERM "$p" 2>/dev/null || true; done
  for p in "${BG_PIDS[@]}"; do wait "$p" 2>/dev/null || true; done
  BG_PIDS=()
}

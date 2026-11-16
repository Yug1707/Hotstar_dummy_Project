#!/bin/bash
# One experiment run, end to end (plan §6.8). Run it on the loadgen inside tmux.
#
# usage: run_experiment.sh [options] EXP RUN MODE PROFILE [K=V ...]
#   EXP      run id, e.g. E3, E2a_N3, E6_auto_shed     -> results/EXP/runRUN/
#   MODE     "static N" | reactive | "proactive [--prewarm N] [--headroom H] ..." | "scheduled +S N"
#            ("scheduled +120 4" = AWS scheduled action S seconds after k6 starts: min=desired=N)
#   PROFILE  step | fixed | spike
#   K=V      extra k6 env (FIXED_RPS=200 GUESS=150 MIX=match_only HOLD=3m SPEED=10 C1=10 ...)
# options:
#   --force             keep an existing run folder (renamed *.replaced-<ts>) and run again
#   --target alb|cloudfront   where k6 sends traffic (E7); default alb
#   --degrade 0|1       degrade level to set in SSM before k6 (E6); always restored to 0
#   --auto-shed         AUTO_SHED=true on the fleet for this run (E6); restored afterwards
#   --observe S         seconds to keep monitoring after k6 ends (default global.observe_s)
#   --no-cooldown       skip the wait for global.cooldown_s since the last reset
#   --no-cw / --no-s3 / --no-lock    skip CloudWatch collection / S3 sync / lab lock
#   --local URL         laptop dry run against URL (e.g. http://127.0.0.1:8000): no AWS at all
# examples:
#   run_experiment.sh E3 1 reactive spike
#   run_experiment.sh E4c 2 "proactive --prewarm 3" spike
#   run_experiment.sh E2a_N3 1 "static 3" fixed FIXED_RPS=200
#   run_experiment.sh DRY 1 reactive spike C1=10                      (acceptance dry run, T3.7)
#   run_experiment.sh --local http://127.0.0.1:8000 LOCAL 1 none spike C1=10 SPEED=10
# shellcheck disable=SC2016  # $vars inside single quotes are jq variables, not shell
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
PY=${PYTHON:-python3}
# shellcheck source=labfuncs.sh
source "$HERE/labfuncs.sh"

usage() { sed -n '2,24p' "$0" | sed 's/^# \{0,1\}//'; exit "${1:-2}"; }

FORCE=0 TARGET=alb DEGRADE="" AUTO_SHED=0 OBSERVE_S="" NO_COOLDOWN=0 NO_CW=0 NO_S3=0 NO_LOCK=0 LOCAL_URL=""
while [ $# -gt 0 ] && [[ $1 == --* ]]; do
  case $1 in
    --force) FORCE=1 ;;
    --target) TARGET=$2; shift ;;
    --degrade) DEGRADE=$2; shift ;;
    --auto-shed) AUTO_SHED=1 ;;
    --observe) OBSERVE_S=$2; shift ;;
    --no-cooldown) NO_COOLDOWN=1 ;;
    --no-cw) NO_CW=1 ;;
    --no-s3) NO_S3=1 ;;
    --no-lock) NO_LOCK=1 ;;
    --local) LOCAL_URL=$2; shift ;;
    -h | --help) usage 0 ;;
    *) say "unknown option $1"; usage 2 ;;
  esac
  shift
done
[ $# -ge 4 ] || usage 2
EXP=$1 RUN=$2 MODE=$3 PROFILE=$4
shift 4
K6_KV=("$@")

[[ $EXP =~ ^[A-Za-z0-9_-]+$ ]] || die "EXP must be [A-Za-z0-9_-]+"
[[ $RUN =~ ^[0-9]+$ ]] || die "RUN must be a number"
[[ $PROFILE =~ ^(step|fixed|spike)$ ]] || die "PROFILE must be step, fixed or spike"
[[ $TARGET =~ ^(alb|cloudfront)$ || -n $LOCAL_URL ]] || die "--target must be alb or cloudfront"
[[ -z $DEGRADE || $DEGRADE =~ ^[01]$ ]] || die "--degrade must be 0 or 1"
command -v k6 >/dev/null || die "k6 not found"
command -v jq >/dev/null || die "jq not found"

LOCAL=0
[ -n "$LOCAL_URL" ] && LOCAL=1 NO_CW=1 NO_S3=1 NO_LOCK=1 NO_COOLDOWN=1 TARGET=local

# ---- config -------------------------------------------------------------------------------------
C1=${C1:-$(cfg global.c1)}
SPEED=1
K6_E=()
for kv in "${K6_KV[@]}"; do
  [[ $kv == *=* ]] || die "extra k6 args must be K=V, got '$kv'"
  case ${kv%%=*} in
    C1) C1=${kv#*=} ;;
    SPEED) SPEED=${kv#*=}; K6_E+=(-e "$kv") ;;
    *) K6_E+=(-e "$kv") ;;
  esac
done
WORK_SCALE=$(cfg global.work_scale)
INSTANCE_TYPE=$(cfg global.instance_type)
COOLDOWN_S=$(cfg global.cooldown_s)
if [ -z "$OBSERVE_S" ]; then
  if [ "$LOCAL" = 1 ]; then OBSERVE_S=0; else OBSERVE_S=$(cfg global.observe_s); fi
fi

read -ra MW <<<"$MODE"
ASG_MODE=${MW[0]}
SCALER_ARGS=()
PREWARM=1
case $ASG_MODE in
  static) [ ${#MW[@]} -eq 2 ] || die "MODE static needs N" ;;
  reactive) ;;
  proactive)
    SCALER_ARGS=("${MW[@]:1}")
    for ((i = 1; i < ${#MW[@]}; i++)); do [ "${MW[i]}" = --prewarm ] && PREWARM=${MW[i + 1]}; done ;;
  scheduled) [[ ${#MW[@]} -eq 3 && ${MW[1]} =~ ^\+[0-9]+$ ]] || die 'MODE scheduled needs "+SECONDS N"' ;;
  none) [ "$LOCAL" = 1 ] || die "MODE none is only for --local" ;;
  *) die "unknown MODE '$MODE'" ;;
esac

if [ "$LOCAL" = 0 ]; then
  load_stack_env
  : "${ASG_NAME:?missing ASG_NAME (source /etc/profile.d/hsl.sh or make env)}" "${TG_ARN:?}" "${RESULTS_BUCKET:?}"
  if [ "$TARGET" = cloudfront ]; then BASE=${CLOUDFRONT_URL:?CloudFront is not enabled yet (account not verified): only --target alb works}; else BASE="http://${ALB_DNS:?}"; fi
else
  BASE=$LOCAL_URL
fi

RESULTS_DIR=${RESULTS_DIR:-results}
OUT="$RESULTS_DIR/$EXP/run$RUN"
if [ -e "$OUT" ]; then
  [ "$FORCE" = 1 ] || die "$OUT exists (runs are never overwritten; use --force to keep it aside and rerun)"
  mv "$OUT" "$OUT.replaced-$(date -u +%Y%m%dT%H%M%SZ)"
fi
mkdir -p "$OUT/raw"
META="$OUT/meta.json"
exec > >(tee -a "$OUT/runner.log") 2>&1
say "run $EXP run$RUN mode='$MODE' profile=$PROFILE target=$TARGET base=$BASE c1=$C1 out=$OUT"

# ---- cleanup: always runs (normal end, error, Ctrl-C, SSM disconnect) ---------------------------
ASG_TOUCHED=0 DEGRADE_SET=0 SHED_SET=0
cleanup() {
  local rc=$?
  set +e
  stop_bg
  if [ "$SHED_SET" = 1 ]; then say "restoring AUTO_SHED=false"; "$PY" "$HERE/fleet.py" auto-shed off; fi
  if [ "$DEGRADE_SET" = 1 ]; then
    aws ssm put-parameter --name /streamlite/degrade_level --value 0 --type String --overwrite >/dev/null &&
      say "degrade_level restored to 0"
  fi
  if [ "$ASG_TOUCHED" = 1 ]; then "$PY" "$HERE/asg_mode.py" reset --no-wait >/dev/null && say "ASG reset (no wait)"; fi
  if [ "$NO_S3" = 0 ] && [ -d "$OUT" ]; then
    aws s3 sync "$RESULTS_DIR/$EXP/" "s3://$RESULTS_BUCKET/results/$EXP/" --only-show-errors && say "synced to S3"
  fi
  lock_release
  say "done (exit $rc): $OUT"
  exit "$rc"
}
trap cleanup EXIT
trap 'say "interrupted"; exit 130' INT TERM

# ---- pre-flight ---------------------------------------------------------------------------------
NOTES=()
[ "$NO_LOCK" = 1 ] || lock_acquire "$EXP" "$RUN"

if [ "$NO_COOLDOWN" = 0 ]; then
  since=$("$PY" -c "import sys; sys.path.insert(0, '$HERE'); import common; s = common.seconds_since_reset(); print(-1 if s is None else int(s))")
  if [ "$since" -lt 0 ]; then
    say "no reset recorded on this machine: resetting the ASG now"
    "$PY" "$HERE/asg_mode.py" reset >/dev/null
    since=0
  fi
  if [ "$since" -lt "$COOLDOWN_S" ]; then
    say "cool-down: last reset ${since}s ago, waiting $((COOLDOWN_S - since))s"
    sleep $((COOLDOWN_S - since))
  fi
fi

# loadgen must be idle (<0.5 load1); wait up to 2 min. Laptops (--local) are never idle: note only.
if [ "$LOCAL" = 0 ]; then
  for _ in $(seq 1 24); do
    load1=$(cut -d' ' -f1 /proc/loadavg)
    awk -v l="$load1" 'BEGIN{exit !(l < 0.5)}' && break
    sleep 5
  done
fi
load1=$(cut -d' ' -f1 /proc/loadavg)
awk -v l="$load1" 'BEGIN{exit !(l < 0.5)}' || NOTES+=("loadgen load1=$load1 at start (>= 0.5)")

if [ "$LOCAL" = 0 ]; then
  cur=$(aws ssm get-parameter --name /streamlite/degrade_level --query Parameter.Value --output text)
  want=${DEGRADE:-0}
  if [ "$cur" != "$want" ]; then
    aws ssm put-parameter --name /streamlite/degrade_level --value "$want" --type String --overwrite >/dev/null
    [ "$want" = 0 ] && NOTES+=("degrade_level was $cur at start; set to 0")
    say "degrade_level $cur -> $want; waiting 10 s for the app pollers"
    sleep 10
  fi
  [ "$want" = 1 ] && DEGRADE_SET=1
fi

# ---- scaling mode -------------------------------------------------------------------------------
ASG_JSON=null
if [ "$LOCAL" = 0 ]; then
  ASG_TOUCHED=1
  case $ASG_MODE in
    static) ASG_JSON=$("$PY" "$HERE/asg_mode.py" static "${MW[1]}") ;;
    reactive | scheduled) ASG_JSON=$("$PY" "$HERE/asg_mode.py" reactive) ;;
    proactive)
      ASG_JSON=$("$PY" "$HERE/asg_mode.py" proactive)
      if [ "$PREWARM" -gt 1 ]; then "$PY" "$HERE/proactive_scaler.py" --prewarm-only "$PREWARM"; fi ;;
  esac
  if [ "$AUTO_SHED" = 1 ]; then SHED_SET=1; "$PY" "$HERE/fleet.py" auto-shed on; fi
  start_bg monitor "$PY" "$HERE/monitor_asg.py" --out "$OUT" --interval "${MONITOR_INTERVAL:-5}" --stats
fi
start_bg cpu "$PY" "$HERE/sample_cpu.py" --out "$OUT/loadgen_cpu.csv" --interval 5

TOKEN=${TOKEN:-}
if [ -z "$TOKEN" ]; then
  if [ "$LOCAL" = 1 ]; then TOKEN=local
  else TOKEN=$(aws ssm get-parameter --name /streamlite/loadtest_token --with-decryption --query Parameter.Value --output text)
  fi
fi
APP_VERSION=$(curl -s --max-time 5 "$BASE/api/v1/whoami" -H "X-Load-Test: $TOKEN" | jq -r '.version // "unknown"' 2>/dev/null || echo unknown)
AMIS=""
[ "$LOCAL" = 0 ] && AMIS=$(app_amis)

K6_START=$(date +%s.%N)
if [ "$ASG_MODE" = scheduled ]; then
  at=$(date -u -d "@$(awk -v t="$K6_START" -v o="${MW[1]#+}" -v s="$SPEED" 'BEGIN{printf "%d", t + o / s}')" +%FT%TZ)
  ASG_JSON=$("$PY" "$HERE/asg_mode.py" scheduled "$at" "${MW[2]}" --no-wait)
fi
if [ "$ASG_MODE" = proactive ]; then
  floor_until=$(awk -v t="$K6_START" -v s="$SPEED" 'BEGIN{printf "%.0f", t + 780 / s}')
  start_bg scaler "$PY" "$HERE/proactive_scaler.py" --per-instance-rps "$C1" --floor-until "$floor_until" \
    --out "$OUT/scaler.csv" "${SCALER_ARGS[@]}"
fi

jq -n \
  --arg exp "$EXP" --argjson run "$RUN" --arg mode "$MODE" --arg profile "$PROFILE" --arg target "$TARGET" \
  --arg base "$BASE" --arg start "$(date -u -d "@${K6_START%.*}" +%FT%TZ)" --argjson start_ts "$K6_START" \
  --argjson c1 "$C1" --arg ws "$WORK_SCALE" --arg itype "$INSTANCE_TYPE" --arg amis "$AMIS" \
  --arg app "$APP_VERSION" --arg hsha "$(harness_sha)" --arg region "${AWS_REGION:-local}" \
  --argjson asg "$ASG_JSON" --argjson local "$LOCAL" --arg degrade "${DEGRADE:-0}" --argjson shed "$AUTO_SHED" \
  --arg scaler "${SCALER_ARGS[*]}" --arg kv "${K6_KV[*]}" --argjson speed "$SPEED" \
  '{exp: $exp, run: $run, valid: null, mode: $mode, profile: $profile, target: $target, base_url: $base,
    k6_start_utc: $start, k6_start_ts: $start_ts, k6_end_utc: null, k6_end_ts: null,
    c1: $c1, work_scale: ($ws | tonumber? // $ws), instance_type: $itype, ami_id: $amis, app_version: $app,
    harness_sha: $hsha, region: $region, local: ($local == 1), speed: $speed,
    asg_config: $asg, scaler_args: (if $scaler == "" then null else $scaler end),
    degrade_level: ($degrade | tonumber), auto_shed: ($shed == 1), k6_env: $kv,
    events_s: null, validity: null, notes: ""}' >"$META"

# ---- load ---------------------------------------------------------------------------------------
say "k6 starting"
set +e
TOKEN=$TOKEN K6_CSV_TIME_FORMAT=unix_milli k6 run --quiet --discard-response-bodies --tag "run_id=$EXP-$RUN" \
  --out "csv=$OUT/raw/k6.csv.gz" -e "BASE_URL=$BASE" -e "C1=$C1" -e "OUT=$OUT" "${K6_E[@]}" \
  "$HERE/$PROFILE.js" 2>&1 | tee "$OUT/k6.log"
K6_RC=${PIPESTATUS[0]}
set -e
K6_END=$(date +%s.%N)
say "k6 finished (exit $K6_RC; 99 = a threshold was crossed, which is a result, not an error)"
meta_set "$META" --arg end "$(date -u -d "@${K6_END%.*}" +%FT%TZ)" --argjson end_ts "$K6_END" --argjson rc "$K6_RC" \
  '.k6_end_utc = $end | .k6_end_ts = $end_ts | .k6_exit_code = $rc'

if [ "$OBSERVE_S" -gt 0 ]; then
  say "observing scale-in for ${OBSERVE_S}s"
  sleep "$OBSERVE_S"
fi
stop_bg

if [ "$NO_CW" = 0 ]; then
  "$PY" "$HERE/collect_cw.py" --start "$K6_START" --end "$K6_END" --out "$OUT/cw" || NOTES+=("collect_cw failed")
fi

# ---- validity (a failing check marks the run invalid; the run is kept) --------------------------
SUM="$OUT/k6_summary.json"
DROPPED=-1 R429=-1
if [ -f "$SUM" ]; then
  DROPPED=$(jq '.metrics.dropped_iterations.values.count // 0' "$SUM")
  R429=$(jq '.metrics.http_429.values.count // 0' "$SUM")
else
  NOTES+=("k6_summary.json missing")
fi
CPU_MAX=$("$PY" "$HERE/sample_cpu.py" --max "$OUT/loadgen_cpu.csv")
[ "$K6_RC" = 0 ] || [ "$K6_RC" = 99 ] || NOTES+=("k6 exit code $K6_RC")
[ -f "$OUT/profile.json" ] && meta_set "$META" --slurpfile p "$OUT/profile.json" \
  '.events_s = ($p[0].events_s // null) | .steps = ($p[0].steps // null) | .profile_total_s = $p[0].total_s'
NOTES_STR=$(printf '%s; ' "${NOTES[@]}")
meta_set "$META" --argjson d "$DROPPED" --argjson r "$R429" --argjson cpu "$CPU_MAX" --argjson rc "$K6_RC" \
  --arg notes "${NOTES_STR%; }" \
  '.validity = {dropped_iterations: $d, loadgen_cpu_max: $cpu, http_429: $r}
   | .valid = ($d == 0 and $r == 0 and $cpu >= 0 and $cpu < 70 and ($rc == 0 or $rc == 99))
   | .notes = $notes'
say "validity: $(jq -c '{valid, validity, notes}' "$META")"

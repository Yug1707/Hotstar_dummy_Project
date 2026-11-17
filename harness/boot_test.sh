#!/bin/bash
# E5 boot-time test (plan §7.3): no k6. Scale FROM -> TO with the monitor at 2 s, then save each new
# instance's /var/log/hsl-boot.log. Deploy the mode first: `make tf-apply MODE=naive` (or baked).
#
# usage: boot_test.sh [--label baked|naive] [--from 1] [--to 5] [--force] [--no-lock] [--no-s3] EXP RUN
#   e.g. boot_test.sh --label naive E5_naive 1
# Output: results/EXP/runRUN/{meta.json, asg_timeline.csv, instances.csv, boot_logs/<id>.log}
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
PY=${PYTHON:-python3}
# shellcheck source=labfuncs.sh
source "$HERE/labfuncs.sh"

usage() { sed -n '2,8p' "$0" | sed 's/^# \{0,1\}//'; exit "${1:-2}"; }

LABEL="" FROM=1 TO=4 FORCE=0 NO_LOCK=0 NO_S3=0
while [ $# -gt 0 ] && [[ $1 == --* ]]; do
  case $1 in
    --label) LABEL=$2; shift ;;
    --from) FROM=$2; shift ;;
    --to) TO=$2; shift ;;
    --force) FORCE=1 ;;
    --no-lock) NO_LOCK=1 ;;
    --no-s3) NO_S3=1 ;;
    -h | --help) usage 0 ;;
    *) say "unknown option $1"; usage 2 ;;
  esac
  shift
done
[ $# -eq 2 ] || usage 2
EXP=$1 RUN=$2
[[ $EXP =~ ^[A-Za-z0-9_-]+$ && $RUN =~ ^[0-9]+$ ]] || die "bad EXP or RUN"
[[ $FROM =~ ^[1-4]$ && $TO =~ ^[1-4]$ && $TO -gt $FROM ]] || die "need 1 <= FROM < TO <= 4 (Free-plan fleet cap)"

load_stack_env
: "${ASG_NAME:?}" "${TG_ARN:?}" "${RESULTS_BUCKET:?}"
LABEL=${LABEL:-${USER_DATA_MODE:-baked}}

RESULTS_DIR=${RESULTS_DIR:-results}
OUT="$RESULTS_DIR/$EXP/run$RUN"
if [ -e "$OUT" ]; then
  [ "$FORCE" = 1 ] || die "$OUT exists (use --force to keep it aside and rerun)"
  mv "$OUT" "$OUT.replaced-$(date -u +%Y%m%dT%H%M%SZ)"
fi
mkdir -p "$OUT"
META="$OUT/meta.json"
exec > >(tee -a "$OUT/runner.log") 2>&1

cleanup() {
  local rc=$?
  set +e
  stop_bg
  "$PY" "$HERE/asg_mode.py" reset --no-wait >/dev/null && say "ASG reset (no wait)"
  [ "$NO_S3" = 1 ] || aws s3 sync "$RESULTS_DIR/$EXP/" "s3://$RESULTS_BUCKET/results/$EXP/" --only-show-errors
  lock_release
  say "done (exit $rc): $OUT"
  exit "$rc"
}
trap cleanup EXIT
trap 'say "interrupted"; exit 130' INT TERM

[ "$NO_LOCK" = 1 ] || lock_acquire "$EXP" "$RUN"

say "E5 $LABEL: settle at $FROM"
"$PY" "$HERE/asg_mode.py" proactive >/dev/null # 1..6, no policies
[ "$FROM" -gt 1 ] && "$PY" "$HERE/asg_mode.py" desired "$FROM" --quiet-s 60 >/dev/null
BASE_AMIS=$(app_amis)

start_bg monitor "$PY" "$HERE/monitor_asg.py" --out "$OUT" --interval 2
sleep 4
T0=$(date +%s.%N)
say "scaling $FROM -> $TO"
"$PY" "$HERE/asg_mode.py" desired "$TO" --quiet-s 30 --timeout-s 900 >"$OUT/asg_config.json"
T1=$(date +%s.%N)
sleep 4
stop_bg
say "all $TO healthy after $(awk -v a="$T0" -v b="$T1" 'BEGIN{printf "%.0f", b - a}')s"

NEW_IDS=$(awk -F, -v t0="$T0" 'NR > 1 && $4 + 0 >= t0 {print $1}' "$OUT/instances.csv" | paste -sd, -)
if [ -z "$NEW_IDS" ] || ! "$PY" "$HERE/fleet.py" boot-logs --out "$OUT/boot_logs" --ids "$NEW_IDS"; then
  say "boot logs incomplete"
fi

jq -n --arg exp "$EXP" --argjson run "$RUN" --arg label "$LABEL" --argjson from "$FROM" --argjson to "$TO" \
  --argjson t0 "$T0" --argjson t1 "$T1" --arg new "$NEW_IDS" --arg base_amis "$BASE_AMIS" --arg amis "$(app_amis)" \
  --arg hsha "$(harness_sha)" --arg region "$AWS_REGION" --slurpfile asg "$OUT/asg_config.json" \
  '{exp: $exp, run: $run, valid: true, mode: ("boot " + $label), profile: "none", label: $label,
    from: $from, to: $to, scale_start_ts: $t0, all_healthy_ts: $t1, all_healthy_s: ($t1 - $t0),
    new_instances: ($new | split(",") | map(select(. != ""))), ami_id: $amis, ami_before: $base_amis,
    harness_sha: $hsha, region: $region, asg_config: $asg[0], notes: ""}' >"$META"
say "meta: $(jq -c '{label, all_healthy_s, new_instances}' "$META")"

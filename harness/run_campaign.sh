#!/bin/bash
# Run a list of experiments back to back (plan §6.8). Each non-comment line is `exp.sh` arguments.
# The 5-min reset gap between runs is enforced by run_experiment.sh's cool-down. Run inside tmux.
#
# usage: run_campaign.sh [--keep-going] CAMPAIGN_FILE        e.g. run_campaign.sh campaign_example.txt
set -uo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)

KEEP=0
[ "${1:-}" = --keep-going ] && { KEEP=1; shift; }
[ $# -eq 1 ] && [ -f "$1" ] || { sed -n '2,5p' "$0" | sed 's/^# \{0,1\}//'; exit 2; }

LOG="campaign-$(date -u +%Y%m%dT%H%M%SZ).log"
total=0 ok=0 failed=0
while IFS= read -r line || [ -n "$line" ]; do
  line=${line%%#*}
  read -ra a <<<"$line"
  [ ${#a[@]} -eq 0 ] && continue
  total=$((total + 1))
  echo "$(date -u +%FT%TZ) START ${a[*]}" | tee -a "$LOG"
  if "$HERE/exp.sh" "${a[@]}" </dev/null; then
    ok=$((ok + 1))
    echo "$(date -u +%FT%TZ) OK    ${a[*]}" | tee -a "$LOG"
  else
    rc=$?
    failed=$((failed + 1))
    echo "$(date -u +%FT%TZ) FAIL  ${a[*]} (exit $rc)" | tee -a "$LOG"
    [ "$KEEP" = 1 ] || break
  fi
done <"$1"
echo "campaign: $ok/$total ok, $failed failed (log: $LOG)" | tee -a "$LOG"
[ "$failed" -eq 0 ]

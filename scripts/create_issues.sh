#!/usr/bin/env bash
# Creates labels and one GitHub issue per row of docs/backlog.tsv.
# Usage: scripts/create_issues.sh [--dry-run]
set -euo pipefail
cd "$(dirname "$0")/.."

dry=0; [ "${1:-}" = "--dry-run" ] && dry=1
run() { if [ $dry -eq 1 ]; then echo "+ $*"; else "$@"; fi; }

run gh label create P0 -c B60205 -d "must have" -f
run gh label create P1 -c FBCA04 -d "should have" -f
run gh label create P2 -c 0E8A16 -d "stretch" -f
for r in A B C; do run gh label create "role:$r" -c 5319E7 -f; done

tail -n +2 docs/backlog.tsv | while IFS=$'\t' read -r id title role prio est; do
  run gh issue create --title "$id $title" --label "$prio" --label "role:$role" \
    --body "Estimate: ${est} h. Spec: docs/IMPLEMENTATION_PLAN_DETAILED.md (search for $id). Merge order and reviewer: docs/TEAM_PLAN_3_PEOPLE.md §3."
done

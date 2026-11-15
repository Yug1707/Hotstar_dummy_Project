#!/bin/bash
# Put the ASG back to the idle demo state: no scaling policies, no scheduled actions,
# min 1 / max 6 / desired 1. Used by `make destroy-lab` until automation/asg_mode.py (Phase 3)
# provides `asg_mode.py reset`; afterwards both do the same thing.
set -euo pipefail
cd "$(dirname "$0")/.."
[ -f .env.tf ] || { echo "missing .env.tf: run 'make env' first" >&2; exit 2; }
set -a
# shellcheck disable=SC1091
source .env.tf
set +a
: "${ASG_NAME:?}" "${REGION:?}"
export AWS_REGION="$REGION"

for p in $(aws autoscaling describe-policies --auto-scaling-group-name "$ASG_NAME" \
  --query 'ScalingPolicies[].PolicyName' --output text); do
  aws autoscaling delete-policy --auto-scaling-group-name "$ASG_NAME" --policy-name "$p"
  echo "deleted policy $p"
done

for a in $(aws autoscaling describe-scheduled-actions --auto-scaling-group-name "$ASG_NAME" \
  --query 'ScheduledUpdateGroupActions[].ScheduledActionName' --output text); do
  aws autoscaling delete-scheduled-action --auto-scaling-group-name "$ASG_NAME" --scheduled-action-name "$a"
  echo "deleted scheduled action $a"
done

aws autoscaling update-auto-scaling-group --auto-scaling-group-name "$ASG_NAME" \
  --min-size 1 --max-size 6 --desired-capacity 1
echo "$ASG_NAME reset: min 1, max 6, desired 1"

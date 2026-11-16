#!/bin/bash
# Put the ASG back to the idle demo state: no scaling policies, no scheduled actions,
# min N / max ASG_MAX / desired N, with N = $1 (default 1). `reset_asg.sh 0` pauses the stack
# (no app servers running; deploy_aws.sh pause). Same end state as `asg_mode.py reset` for N = 1.
set -euo pipefail
cd "$(dirname "$0")/.."
[ -f .env.tf ] || { echo "missing .env.tf: run 'make env' first" >&2; exit 2; }
set -a
# shellcheck disable=SC1091
source .env.tf
set +a
: "${ASG_NAME:?}" "${REGION:?}"
export AWS_REGION="$REGION"
N=${1:-1}
MAX=${ASG_MAX:-4}
[[ $N =~ ^[0-9]+$ ]] && [ "$N" -le "$MAX" ] || { echo "usage: reset_asg.sh [0..$MAX]" >&2; exit 2; }

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
  --min-size "$N" --max-size "$MAX" --desired-capacity "$N"
echo "$ASG_NAME reset: min $N, max $MAX, desired $N"

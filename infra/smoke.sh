#!/bin/bash
# Phase 2 acceptance check against the deployed stack (plan §5.4). Paste the output into the PR.
#   make smoke            checks 1-4 and 6 (no extra cost)
#   make smoke SPREAD=1   also check 5: scale to 3, confirm >=2 instances and >=2 AZs, scale back to 1
# Reads names from .env.tf (written by `make env`).
set -uo pipefail
cd "$(dirname "$0")/.." || exit 2
[ -f .env.tf ] || { echo "missing .env.tf: run 'make env' first" >&2; exit 2; }
set -a
# shellcheck disable=SC1091
source .env.tf
set +a
: "${CLOUDFRONT_URL:?}" "${ALB_DNS:?}" "${ASG_NAME:?}" "${TARGET_GROUP_ARN:?}" "${REGION:?}"
export AWS_REGION="$REGION"

pass=0
fail=0
ok() { echo "PASS  $*"; pass=$((pass + 1)); }
bad() { echo "FAIL  $*"; fail=$((fail + 1)); }

CF=1
[ -n "${CLOUDFRONT_ID:-}" ] || CF=0 # enable_cloudfront = false: account not verified for CloudFront yet
skip() { echo "SKIP  $*"; }
if [ "$CF" = 1 ]; then echo "CloudFront: $CLOUDFRONT_URL"; else echo "CloudFront: not enabled yet (check 4 skipped, check 1 via the ALB)"; fi
echo "ALB:        http://$ALB_DNS"
echo

# 1. dashboard: from S3 through CloudFront, or (no CloudFront yet) the copy of web/ inside the image, via the ALB
if [ "$CF" = 0 ]; then
  if curl -sf --max-time 10 "http://$ALB_DNS/" | grep -q "<title>"; then
    ok "1 site: GET / returns the dashboard (served by the app, no CloudFront yet)"
  else
    bad "1 site: GET / via the ALB (image without web/?)"
  fi
elif curl -sf --max-time 10 "$CLOUDFRONT_URL/" | grep -q "<title>"; then
  ok "1 site: GET / returns the dashboard"
else
  bad "1 site: GET / (run 'make publish-site'?)"
fi

# 2. API through CloudFront (or the ALB alone) -> instance
via=CloudFront
[ "$CF" = 1 ] || via=ALB
if id=$(curl -sf --max-time 10 "$CLOUDFRONT_URL/api/v1/whoami" | jq -er .instance_id); then
  ok "2 api: whoami via $via -> $id"
else
  bad "2 api: whoami via $via"
fi

# 3. /internal/* is blocked at the ALB (F2), both via CloudFront and directly
cf_code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 "$CLOUDFRONT_URL/internal/stats")
alb_code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 "http://$ALB_DNS/internal/stats")
if [ "$cf_code" = 404 ] && [ "$alb_code" = 404 ]; then
  ok "3 internal: /internal/stats -> 404 (CloudFront and ALB)"
else
  bad "3 internal: CloudFront=$cf_code ALB=$alb_code, expected 404"
fi

# 4. match state is cached at the edge (E7 precondition)
if [ "$CF" = 0 ]; then
  skip "4 cdn: needs CloudFront"
else
  curl -s -o /dev/null --max-time 10 "$CLOUDFRONT_URL/api/v1/match/state"
  xcache=$(curl -sI --max-time 10 "$CLOUDFRONT_URL/api/v1/match/state" | tr -d '\r' | awk -F': ' 'tolower($1)=="x-cache"{print $2}')
  if [[ "$xcache" == Hit* ]]; then
    ok "4 cdn: second GET /api/v1/match/state -> $xcache"
  else
    bad "4 cdn: x-cache='$xcache', expected 'Hit from cloudfront'"
  fi
fi

# 5. (optional, costs ~2 instance-minutes) the ALB spreads requests across instances and AZs
if [ "${SPREAD:-0}" = 1 ]; then
  echo "      scaling $ASG_NAME to 3 for check 5..."
  aws autoscaling set-desired-capacity --auto-scaling-group-name "$ASG_NAME" --desired-capacity 3
  healthy=0
  for _ in $(seq 1 60); do
    healthy=$(aws elbv2 describe-target-health --target-group-arn "$TARGET_GROUP_ARN" \
      --query "length(TargetHealthDescriptions[?TargetHealth.State=='healthy'])" --output text)
    [ "$healthy" -ge 3 ] && break
    sleep 5
  done
  ids=()
  azs=()
  for _ in $(seq 1 30); do
    body=$(curl -s --max-time 5 "http://$ALB_DNS/api/v1/whoami" -H "Connection: close")
    ids+=("$(jq -r .instance_id <<<"$body")")
    azs+=("$(jq -r .az <<<"$body")")
  done
  n_ids=$(printf '%s\n' "${ids[@]}" | sort -u | grep -vcE '^(null)?$')
  n_azs=$(printf '%s\n' "${azs[@]}" | sort -u | grep -vcE '^(null)?$')
  if [ "$n_ids" -ge 2 ] && [ "$n_azs" -ge 2 ]; then
    ok "5 spread: $healthy healthy, 30 requests hit $n_ids instances in $n_azs AZs"
  else
    bad "5 spread: $healthy healthy, $n_ids instances, $n_azs AZs (expected >=2 and >=2)"
  fi
  aws autoscaling set-desired-capacity --auto-scaling-group-name "$ASG_NAME" --desired-capacity 1
  echo "      scaled back to 1"
else
  echo "SKIP  5 spread (run with SPREAD=1)"
fi

# 6. no security group in the project opens port 22
open22=$(aws ec2 describe-security-groups --filters Name=tag:project,Values=hotstar-scale-lab --output json |
  jq '[.SecurityGroups[].IpPermissions[]
       | select(.IpProtocol == "-1" or ((.FromPort // 0) <= 22 and (.ToPort // 65535) >= 22))] | length')
if [ "$open22" = 0 ]; then
  ok "6 ssh: no project security group allows port 22"
else
  bad "6 ssh: $open22 rule(s) cover port 22"
fi

echo
echo "smoke: $pass passed, $fail failed"
[ "$fail" -eq 0 ]

#!/bin/bash
# Hotstar Scale Lab: the one script for everything on AWS.
#
# Run it on YOUR computer (Linux, macOS, WSL or AWS CloudShell) from the repo folder. It creates the
# AWS servers itself; you never log in to a server. It is safe to run again: every step checks
# what already exists and only does what is missing.
#
#   ./deploy_aws.sh            (= up) everything for the live HTTPS URL:
#                              tools, account checks, instance type, state bucket, vCPU quota, AMI,
#                              Terraform, site, smoke test
#   ./deploy_aws.sh lab        start a lab session (load generator + harness upload) and print next steps
#   ./deploy_aws.sh lab-down   end a lab session (ASG back to 1 instance, load generator removed)
#   ./deploy_aws.sh pause      stop every server (ASG to 0, no load generator) to save credit
#   ./deploy_aws.sh resume     start 1 app server again and wait until the URL works
#   ./deploy_aws.sh status     URLs, running instances, lab lock
#   ./deploy_aws.sh destroy    AFTER THE VIVA ONLY: delete everything (asks you to type 'destroy')
#
# AWS Free plan (USD 118 credit): only free-tier-eligible instance types can be launched, so the stack
# uses c7i-flex.large (2 vCPU, 4 GiB) for the app, the load generator and the Packer build, and at
# most 4 app servers. Rough cost: up ~USD 3/day (1 server + load balancer), paused ~USD 1/day,
# lab session ~USD 0.5/hour. Pause whenever nobody is using it; destroy after the viva.
#
# Before the first run: an AWS user with admin rights and `aws configure` done (or AWS_PROFILE set).
# Optional environment: ALERT_EMAILS="a@x.com,b@y.com"  IMAGE_TAG=<sha7>  YES=1 (no questions)
#                       APP_TYPE=<instance type> (skip the automatic Free-plan choice)
#                       CLOUDFRONT=on (try CloudFront again after AWS has verified the account)
# shellcheck disable=SC2016,SC2153  # literal $ / JMESPath backticks; SITE_BUCKET etc. come from .env.tf
set -euo pipefail

ROOT=$(cd "$(dirname "$0")" && pwd)
cd "$ROOT"
export AWS_REGION=ap-south-1 AWS_DEFAULT_REGION=ap-south-1 AWS_PAGER=""
TOOLS=${HSL_TOOLS:-$HOME/.cache/hsl-tools}
export PATH="$TOOLS/bin:$PATH"
TF_VERSION=1.17.2
PACKER_VERSION=1.16.2
TFVARS=infra/terraform.tfvars
TF="terraform -chdir=infra"

# ---- output helpers -----------------------------------------------------------------------------
if [ -t 1 ]; then B=$'\e[1m' G=$'\e[32m' Y=$'\e[33m' R=$'\e[31m' N=$'\e[0m'; else B="" G="" Y="" R="" N=""; fi
STEP=0
step() { STEP=$((STEP + 1)); printf '\n%s[%d] %s%s\n' "$B" "$STEP" "$*" "$N"; }
ok() { printf '    %sok%s  %s\n' "$G" "$N" "$*"; }
warn() { printf '    %s!!%s  %s\n' "$Y" "$N" "$*"; }
die() { printf '\n%sSTOPPED:%s %s\n' "$R" "$N" "$*" >&2; exit 1; }
ask() { # ask "question" -> 0 for yes
  [ "${YES:-0}" = 1 ] && return 0
  local a
  read -r -p "    $1 [y/N] " a
  [ "$a" = y ] || [ "$a" = Y ] || [ "$a" = yes ]
}

# ---- 1. tools -----------------------------------------------------------------------------------
os_arch() {
  local os arch
  case "$(uname -s)" in Linux) os=linux ;; Darwin) os=darwin ;; *) die "unsupported OS $(uname -s); use Linux, macOS, WSL or AWS CloudShell" ;; esac
  case "$(uname -m)" in x86_64 | amd64) arch=amd64 ;; aarch64 | arm64) arch=arm64 ;; *) die "unsupported CPU $(uname -m)" ;; esac
  echo "$os $arch"
}

version_ge() { # version_ge 1.17.2 1.10.0
  [ "$(printf '%s\n%s\n' "$2" "$1" | sort -V | head -1)" = "$2" ]
}

install_hashicorp() { # install_hashicorp terraform 1.17.2
  local name=$1 ver=$2 os arch tmp
  read -r os arch <<<"$(os_arch)"
  tmp=$(mktemp -d)
  curl -fsSL -o "$tmp/$name.zip" "https://releases.hashicorp.com/$name/$ver/${name}_${ver}_${os}_${arch}.zip" ||
    die "could not download $name $ver"
  unzip -oq "$tmp/$name.zip" "$name" -d "$TOOLS/bin"
  rm -rf "$tmp"
}

install_awscli() {
  local os arch tmp
  read -r os arch <<<"$(os_arch)"
  [ "$os" = linux ] || die "install the AWS CLI v2 first: https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html (macOS: 'brew install awscli')"
  tmp=$(mktemp -d)
  [ "$arch" = arm64 ] && arch=aarch64 || arch=x86_64
  curl -fsSL -o "$tmp/awscli.zip" "https://awscli.amazonaws.com/awscli-exe-linux-$arch.zip" || die "could not download the AWS CLI"
  unzip -q "$tmp/awscli.zip" -d "$tmp"
  "$tmp/aws/install" --install-dir "$TOOLS/aws-cli" --bin-dir "$TOOLS/bin" --update >/dev/null
  rm -rf "$tmp"
}

ensure_tools() {
  step "Tools"
  mkdir -p "$TOOLS/bin"
  local t
  for t in curl unzip git jq tar; do
    command -v "$t" >/dev/null || die "'$t' is missing. Install it (e.g. sudo apt install $t / sudo dnf install $t / brew install $t)"
  done
  ok "curl unzip git jq tar"
  if ! command -v aws >/dev/null; then
    warn "AWS CLI not found: installing into $TOOLS (no sudo needed)"
    install_awscli
  fi
  ok "$(aws --version 2>&1 | cut -d' ' -f1)"
  if ! command -v terraform >/dev/null || ! version_ge "$(terraform version -json | jq -r .terraform_version)" 1.10.0; then
    warn "Terraform >= 1.10 not found: installing $TF_VERSION into $TOOLS"
    install_hashicorp terraform "$TF_VERSION"
  fi
  ok "terraform $(terraform version -json | jq -r .terraform_version)"
  if ! command -v packer >/dev/null; then
    warn "Packer not found: installing $PACKER_VERSION into $TOOLS"
    install_hashicorp packer "$PACKER_VERSION"
  fi
  ok "packer $(packer version | head -1 | tr -d 'Packer v')"
}

# ---- 2. account ---------------------------------------------------------------------------------
check_account() {
  step "AWS account (region ap-south-1, Mumbai)"
  local id
  id=$(aws sts get-caller-identity --output json 2>/dev/null) ||
    die "AWS CLI has no working credentials. Run 'aws configure' (access key of an IAM user with AdministratorAccess) or set AWS_PROFILE, then run this script again."
  ACCOUNT=$(jq -r .Account <<<"$id")
  ok "account $ACCOUNT as $(jq -r .Arn <<<"$id")"
  case $(jq -r .Arn <<<"$id") in *:root) warn "you are using the ROOT user; an IAM user is safer (plan §3.3)" ;; esac
  if [ "$(aws ec2 describe-vpcs --filters Name=isDefault,Values=true --query 'length(Vpcs)' --output text)" = 0 ]; then
    warn "no default VPC in ap-south-1: creating it"
    aws ec2 create-default-vpc >/dev/null
  fi
  ok "default VPC present"
}

# ---- 2b. instance type the account may launch -> infra/instance.auto.tfvars (git-ignored) -------
# Free-plan accounts get "InvalidParameterCombination: The specified instance type is not eligible for
# Free Tier" for c6i.large. c7i-flex.large is eligible and has the same shape (2 vCPU, x86_64).
PREFERRED_TYPES="c7i-flex.large m7i-flex.large"

pick_instance_type() {
  step "Instance type (AWS Free plan check)"
  local plan elig c offered
  plan=$(aws freetier get-account-plan-state --region us-east-1 --query accountPlanType --output text 2>/dev/null || echo unknown)
  elig=$(aws ec2 describe-instance-types --filters Name=free-tier-eligible,Values=true \
    --query 'InstanceTypes[].InstanceType' --output text 2>/dev/null | tr '\t' '\n' | sort)
  APP_TYPE=${APP_TYPE:-}
  if [ -z "$APP_TYPE" ]; then
    for c in $PREFERRED_TYPES; do
      if grep -qx "$c" <<<"$elig"; then APP_TYPE=$c; break; fi
    done
  fi
  if [ -z "$APP_TYPE" ]; then
    if [ "$plan" != FREE ]; then
      APP_TYPE=c7i-flex.large # paid (or unknown) plan: any type may be launched, the eligible list does not matter
    elif grep -qx t3.small <<<"$elig"; then
      APP_TYPE=t3.small
      warn "only burstable types are eligible: using t3.small with unlimited CPU credits (small extra"
      warn "charge under load). Capacity per server (C1) will be much lower; that is fine, E1 measures it."
    else
      die "no suitable Free-plan instance type found (eligible here: $(echo "$elig" | tr '\n' ' ')). Set APP_TYPE=<type> and rerun."
    fi
  fi
  offered=$(aws ec2 describe-instance-type-offerings --location-type availability-zone \
    --filters "Name=instance-type,Values=$APP_TYPE" --query 'length(InstanceTypeOfferings)' --output text)
  [ "${offered:-0}" -ge 1 ] || die "$APP_TYPE is not offered in ap-south-1; set APP_TYPE=<type> and rerun"
  printf '# Written by deploy_aws.sh (account plan: %s). Git-ignored.\ninstance_type         = "%s"\nloadgen_instance_type = "%s"\n' \
    "$plan" "$APP_TYPE" "$APP_TYPE" >infra/instance.auto.tfvars
  ok "$APP_TYPE for app servers, load generator and Packer (account plan: $plan, offered in $offered AZs)"
}

# ---- 3. settings (suffix, emails) -> infra/terraform.tfvars (git-ignored) ----------------------
tfvar() { # tfvar NAME -> value from terraform.tfvars (simple string / list lines only)
  [ -f "$TFVARS" ] || return 0
  sed -nE "s/^[[:space:]]*$1[[:space:]]*=[[:space:]]*(.*)$/\1/p" "$TFVARS" | head -1 | sed -E 's/[[:space:]]*#.*$//'
}

ensure_settings() {
  step "Settings ($TFVARS)"
  if [ -f "$TFVARS" ]; then
    SUFFIX=$(tfvar suffix | tr -d '"')
    [ -n "$SUFFIX" ] || die "$TFVARS exists but has no suffix = \"...\" line"
    ok "using existing settings: suffix=$SUFFIX"
    return
  fi
  SUFFIX=$(od -An -N3 -tx1 /dev/urandom | tr -d ' \n') # 6 hex chars
  local emails=${ALERT_EMAILS:-}
  if [ -z "$emails" ] && [ "${YES:-0}" != 1 ]; then
    read -r -p "    Budget alert e-mails, comma separated (Enter = none): " emails
  fi
  local list
  list=$(printf '%s' "$emails" | tr -d ' ' | jq -R -c 'split(",") | map(select(length > 0))')
  cat >"$TFVARS" <<EOF
# Written by deploy_aws.sh on $(date -u +%F). Git-ignored. Edit and rerun ./deploy_aws.sh to apply.
suffix       = "$SUFFIX"
owner        = "it457-team"
alert_emails = $list
budget_usd   = 25 # alarm on gross monthly usage; the whole Free-plan credit is USD 118

# From the c7i-flex.large calibration (T2.7). Changing it rolls the fleet (instance refresh).
work_scale      = "2.0"
web_concurrency = 1
EOF
  ok "wrote $TFVARS (suffix=$SUFFIX, alerts=$list)"
}

# ---- 4. Terraform state bucket (created once, survives destroy) ---------------------------------
ensure_state_bucket() {
  step "Terraform state bucket"
  STATE_BUCKET="hsl-tfstate-$SUFFIX"
  if aws s3api head-bucket --bucket "$STATE_BUCKET" >/dev/null 2>&1; then
    ok "s3://$STATE_BUCKET exists"
  else
    aws s3api create-bucket --bucket "$STATE_BUCKET" --create-bucket-configuration LocationConstraint=ap-south-1 >/dev/null ||
      die "could not create s3://$STATE_BUCKET (name taken? delete the suffix line in $TFVARS and rerun)"
    aws s3api put-bucket-versioning --bucket "$STATE_BUCKET" --versioning-configuration Status=Enabled
    aws s3api put-public-access-block --bucket "$STATE_BUCKET" --public-access-block-configuration \
      BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true
    ok "created s3://$STATE_BUCKET (versioned, private)"
  fi
  printf 'bucket = "%s"\n' "$STATE_BUCKET" >infra/.backend.hcl
  $TF init -input=false -reconfigure -backend-config=.backend.hcl >/dev/null || die "terraform init failed"
  ok "terraform initialised with the S3 backend"
}

# ---- 5. vCPU quota ------------------------------------------------------------------------------
check_quota() {
  step "EC2 vCPU quota (Running On-Demand Standard instances)"
  local q pending
  q=$(aws service-quotas get-service-quota --service-code ec2 --quota-code L-1216C47A \
    --query 'Quota.Value' --output text 2>/dev/null | cut -d. -f1)
  q=${q:-0}
  if [ "$q" -ge 10 ]; then ok "$q vCPUs (experiments need 10)"; return; fi
  warn "quota is $q vCPUs; the experiments need 10 (4 app servers x 2 + load generator 2)"
  pending=$(aws service-quotas list-requested-service-quota-change-history-by-quota --service-code ec2 \
    --quota-code L-1216C47A --query "length(RequestedQuotas[?Status=='PENDING' || Status=='CASE_OPENED'])" \
    --output text 2>/dev/null || echo 0)
  if [ "${pending:-0}" != 0 ]; then
    warn "an increase request is already open; AWS usually answers within 1-3 days"
  elif ask "Request an increase to 16 vCPUs now? (free)"; then
    aws service-quotas request-service-quota-increase --service-code ec2 --quota-code L-1216C47A --desired-value 16 \
      --query 'RequestedQuota.Id' --output text | sed 's/^/    request id: /'
    warn "write the request id into docs/runbook.md; experiments must wait for approval"
  fi
  warn "until then: with $q vCPUs at most $(((q - 2) / 2)) app server(s) fit next to the load generator"
  [ "$q" -ge 4 ] || die "only $q vCPUs: not even the demo stack (2) + Packer builder (2) fits. Wait for the quota increase, then rerun."
  ok "enough for the demo stack; continuing"
}

# ---- 6. container image on GHCR -----------------------------------------------------------------
resolve_image() {
  step "Container image (GitHub Container Registry)"
  local owner token tags c
  owner=$(git remote get-url origin 2>/dev/null | sed -E 's#.*github\.com[:/]([^/]+)/.*#\1#' | tr '[:upper:]' '[:lower:]')
  owner=${GH_OWNER:-$owner}
  [ -n "$owner" ] || die "cannot tell the GitHub owner; set GH_OWNER=<github user or org>"
  token=$(curl -fsS "https://ghcr.io/token?scope=repository:$owner/streamlite:pull" | jq -r .token) ||
    die "GHCR is not reachable"
  tags=$(curl -fsS -H "Authorization: Bearer $token" "https://ghcr.io/v2/$owner/streamlite/tags/list?n=1000" |
    jq -r '.tags[]?' 2>/dev/null) ||
    die "ghcr.io/$owner/streamlite is not public (or not pushed yet). GitHub → your profile → Packages → streamlite → Package settings → Change visibility → Public"
  if [ -n "${IMAGE_TAG:-}" ]; then
    grep -qx "$IMAGE_TAG" <<<"$tags" || die "tag $IMAGE_TAG not in ghcr.io/$owner/streamlite (have: $(echo "$tags" | tr '\n' ' '))"
  else
    IMAGE_TAG=""
    for c in $(git log --format=%H -n 500 2>/dev/null | cut -c1-7); do
      if grep -qx "$c" <<<"$tags"; then IMAGE_TAG=$c; break; fi
    done
    [ -n "$IMAGE_TAG" ] || die "no image tag matches a commit of this branch; push to main (docker workflow) or set IMAGE_TAG"
  fi
  IMAGE="ghcr.io/$owner/streamlite:$IMAGE_TAG"
  ok "$IMAGE (public)"
}

# ---- 7. baked AMI -------------------------------------------------------------------------------
ensure_ami() {
  step "Server image (AMI) with the app pre-installed"
  local ami
  ami=$(aws ec2 describe-images --owners self --filters Name=tag:project,Values=hotstar-scale-lab \
    "Name=tag:git_sha,Values=$IMAGE_TAG" Name=state,Values=available \
    --query 'sort_by(Images,&CreationDate)[-1].ImageId' --output text)
  if [ "$ami" != None ] && [ -n "$ami" ]; then
    ok "reusing $ami (already built for $IMAGE_TAG)"
  else
    warn "building a new AMI with Packer (~6-8 min, one temporary $APP_TYPE)"
    rm -f infra/manifest.json
    packer init infra/streamlite.pkr.hcl >/dev/null
    packer build -color=false -var "image=$IMAGE" -var "tag=$IMAGE_TAG" -var "instance_type=$APP_TYPE" \
      infra/streamlite.pkr.hcl |
      sed -u 's/^/    | /' | grep -E '\| (==>|Build|---|amazon-ebs.al2023: (AMIs|ap-south-1|provision ok))|[Ee]rror' || true
    [ -f infra/manifest.json ] || die "Packer failed (see output above). Fallback: infra/README.md → 'Packer fallback'"
    ami=$(jq -r '.builds[-1].artifact_id | split(":")[1]' infra/manifest.json)
    ok "built $ami"
  fi
  printf 'ami_id = "%s"\n' "$ami" >infra/ami.auto.tfvars
}

# ---- 8. Terraform apply -------------------------------------------------------------------------
loadgen_running() {
  local id
  id=$($TF output -raw loadgen_instance_id 2>/dev/null || true)
  [ -n "$id" ] && [[ $id == i-* ]]
}

# New accounts: the Auto Scaling / ELB service-linked roles are created on first use and take a few
# seconds to become assumable ("Access denied when attempting to assume role ...AWSServiceRoleForAutoScaling").
ensure_service_roles() {
  local svc role created=0
  for svc in autoscaling elasticloadbalancing; do
    case $svc in autoscaling) role=AWSServiceRoleForAutoScaling ;; *) role=AWSServiceRoleForElasticLoadBalancing ;; esac
    if ! aws iam get-role --role-name "$role" >/dev/null 2>&1; then
      if aws iam create-service-linked-role --aws-service-name "$svc.amazonaws.com" >/dev/null 2>&1; then
        created=1
        ok "created service-linked role $role"
      else
        warn "could not create $role (it may be appearing right now); continuing"
      fi
    fi
  done
  if [ "$created" = 1 ]; then
    printf '    waiting 30 s for the new roles to propagate ...\n'
    sleep 30
  fi
}

# CloudFront is optional: brand-new accounts are refused until AWS Support verifies them.
CF_TFVARS=infra/cloudfront.auto.tfvars
cloudfront_setting() {
  if [ "${CLOUDFRONT:-}" = on ] && [ -f "$CF_TFVARS" ]; then
    rm -f "$CF_TFVARS"
    ok "CLOUDFRONT=on: trying to create CloudFront again"
  fi
  [ -f "$CF_TFVARS" ] && warn "CloudFront is switched off ($CF_TFVARS); after AWS verifies the account: CLOUDFRONT=on ./deploy_aws.sh"
  return 0
}

disable_cloudfront() {
  printf '# Written by deploy_aws.sh: AWS refused CloudFront (account not verified yet). Git-ignored.\n# Delete this file (or run CLOUDFRONT=on ./deploy_aws.sh) after AWS Support has verified the account.\nenable_cloudfront = false\n' >"$CF_TFVARS"
  warn "AWS refused CloudFront: \"Your account must be verified before you can add new CloudFront resources\"."
  warn "Continuing WITHOUT CloudFront: the URL is the load balancer (http://; API and dashboard work, no HTTPS, no E7)."
  warn "Fix: AWS console → Support → Create case → Account and billing → ask them to verify the account"
  warn "for CloudFront (paste the error). When they confirm: CLOUDFRONT=on ./deploy_aws.sh"
}

tf_apply() { # tf_apply true|false (loadgen); retries the two known first-run failures of new accounts
  local attempt rc log handled
  log=$(mktemp)
  for attempt in 1 2 3; do
    { $TF apply -input=false -auto-approve -no-color -var "image=$IMAGE" -var user_data_mode=baked \
      -var "enable_loadgen=$1" 2>&1; echo "rc=$?" >>"$log.rc"; } | tee "$log" |
      grep -E '^(Apply complete|Plan:|No changes|Error|│)|(Creation|Destruction|Modifications) complete' | sed 's/^/    | /' || true
    rc=$(tail -1 "$log.rc" | cut -d= -f2)
    [ "$rc" = 0 ] && break
    handled=0
    if grep -q "must be verified before you can add new CloudFront" "$log" && [ ! -f "$CF_TFVARS" ]; then
      disable_cloudfront
      handled=1
    fi
    if grep -q "AWSServiceRoleForAutoScaling\|AWSServiceRoleForElasticLoadBalancing" "$log" && [ "$attempt" -lt 3 ]; then
      warn "the Auto Scaling service role is not usable yet (normal on a new account): retrying in 60 s"
      ensure_service_roles
      sleep 60
      handled=1
    fi
    [ "$handled" = 1 ] || break
    warn "retrying terraform apply (attempt $((attempt + 1)) of 3)"
  done
  rm -f "$log" "$log.rc"
  [ "$rc" = 0 ] || die "terraform apply failed (see the error above). Rerun ./deploy_aws.sh; if the same error repeats, paste it."
  write_env
}

write_env() {
  $TF output -json | jq -r 'to_entries[] | "\(.key | ascii_upcase)=\(.value.value)"' >.env.tf
  set -a
  # shellcheck disable=SC1091
  source .env.tf
  set +a
}

apply_stack() {
  cloudfront_setting
  ensure_service_roles
  step "Create / update the stack with Terraform (first time: ~10-20 min, CloudFront is slow)"
  local lg=false
  if loadgen_running; then lg=true; warn "a lab session is running: keeping the load generator"; fi
  tf_apply "$lg"
  ok "stack applied; outputs in .env.tf"
}

# ---- 9. site + readiness + smoke ----------------------------------------------------------------
publish_site() {
  step "Upload the dashboard (web/) and refresh CloudFront"
  aws s3 sync web/ "s3://$SITE_BUCKET" --delete --only-show-errors
  ok "uploaded to s3://$SITE_BUCKET"
  if [ -n "${CLOUDFRONT_ID:-}" ]; then
    aws cloudfront create-invalidation --distribution-id "$CLOUDFRONT_ID" --paths '/*' >/dev/null
    ok "CloudFront cache refreshed"
  else
    warn "no CloudFront yet: the app serves the dashboard copy baked into the image at http://<alb>/"
  fi
}

wait_healthy() {
  local i healthy=0
  for i in $(seq 1 60); do
    healthy=$(aws elbv2 describe-target-health --target-group-arn "$TARGET_GROUP_ARN" \
      --query "length(TargetHealthDescriptions[?TargetHealth.State=='healthy'])" --output text)
    [ "$healthy" -ge 1 ] && break
    [ $((i % 6)) = 1 ] && printf '    waiting for a healthy app instance ...\n'
    sleep 10
  done
  [ "$healthy" -ge 1 ] || die "no healthy instance after 10 min. infra/README.md → Troubleshooting (targets unhealthy)"
  ok "$healthy healthy app instance(s)"
}

wait_ready() {
  step "Wait until it is live"
  wait_healthy
  [ -n "${CLOUDFRONT_ID:-}" ] || return 0
  printf '    waiting for CloudFront to finish deploying (up to ~15 min the first time) ...\n'
  aws cloudfront wait distribution-deployed --id "$CLOUDFRONT_ID"
  ok "CloudFront deployed"
}

smoke() {
  step "Smoke test (Phase 2 acceptance)"
  if bash infra/smoke.sh | sed 's/^/    /'; then ok "all checks passed"; else warn "some checks failed (output above); a rerun in 2-3 min often fixes CloudFront timing"; fi
}

cmd_up() {
  ensure_tools
  check_account
  pick_instance_type
  printf '\n    This creates in account %s (ap-south-1): ALB, Auto Scaling group (1 x %s, max 4),\n' "$ACCOUNT" "$APP_TYPE"
  printf '    CloudFront, 2 S3 buckets, SSM parameters, budget. While up it uses about USD 3 of credit per day;\n'
  printf '    "./deploy_aws.sh pause" brings that down to about USD 1 per day.\n'
  ask "Continue?" || die "cancelled"
  ensure_settings
  ensure_state_bucket
  check_quota
  resolve_image
  ensure_ami
  apply_stack
  publish_site
  wait_ready
  smoke
  printf '\n%sLIVE URL: %s%s\n' "$G$B" "$CLOUDFRONT_URL" "$N"
  if [ -z "${CLOUDFRONT_ID:-}" ]; then
    printf '%s    (load balancer only: dashboard at %s/ , API at %s/api/v1/whoami)%s\n' "$Y" "$CLOUDFRONT_URL" "$CLOUDFRONT_URL" "$N"
    printf '    CloudFront (HTTPS) is waiting for AWS to verify the account. Open a support case:\n'
    printf '    AWS console → Support → Create case → Account and billing, paste the CloudFront error,\n'
    printf '    then after their answer run:  CLOUDFRONT=on ./deploy_aws.sh\n'
  fi
  cat <<EOF

Next:
  - Write the URL into README.md and docs/runbook.md, paste the smoke output into the PR, tag v0.2.
  - Lab session (experiments):   ./deploy_aws.sh lab      ...   ./deploy_aws.sh lab-down
  - Not using it for a while:    ./deploy_aws.sh pause    (later: ./deploy_aws.sh resume)
  - Overview at any time:        ./deploy_aws.sh status
  - Stop paying after the viva:  ./deploy_aws.sh destroy
  Credit: about USD 3/day while up, USD 1/day paused, USD 0.5/hour in a lab session (of USD 118).
EOF
}

# ---- lab session --------------------------------------------------------------------------------
push_harness() {
  local tmp ver
  tmp=$(mktemp -d)
  tar -C . --exclude='__pycache__' --exclude='.state' --exclude='.pytest_cache' --exclude='.ruff_cache' -cf - harness |
    tar -C "$tmp" -xf -
  ver=$(git rev-parse --short HEAD 2>/dev/null || echo unknown)
  [ -z "$(git status --porcelain -- harness 2>/dev/null)" ] || ver="$ver-dirty"
  echo "$ver" >"$tmp/harness/VERSION"
  tar -C "$tmp" -czf - harness | aws s3 cp - "s3://$RESULTS_BUCKET/harness/harness.tgz" --only-show-errors
  rm -rf "$tmp"
  ok "harness $ver uploaded to s3://$RESULTS_BUCKET/harness/harness.tgz"
}

stack_ready() {
  ensure_tools
  check_account
  [ -f "$TFVARS" ] && [ -f infra/.backend.hcl ] || die "run ./deploy_aws.sh (up) first"
  SUFFIX=$(tfvar suffix | tr -d '"')
  pick_instance_type
  $TF init -input=false -reconfigure -backend-config=.backend.hcl >/dev/null
  resolve_image
}

asg_desired() {
  aws autoscaling describe-auto-scaling-groups --auto-scaling-group-names "$ASG_NAME" \
    --query 'AutoScalingGroups[0].DesiredCapacity' --output text
}

cmd_lab() {
  stack_ready
  step "Start the load generator ($APP_TYPE; the whole lab costs about USD 0.5/hour)"
  tf_apply true
  ok "loadgen $LOADGEN_INSTANCE_ID"
  if [ "$(asg_desired)" = 0 ]; then
    step "The stack was paused: start 1 app server"
    bash infra/reset_asg.sh 1 | sed 's/^/    /'
    wait_healthy
  fi
  step "Upload the harness"
  push_harness
  command -v session-manager-plugin >/dev/null ||
    warn "install the Session Manager plugin to open a shell: https://docs.aws.amazon.com/systems-manager/latest/userguide/session-manager-working-with-install-plugin.html"
  cat <<EOF

Lab session is up. Open a shell on the load generator (wait ~2 min after creation for its setup):
  aws ssm start-session --region ap-south-1 --target $LOADGEN_INSTANCE_ID

Then on the load generator:
  sudo su - ec2-user
  tmux new -s lab
  cd /opt/hsl && aws s3 cp "s3://\$RESULTS_BUCKET/harness/harness.tgz" - | tar xz
  python3.11 harness/asg_mode.py reset
  harness/run_experiment.sh DRY 1 reactive spike C1=10      # first time: Phase 3 acceptance dry run
  harness/exp.sh E1 1                                       # experiments, see harness/README.md

When you are done:  ./deploy_aws.sh lab-down
EOF
}

cmd_lab_down() {
  stack_ready
  step "Reset the Auto Scaling group to 1 instance"
  write_env
  bash infra/reset_asg.sh | sed 's/^/    /'
  step "Remove the load generator"
  tf_apply false
  ok "lab session ended"
  cmd_status_body
}

# ---- pause / resume (save credit between sessions) -----------------------------------------------
cmd_pause() {
  stack_ready
  write_env
  if loadgen_running; then
    step "Remove the load generator"
    tf_apply false
  fi
  step "Stop all app servers (Auto Scaling group to 0)"
  bash infra/reset_asg.sh 0 | sed 's/^/    /'
  ok "paused. The page still loads from CloudFront, the API answers 503 until you resume."
  warn "the load balancer still costs about USD 1/day; for breaks of a week or more use destroy"
}

cmd_resume() {
  stack_ready
  write_env
  step "Start 1 app server"
  bash infra/reset_asg.sh 1 | sed 's/^/    /'
  wait_healthy
  printf '\n%sLIVE URL: %s%s\n' "$G$B" "$CLOUDFRONT_URL" "$N"
}

# ---- status / destroy ---------------------------------------------------------------------------
cmd_status_body() {
  step "Running project instances"
  aws ec2 describe-instances --filters Name=tag:project,Values=hotstar-scale-lab \
    Name=instance-state-name,Values=pending,running \
    --query 'Reservations[].Instances[].[InstanceId,InstanceType,Tags[?Key==`Name`]|[0].Value,LaunchTime]' --output table
  printf '    lab lock: %s\n' "$(aws s3 cp "s3://$RESULTS_BUCKET/lab.lock" - 2>/dev/null || echo free)"
  printf '    app servers (desired): %s of max %s\n' "$(asg_desired 2>/dev/null || echo '?')" "${ASG_MAX:-4}"
  printf '    live URL: %s\n' "${CLOUDFRONT_URL:-?}"
}

cmd_status() {
  ensure_tools
  check_account
  [ -f infra/.backend.hcl ] || die "nothing deployed yet: run ./deploy_aws.sh"
  $TF init -input=false -reconfigure -backend-config=.backend.hcl >/dev/null
  write_env
  cmd_status_body
}

cmd_destroy() {
  ensure_tools
  check_account
  [ -f infra/.backend.hcl ] || die "nothing deployed yet"
  SUFFIX=$(tfvar suffix | tr -d '"')
  $TF init -input=false -reconfigure -backend-config=.backend.hcl >/dev/null
  write_env
  printf '\n%sThis deletes the whole stack, the results bucket (pull results first: make results-pull)\n' "$R"
  printf 'and every hsl AMI + snapshot in account %s. The state bucket is kept.%s\n' "$ACCOUNT" "$N"
  local a
  read -r -p "    Type 'destroy' to continue: " a
  [ "$a" = destroy ] || die "cancelled"
  [ -f infra/ami.auto.tfvars ] || echo 'ami_id = "ami-00000000000000000"' >infra/ami.auto.tfvars
  local img="ghcr.io/x/streamlite:0000000" v=(-input=false -auto-approve -var user_data_mode=baked -var enable_loadgen=false)
  step "Allow deleting the results bucket, then destroy"
  $TF apply "${v[@]}" -var "image=$img" -var force_destroy_results=true -target=aws_s3_bucket.results >/dev/null
  $TF destroy "${v[@]}" -var "image=$img" -var force_destroy_results=true | grep -E '^(Destroy complete|Error)' | sed 's/^/    | /'
  step "Deregister AMIs and delete their snapshots"
  local ami snaps s
  for ami in $(aws ec2 describe-images --owners self --filters Name=tag:project,Values=hotstar-scale-lab \
    --query 'Images[].ImageId' --output text); do
    snaps=$(aws ec2 describe-images --image-ids "$ami" --query 'Images[].BlockDeviceMappings[].Ebs.SnapshotId' --output text)
    aws ec2 deregister-image --image-id "$ami" && ok "deregistered $ami"
    for s in $snaps; do aws ec2 delete-snapshot --snapshot-id "$s" && ok "deleted $s"; done
  done
  rm -f .env.tf infra/ami.auto.tfvars infra/instance.auto.tfvars "$CF_TFVARS"
  printf '\n    Done. The state bucket s3://hsl-tfstate-%s is kept (a few cents). To delete it as well:\n' "$SUFFIX"
  printf '    aws s3 rm s3://hsl-tfstate-%s --recursive && aws s3api delete-bucket --bucket hsl-tfstate-%s\n' "$SUFFIX" "$SUFFIX"
  printf '    (it is versioned: empty the old versions in the console first if delete-bucket refuses)\n'
}

case "${1:-up}" in
  up) cmd_up ;;
  lab) cmd_lab ;;
  lab-down) cmd_lab_down ;;
  pause) cmd_pause ;;
  resume) cmd_resume ;;
  status) cmd_status ;;
  destroy) cmd_destroy ;;
  -h | --help | help) sed -n '2,26p' "$0" | sed 's/^# \{0,1\}//' ;;
  *) die "unknown command '$1' (up, lab, lab-down, pause, resume, status, destroy, help)" ;;
esac

#!/usr/bin/env bash
# First deploy to AWS in one command (infra/README.md "First deploy"): checks, Terraform init, Packer AMI,
# apply, outputs, site publish, smoke test, then prints the live URL and the v0.2 tag commands.
#
# usage: scripts/deploy_aws.sh [--yes] [--skip-ami] [--image-tag SHA7] [--tag]
#   --yes         do not ask before spending money (ami + tf-apply)
#   --skip-ami    reuse infra/ami.auto.tfvars from an earlier run
#   --image-tag   GHCR image tag to bake (default: newest commit that changed app/)
#   --tag         after a green smoke test, write the URL into README.md, commit it and tag v0.2 (no push)
# Run from the repo root, with AWS_PROFILE set. Costs about $3-4 per day while the stack runs.
set -euo pipefail
cd "$(dirname "$0")/.."

YES=0 SKIP_AMI=0 TAG=0 IMAGE_TAG=""
while [ $# -gt 0 ]; do
  case $1 in
    --yes) YES=1 ;;
    --skip-ami) SKIP_AMI=1 ;;
    --tag) TAG=1 ;;
    --image-tag) IMAGE_TAG=${2:?--image-tag needs a value}; shift ;;
    -h | --help) sed -n '2,11p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown option $1"; exit 2 ;;
  esac
  shift
done

say() { printf '\n\033[1m== %s\033[0m\n' "$*"; }
die() { printf '\033[31merror:\033[0m %s\n' "$*" >&2; exit 1; }
MAKE_ARGS=()
[ -n "$IMAGE_TAG" ] && MAKE_ARGS+=("IMAGE_TAG=$IMAGE_TAG")

say "1/8 preflight"
for t in aws terraform packer jq make docker; do command -v "$t" >/dev/null || die "$t is not installed (make doctor)"; done
[ -n "${AWS_PROFILE:-}${AWS_ACCESS_KEY_ID:-}" ] || die "set AWS_PROFILE (e.g. export AWS_PROFILE=hsl)"
aws sts get-caller-identity --query Arn --output text || die "AWS credentials do not work"
[ -f infra/.backend.hcl ] || die "missing infra/.backend.hcl (copy infra/backend.hcl.example and set the state bucket)"
[ -f infra/terraform.tfvars ] || die "missing infra/terraform.tfvars (copy infra/terraform.tfvars.example)"
export AWS_DEFAULT_REGION=${AWS_DEFAULT_REGION:-ap-south-1}
echo "region: $AWS_DEFAULT_REGION"

say "2/8 offline checks (terraform validate + tests)"
make tf-validate tf-test

say "3/8 GHCR image is public and pullable"
make image-check "${MAKE_ARGS[@]}" || die "image not pullable: make the streamlite package public, or pass --image-tag <sha7>"

if [ "$YES" = 0 ]; then
  read -r -p "Next steps create billable AWS resources (about \$3-4/day). Continue? [y/N] " a
  [ "$a" = y ] || [ "$a" = Y ] || die "aborted"
fi

say "4/8 terraform init"
make tf-init

if [ "$SKIP_AMI" = 1 ]; then
  say "5/8 AMI (skipped)"
  [ -f infra/ami.auto.tfvars ] || die "--skip-ami but infra/ami.auto.tfvars does not exist"
else
  say "5/8 Packer baked AMI (about 6 min)"
  make ami "${MAKE_ARGS[@]}"
fi

say "6/8 terraform apply (CloudFront takes 5-15 min the first time)"
make tf-apply
make env

say "7/8 publish the dashboard"
make publish-site

say "8/8 smoke test"
make smoke | tee /tmp/hsl-smoke.txt

URL=$(terraform -chdir=infra output -raw cloudfront_url)
say "done"
echo "Live URL: $URL"
echo "Paste the smoke output (/tmp/hsl-smoke.txt) into the PR."

if [ "$TAG" = 1 ]; then
  say "README + tag v0.2"
  sed -i "s|^- Live URL: .*|- Live URL: $URL (tag \`v0.2\`)|" README.md
  git add README.md
  git commit -m "docs: live URL (v0.2)" || true
  git tag v0.2
  echo "tagged v0.2. Push with: git push origin main v0.2"
else
  echo "Then: put the URL in README.md, commit, and run: git tag v0.2 && git push origin main v0.2"
fi
echo "Teardown after the viva: make destroy-all. Between sessions the demo stack keeps costing money."

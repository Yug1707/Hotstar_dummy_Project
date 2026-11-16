#!/usr/bin/env bash
# Kept for the old path: the deploy now lives in ../deploy_aws.sh (AWS Free plan: free-tier instance type, fleet
# max 4, optional CloudFront, retries for first-run IAM races, pause/resume). This wrapper maps the old flags.
#
# usage: scripts/deploy_aws.sh [--yes] [--image-tag SHA7] [up|lab|lab-down|pause|resume|status|destroy]
#   --yes         do not ask before spending money (same as YES=1)
#   --image-tag   GHCR image tag to bake (same as IMAGE_TAG=<sha7>)
#   --skip-ami    accepted and ignored: ../deploy_aws.sh reuses an AMI that already exists for the tag
# The old --tag (commit + tag v0.2) is gone: tag by hand after a green smoke test.
set -euo pipefail
args=()
while [ $# -gt 0 ]; do
  case $1 in
    --yes) export YES=1 ;;
    --skip-ami) ;;
    --image-tag) export IMAGE_TAG=${2:?--image-tag needs a value}; shift ;;
    --tag) echo "--tag was removed: after a green smoke test run 'git tag v0.2 && git push origin v0.2'" >&2; exit 2 ;;
    -h | --help) sed -n '2,9p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) args+=("$1") ;;
  esac
  shift
done
exec "$(dirname "$0")/../deploy_aws.sh" ${args[@]+"${args[@]}"}

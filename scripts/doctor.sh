#!/usr/bin/env bash
# Checks every tool the project needs, with a minimum version. Exit 1 if anything is missing.
set -uo pipefail

fail=0
ok()   { printf '  \033[32mok\033[0m   %-24s %s\n' "$1" "$2"; }
bad()  { printf '  \033[31mFAIL\033[0m %-24s %s\n' "$1" "$2"; fail=1; }
warn() { printf '  \033[33mwarn\033[0m %-24s %s\n' "$1" "$2"; }

# version_ge 1.10.2 1.10  -> true
version_ge() { [ "$(printf '%s\n%s\n' "$2" "$1" | sort -V | head -n1)" = "$2" ]; }

check() { # name min_version command-that-prints-version
  local name=$1 min=$2; shift 2
  if ! command -v "$name" >/dev/null 2>&1; then bad "$name" "not installed (need >= $min)"; return; fi
  local v
  v=$("$@" 2>/dev/null | grep -Eo '[0-9]+\.[0-9]+(\.[0-9]+)?' | head -n1)
  if [ -z "$v" ]; then warn "$name" "installed, version unknown"; return; fi
  if version_ge "$v" "$min"; then ok "$name" "$v"; else bad "$name" "$v (need >= $min)"; fi
}

echo "Tools"
if command -v python3.12 >/dev/null 2>&1 || command -v uv >/dev/null 2>&1; then
  ok "python 3.12" "$(command -v python3.12 || echo 'via uv')"
else
  check python3 3.12 python3 --version
fi
check docker    24.0  docker version --format '{{.Server.Version}}'
check terraform 1.10  terraform version
check packer    1.10  packer version
check k6        1.0   k6 version
check aws       2.0   aws --version
check session-manager-plugin 1.0 session-manager-plugin --version
check git       2.30  git --version
check jq        1.6   jq --version
check make      3.81  make --version

echo "AWS"
if command -v aws >/dev/null 2>&1; then
  if acct=$(aws sts get-caller-identity --query Account --output text 2>/dev/null); then
    ok "credentials" "account $acct (profile ${AWS_PROFILE:-default})"
  else
    bad "credentials" "aws sts get-caller-identity failed (aws configure sso / AWS_PROFILE=hsl)"
  fi
  region=$(aws configure get region 2>/dev/null || true)
  region=${AWS_REGION:-${region:-}}
  if [ "$region" = "ap-south-1" ]; then ok "region" "$region"; else bad "region" "'${region:-unset}' (need ap-south-1)"; fi
fi

echo
if [ $fail -eq 0 ]; then echo "doctor: all good"; else echo "doctor: fix the FAIL lines above"; fi
exit $fail

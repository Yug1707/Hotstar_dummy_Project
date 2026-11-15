#!/bin/bash
# Run one entry of experiments.yaml. Prints the resolved command, then runs it.
# usage: exp.sh EXP RUN [N|VARIANT] [-- extra run_experiment.sh options]
#   exp.sh E1 1          exp.sh E2a 2 3          exp.sh E6 1 auto_shed          exp.sh E5 1 naive
#   exp.sh E3 1 -- --no-cooldown
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
PY=${PYTHON:-python3}

args=()
extra=()
while [ $# -gt 0 ]; do
  if [ "$1" = -- ]; then shift; extra=("$@"); break; fi
  args+=("$1")
  shift
done
[ ${#args[@]} -ge 2 ] || { sed -n '2,5p' "$0" | sed 's/^# //'; exit 2; }

line=$("$PY" "$HERE/exp_config.py" cmd "${args[@]}")
read -r script rest <<<"$line"
echo "+ $script ${extra[*]} $rest" >&2
eval "set -- $rest"
exec "$HERE/$script" "${extra[@]}" "$@"

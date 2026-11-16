#!/usr/bin/env python3
"""Draft the five-line summary.md that goes with every `results(EX): ...` commit (plan section 7.4).

usage: new_summary.py results/E3          drafts results/E3/summary.md from the run folders' summary.json files
       new_summary.py results/E3 --print  print instead of writing

Lines: what, numbers, surprise, validity, next. The tool fills in what the data says (what, numbers, validity);
the surprise and next lines are left for a human, marked TODO, because only a person saw what was surprising.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

try:
    from analysis import common
except ImportError:  # run as a script
    import common  # type: ignore[no-redef]


def draft(exp_dir: Path) -> str:
    runs = sorted(exp_dir.glob("run*"))
    metas = [(r, common.read_json(r / "meta.json")) for r in runs if (r / "meta.json").exists()]
    sums = [common.read_json(r / "summary.json") for r in runs if (r / "summary.json").exists()]
    if not metas:
        raise SystemExit(f"{exp_dir}: no run folders with meta.json")
    m0 = metas[0][1]
    what = (
        f"{exp_dir.name}: {m0.get('mode')} on the {m0.get('profile')} profile, {len(metas)} run(s), c1 {m0.get('c1')}, "
    )
    what += f"work_scale {m0.get('work_scale')}, {m0.get('instance_type')}, harness {m0.get('harness_sha')}."
    if sums and "instances" in sums[0]:
        t = common.median([s.get("median_launch_to_healthy_s") for s in sums])
        numbers = f"median launch to healthy {t} s over {len(sums)} run(s)."
    elif sums:
        p95 = [s["critical"]["p95_ms"] for s in sums if s.get("critical")]
        viol = [s["slo_violation_s"] for s in sums if s.get("slo_violation_s") is not None]
        numbers = (
            f"critical p95 median {common.median(p95)} ms (range {min(p95)}-{max(p95)}), "
            f"SLO-violation s median {common.median(viol)} (range {min(viol)}-{max(viol)})."
        )
        caps = [s["capacity_rps"] for s in sums if s.get("capacity_rps") is not None]
        if caps:
            numbers += f" Capacity at SLO median {common.median(caps)} rps."
    else:
        numbers = "TODO: run parse_k6.py first."
    bad = [m["run"] for _, m in metas if m.get("valid") is False]
    validity = f"{len(metas) - len(bad)} of {len(metas)} valid" + (
        f"; invalid: run {', '.join(map(str, bad))} (kept, logged in runbook)" if bad else ""
    )
    return "\n".join(
        [
            f"1. **What:** {what}",
            f"2. **Numbers:** {numbers}",
            "3. **Surprise:** TODO",
            f"4. **Validity:** {validity}.",
            "5. **Next:** TODO",
            "",
        ]
    )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("exp_dir", type=Path)
    ap.add_argument("--print", action="store_true", dest="to_stdout")
    a = ap.parse_args(argv)
    text = draft(a.exp_dir)
    if a.to_stdout:
        print(text)
    else:
        (a.exp_dir / "summary.md").write_text(text)
        print(f"wrote {a.exp_dir / 'summary.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

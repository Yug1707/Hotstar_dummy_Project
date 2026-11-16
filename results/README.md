# results/

One folder per experiment, one sub-folder per run. Raw k6 CSVs stay in S3 (`raw/` is git-ignored); everything
small is committed. Folder names are the ones `harness/exp.sh` writes:

| Experiment | Folders |
|---|---|
| E1 | `E1/run1..3` |
| E2a, E2b | `E2a_N1..N5/run1..3`, `E2b_N1..N5/run1` |
| E3 | `E3/run1..3` |
| E4 | `E4a/run1`, `E4b/run1`, `E4c/run1..3` (optional `E4d/run1`) |
| E5 | `E5_naive/run1..3`, `E5_baked/run1..3` |
| E6 | `E6_none`, `E6_ssm_level1`, `E6_auto_shed`, each `run1..3` |
| E7 | `E7_alb`, `E7_cloudfront`, each `run1..3` |
| E8 | `E8/summary.json`, `E8/cost.md` (from `analysis/cost_model.py`, not a lab run) |
| figures | `figures/F1..F7.{png,svg}` (from `make analyze`) |

`FAKE_*` folders (from `analysis/fake_campaign.py`) are synthetic, git-ignored and never reported.

## Running Phase 4

The order is E1, E2, E5, E3, E4, E6, E7 (plan section 7.2). All commands run on the load generator inside `tmux`; see
[`harness/README.md`](../harness/README.md) for the cheat sheet and [`docs/runbook.md`](../docs/runbook.md) for the session
checklist. The gates between experiments:

1. **Before E1:** the GIL check from plan section 4.6. After E1: the median knee goes into `harness/experiments.yaml`
   as `global.c1` (it must land in 80 to 130 rps; otherwise change `WORK_SCALE`, rebuild the AMI and redo E1).
2. **Same AMI, instance type, `WORK_SCALE` and harness SHA** inside one comparison; the runner records them in
   `meta.json`. Do not compare runs that differ.
3. **Never delete an invalid run.** It stays, `meta.json` says `valid: false`, and it gets a line in the runbook run log.
4. **Report the median and the min to max of three runs**, never the best one.

## Per experiment, after the runs

```bash
make results-pull RAW=1
.venv/bin/python analysis/parse_k6.py results/E3/run*          # summary.json, timeline.json
.venv/bin/python analysis/new_summary.py results/E3            # drafts summary.md; fill in "surprise" and "next"
git add results/E3 && git commit -m "results(E3): reactive scaling on the spike profile"
```

`summary.md` has exactly five lines: what, numbers, surprise, validity, next. `new_summary.py` fills what, numbers
and validity from the data; a person writes the other two.

Phase 4 is done when: every run folder is complete, three runs exist where required, `c1` and the knee are in
`experiments.yaml`, raw data is synced to S3, each experiment has its `summary.json` files and a `summary.md`
committed, and `make analyze` produces F1 to F7 from them.

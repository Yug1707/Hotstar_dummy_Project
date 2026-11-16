# Runbook

## AWS account facts
| Item | Value |
|---|---|
| Region | ap-south-1 |
| Account id | _tbd_ |
| vCPU quota (Running On-Demand Standard) | requested: 32 · granted: _tbd_ · request id: _tbd_ |
| Budget | $25/month, alerts 50/80/100 % — created: _tbd_ |
| Terraform state bucket | `hsl-tfstate-<suffix>` — _tbd_ |

## Local development
```bash
make venv && make test && make dev
make image && make run-image
```

## Deploy / teardown
See [`infra/README.md`](../infra/README.md): one-time setup, first deploy, lab session, teardown, Packer fallback.

| Item | Value |
|---|---|
| CloudFront URL | _tbd (after first deploy)_ |
| Current AMI / image tag | _tbd_ |
| `work_scale` (T2.7) | _tbd_ |

## Lab session checklist
See docs/IMPLEMENTATION_PLAN_DETAILED.md §15.3. Per session: `make lab-up && make push-harness`, run the experiments on
the loadgen (`harness/README.md`), then `make destroy-lab` and confirm in the console that the ASG is at 1 and the
loadgen is gone.

## From a run to the dashboard
```bash
make results-pull                    # laptop: summaries, meta, CSVs (RAW=1 also pulls raw/k6.csv.gz)
.venv/bin/python analysis/parse_k6.py --all        # raw -> summary.json + timeline.json (needs RAW=1)
git add results/E*/run*/{meta,summary,profile}.json results/E*/run*/timeline.json results/E*/run*/summary.md
make analyze                         # figures, results/E8, web/data/results.json
make publish-site                    # s3 sync web/ + CloudFront invalidation
```
Commit per experiment as `results(EX): <what>` with a five-line `summary.md` (what, numbers, surprise, validity, next);
see [`results/README.md`](../results/README.md).

## Filling in the cost inputs
`config/prices.yaml` is empty on purpose. After the first deploy, build one estimate in the AWS Pricing Calculator
(region ap-south-1), copy the on-demand price of `c6i.large`, the ALB prices and the Spot discount observed in the
Spot price history, and set `retrieved` and `source`. Until then `make analyze` and the dashboard show instance counts
and say "price missing".

## Troubleshooting the analysis
| Symptom | Fix |
|---|---|
| `parse_k6.py` prints "raw/k6.csv.gz not here" | `make results-pull RAW=1` |
| a figure is skipped ("no data yet") | the experiment behind it has no `summary.json` yet (F1: E2a/E2b, F2/F3: E3/E4, F4: E5, F5: E6, F6: E7) |
| dashboard shows "results pending" | `web/data/results.json` has `pending: true`: run `make analyze` after parsing real runs |
| mixed runs in one figure | the analysis reads every valid run of an experiment: keep invalid ones out by leaving `valid: false` in `meta.json` and log them below |

## Run log
`date UTC | EXP runN | valid/invalid | ami sha work_scale c1 | note`

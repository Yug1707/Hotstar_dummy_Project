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
_Phase 2 (A)._

## Lab session checklist
See docs/IMPLEMENTATION_PLAN_DETAILED.md §15.3.

## Run log
`date UTC | EXP runN | valid/invalid | ami sha work_scale c1 | note`

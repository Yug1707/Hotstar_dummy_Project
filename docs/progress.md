# Progress log

One entry per day, written by the scribe of the day (docs/TEAM_PLAN_3_PEOPLE.md §5).
Format: done (PR numbers), numbers learned, blockers, next.

## Week of 14 Nov 2026

### Day 1 (14 Nov) — setup + application
- Done: repo skeleton, `make doctor`, backlog + issue script, sources log template, plans committed;
  StreamLite app (all endpoints, arrival-based stats, degradation, auto-shed, rate limit), test suite,
  Dockerfile, CI workflows, calibration script.
- Numbers: local calibration only (laptop), not reportable. Real calibration happens on c6i.large in T2.7.
- Blockers: vCPU quota request (A) — record the request id and the granted value in `runbook.md`.
- Next: Terraform core (A), k6 lib + profiles (C), GHCR package made public after the first image push (repo owner).

### Day 2 (15 Nov) — Phase 2 infrastructure code
- Done: all of Phase 2 in the single folder `infra/`: Terraform (network, IAM, SSM, ALB with `/internal/*` block,
  ASG + launch template, S3 site + CloudFront, loadgen + results bucket, budget, outputs), Packer baked AMI,
  baked/naive/loadgen boot scripts, smoke test, ASG reset, `make` targets, CI jobs for terraform/packer.
- Verified offline: `terraform validate`, 6 `terraform test` runs against mock providers, `packer validate`, shellcheck.
- Not done (needs AWS): `make ami`, first `tf-apply`, smoke test, live URL, tag `v0.2`, calibration (T2.7).
- Blockers: vCPU quota + state bucket (A), GHCR package public (repo owner).

### Day 3 (16 Nov) — analysis, dashboard, docs (everything that needs no AWS)
- Done: Phase 5 analysis (`analysis/`: k6 parser with per-second aggregates and `summary.json`, figures F1 to F6, cost model
  and F7, `results.json` export, synthetic run and campaign generators, `new_summary.py`; 18 tests); Phase 6 dashboard
  (`web/`: case facts, architecture, results charts with a pending state, live panel, burst test, cost calculator);
  Phase 7 docs (`docs/architecture.md`, report outline and sections, viva slides, runbook); CI job for the web checks.
- Verified: analysis tests and the full chain on a synthetic campaign; dashboard in a browser (desktop and 375 px, no console
  errors, no horizontal scroll), live panel and burst test against a local StreamLite.
- Not done (needs the AWS stack): first deploy, calibration (T2.7), the harness dry run, all of Phase 4 (E1 to E7), real figures,
  real prices in `config/prices.yaml`, Lighthouse and phone checks on the live URL, report results sections, viva rehearsal.
- Numbers learned: none yet. Every figure in the repository so far is from synthetic data and says so.
- Blockers: vCPU quota and state bucket (A), GHCR package public (repo owner), prices to fill from the AWS Pricing Calculator.
- Next: `make lab-up`, harness dry run at C1=10, E1 to set `c1`, then E2 onwards; `make analyze` and `make publish-site` after each.

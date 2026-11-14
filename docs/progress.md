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

# Hotstar Scale Lab

IT457 Cloud Computing case study. **Hotstar Scale Lab** is a scaled-down, honest replica of the problem
Disney+ Hotstar solved for IPL / World Cup streaming: a sudden wall of traffic (1M+ new users per minute,
about 90 s to react) hitting a platform whose servers take longer than that to boot.

We deploy a small web app (**StreamLite**, FastAPI) behind an AWS Application Load Balancer with an Auto
Scaling Group, serve it on a public HTTPS URL through CloudFront, then use k6 to replay a match-day traffic
spike under different scaling strategies and measure latency, errors, scaling behaviour and cost.

- Live URL: _after the first deploy (`make tf-apply`, see [`infra/README.md`](infra/README.md)), tag `v0.2`_
- Plans: [`docs/IMPLEMENTATION_PLAN_DETAILED.md`](docs/IMPLEMENTATION_PLAN_DETAILED.md) ·
  [`docs/TEAM_PLAN_3_PEOPLE.md`](docs/TEAM_PLAN_3_PEOPLE.md) · [original plan (PDF)](docs/original-plan.pdf)
- Progress log: [`docs/progress.md`](docs/progress.md)

## Status

| Phase | What | Status |
|---|---|---|
| 0 | Repo, tooling check, sources log, backlog | done |
| 1 | StreamLite app, tests, container, CI | done (`v0.1`) |
| 2 | Terraform + Packer + CloudFront live URL | code done, validated offline; first deploy pending (AWS) |
| 3 | k6 harness, ASG mode switcher, proactive scaler | – |
| 4–7 | Experiments, analysis, dashboard, report | – |

## Quick start (local)

```bash
make doctor          # checks python, docker, terraform, packer, k6, aws, ...
make venv            # .venv with app + dev dependencies (uses uv if present)
make test            # pytest
make dev             # http://localhost:8000  (reload on change)
make image           # docker build -f app/Dockerfile -t streamlite:<sha> .
make run-image       # run the container on :8000
make tf-test         # Terraform tests against mock AWS (no account needed)
```

Deploying to AWS: [`infra/README.md`](infra/README.md).

Try it:

```bash
curl -s localhost:8000/api/v1/whoami | jq
curl -s -XPOST localhost:8000/api/v1/playback/start -H 'content-type: application/json' \
     -d '{"user_id": 1, "match_id": "m1"}' | jq
curl -s localhost:8000/internal/stats | jq
```

## StreamLite endpoints

| Endpoint | Class | CPU cost (target) | Notes |
|---|---|---|---|
| `GET /healthz` | infra | ~0 | ALB health check |
| `GET /api/v1/whoami` | infra | ~0 | instance id, AZ, uptime, in-flight, degrade level |
| `POST /api/v1/playback/start` | critical | 15 ms | fake manifest + token |
| `POST /api/v1/heartbeat` | critical | 2 ms | updates active-viewer set (TTL 30 s) |
| `GET /api/v1/match/state` | public, cacheable | 1 ms | `Cache-Control: public, max-age=5` |
| `GET /api/v1/recommendations` | non-critical | 40 ms | degradable / shed under load |
| `GET /internal/stats` | internal | ~0 | rps (arrivals), in-flight, p95, shed count — blocked at the ALB |

Configuration is environment-only. See `app/config.py` and §1.2 of the detailed plan.

## Repository layout

```
app/        StreamLite (FastAPI) + tests + Dockerfile
web/        static dashboard (Phase 6)
scripts/    doctor.sh, calibrate.py, create_issues.sh
make/       per-owner Makefile fragments (infra.mk, app.mk, lab.mk, analysis.mk)
infra/      Phase 2 in one folder: Terraform, Packer, boot scripts, smoke test
loadtest/   k6 scripts (Phase 3)
automation/ asg_mode, monitor, proactive scaler, runner (Phase 3)
analysis/   parser, plots, cost model (Phase 5)
config/     experiments.yaml, model.yaml, prices.yaml
results/    E1..E8 (raw/ is git-ignored; summary.json + png committed)
docs/       plans, sources, runbook, progress, report
```

## Team

| Role | Owns | Name |
|---|---|---|
| A — Infra & Platform | `infra/`, cost model, case study | _tbd_ |
| B — App, Dashboard, Analysis | `app/`, `web/`, plots | _tbd_ |
| C — Load Lab & Experiments | `loadtest/`, `automation/`, results | _tbd_ |

## Licence

MIT — see [LICENSE](LICENSE).

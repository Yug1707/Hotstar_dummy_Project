# Architecture

How the pieces of Hotstar Scale Lab fit together. For the build steps see [`infra/README.md`](../infra/README.md);
for the experiments see [`harness/README.md`](../harness/README.md); for the reasoning behind each choice see
[`IMPLEMENTATION_PLAN_DETAILED.md`](IMPLEMENTATION_PLAN_DETAILED.md).

## 1. The serving path

```
viewer ──HTTPS──► CloudFront (PriceClass_200, includes India)
                    ├─ default (*)        → S3 site bucket (private, origin access control)   cached
                    ├─ /api/v1/match/*    → ALB                                               cached, max-age=5 from the origin
                    └─ /api/*             → ALB                                               not cached
ALB :80 ─ rule 1: /internal/* → fixed 404 ─► target group :8000 (/healthz every 5 s) ─► ASG, c6i.large × 1..6, two AZs
```

- **CloudFront** terminates HTTPS on the default `*.cloudfront.net` name and splits traffic by path. The order of
  behaviours matters: `/api/v1/match/*` is matched before `/api/*`.
- **ALB** balances per request, round robin. A listener rule answers `/internal/*` with 404 so the stats endpoint is never
  reachable through the public path (plan fix F2).
- **ASG** runs StreamLite from a baked AMI. It has **no scaling policy of its own**: capacity is set by
  [`harness/asg_mode.py`](../harness/asg_mode.py), so every experiment starts from a known state.
- **Static dashboard** (`web/`) lives in the S3 bucket and is published with `make publish-site` (sync plus an
  invalidation). It needs no rebuild of the image when results change.

## 2. StreamLite, the application

One FastAPI process family per instance, with a deliberately predictable CPU cost per request class:

| Class | Endpoint | CPU target | Behaviour under pressure |
|---|---|---|---|
| infra | `/healthz`, `/api/v1/whoami` | ~0 | always answered |
| critical | `POST /api/v1/playback/start` (15 ms), `POST /api/v1/heartbeat` (2 ms) | fixed | never shed |
| public, cacheable | `GET /api/v1/match/state` (1 ms) | fixed | cached by CloudFront for 5 s |
| non-critical | `GET /api/v1/recommendations` (40 ms) | fixed | degraded by SSM level 1, shed by auto-shed |
| internal | `GET /internal/stats` | ~0 | private IP only |

Statistics count **arrivals** in the middleware, before the thread-pool queue (fix F5): when an instance saturates,
completions flatten at its capacity but arrivals keep reporting the real demand, which is what the scaler needs.
Per-process snapshots in `/dev/shm` are aggregated by `/internal/stats`, so running two workers is a one-line change.

Degradation has two independent switches (experiment E6):

1. `degrade_level` in SSM Parameter Store, polled by every instance (manual, operator-driven);
2. `AUTO_SHED`, where an instance sheds non-critical requests by itself when its in-flight count crosses a threshold.

A load-test token (SSM SecureString) bypasses the per-client rate limit so the load generator is never throttled; the public
limit stays on for everyone else.

## 3. The scaling modes

| Mode | Where it lives | What it does |
|---|---|---|
| `static N` | `asg_mode.py` | fixed fleet, for capacity (E1, E2) and for E6/E7 |
| `reactive` | `asg_mode.py` | a target-tracking policy on average CPU at 50 %, as a default ASG user would configure it (E3) |
| `proactive` | `asg_mode.py` + `proactive_scaler.py` | pre-warm floor, then a ladder on the measured **arrival rate**: scale out at once, scale in one step per five minutes (E4) |
| `scheduled AT N` | `asg_mode.py` | the reactive policy plus a scheduled action that raises capacity at the ramp: the AWS-native pre-warm (E4d) |
| `reset` | `asg_mode.py` | no policies, no scheduled actions, 1 / 6 / 1; always run on exit by `run_experiment.sh` |

The hard ceiling is six instances, enforced in Terraform, in `asg_mode.py` and in the scaler.

## 4. The measurement path

```
k6 on the load generator (open model, ramping-arrival-rate) ──► ALB or CloudFront
        │                                                              │
        └─ raw/k6.csv.gz  (stays in S3)             monitor_asg.py: asg_timeline.csv, instances.csv, stats.csv
                                                    collect_cw.py : cw/*.csv (14 CloudWatch series)
                                                    sample_cpu.py : loadgen_cpu.csv (validity check, < 70 %)
                              meta.json, profile.json, k6_summary.json
```

Every run lands in `results/<EXP>/run<N>/` and is synced to the results bucket by the runner's exit trap. A lock object
(`lab.lock`, taken with a conditional write) keeps two people from running experiments at once. The load model is **open**:
arrivals do not wait for responses, so overload shows up as latency and errors instead of being hidden by coordinated omission.

## 5. From raw runs to the dashboard

```
results/<EXP>/run<N>/raw/k6.csv.gz ──► analysis/parse_k6.py ──► summary.json, timeline.json (committed), aggregates.csv.gz (local)
summary.json files ──► analysis/make_plots.py ──► results/figures/F1..F6.{png,svg}
                  └──► analysis/cost_model.py ──► results/E8/summary.json, cost.md, F7
                  └──► analysis/export_results.py ──► web/data/results.json, web/img/F*.png
```

`make analyze` runs the last three steps from the committed summaries in well under a minute; `make analyze-full` re-parses
the raw CSVs first. `analysis/fake_campaign.py` writes a complete synthetic E1 to E7 campaign (`results/FAKE_*`, never
committed) so the whole chain, including the dashboard, can be developed and tested before any AWS run exists.

## 6. What maps to what

| Hotstar fact | What we replicate | What we do not claim |
|---|---|---|
| 1M+ new users per minute, ~90 s to react | k6 ramps to 3 × C1 in 90 s | real user behaviour or real scale |
| standard Auto Scaling failed; pre-warm plus a custom scaler on request count | reactive policy vs our proactive scaler (floor plus ladder) | Hotstar's exact algorithm (not public) |
| fully baked AMIs | Packer AMI vs install-at-boot (E5) | their instance mix or Spot share (unverified) |
| graceful degradation of non-critical features | SSM degrade flag and auto-shed (E6) | their feature list |
| 2023: cacheable and personalised APIs on separate CDN domains | `/api/v1/match/*` cached by CloudFront vs uncached personal APIs (E7) | multi-CDN, Envoy, EKS (explained in the report, not rebuilt) |

## 7. Security and cost guardrails

- No SSH anywhere: instances are reached through SSM Session Manager and Run Command.
- IMDSv2 only; the app role can read `/streamlite/*`; the load generator role can drive the ASG and write the results bucket.
- The load-test token is generated by Terraform into an SSM SecureString and never appears in Git, in the launch template or in `web/` (CI greps for it).
- Budget alerts at 50, 80 and 100 %; ASG maximum six; load generator behind a count toggle; no NAT gateways; `make destroy-lab` ends every session.

# Hotstar Scale Lab — Detailed Implementation Plan (v2)

> Expands `Hotstar_Scale_Lab_Implementation_Plan.pdf` (13 Nov 2026) into task-level detail:
> every file, interface, command, data format, schedule slot and acceptance check.
> The PDF is still the source of truth for **scope and hypotheses (H1–H6)**. This document is the
> source of truth for **how to build it**. Where this document changes something in the PDF, §0 says what changed and why.

---

## Table of contents

0. [Changes and fixes to the original plan](#0-changes-and-fixes-to-the-original-plan)
1. [Global conventions](#1-global-conventions)
2. [Task backlog, dependencies and day-by-day schedule](#2-task-backlog-dependencies-and-day-by-day-schedule)
3. [Phase 0 — Setup and guardrails](#3-phase-0--setup-and-guardrails)
4. [Phase 1 — StreamLite application](#4-phase-1--streamlite-application)
5. [Phase 2 — Infrastructure and the live URL](#5-phase-2--infrastructure-and-the-live-url)
6. [Phase 3 — Load-test harness and automation](#6-phase-3--load-test-harness-and-automation)
7. [Phase 4 — Experiment run-book](#7-phase-4--experiment-run-book)
8. [Phase 5 — Analysis, plots and cost model](#8-phase-5--analysis-plots-and-cost-model)
9. [Phase 6 — Dashboard on the live URL](#9-phase-6--dashboard-on-the-live-url)
10. [Phase 7 — Report, README and viva](#10-phase-7--report-readme-and-viva)
11. [Makefile reference](#11-makefile-reference)
12. [CI/CD](#12-cicd)
13. [Cost estimate and budget guardrails](#13-cost-estimate-and-budget-guardrails)
14. [Troubleshooting run-book](#14-troubleshooting-run-book)
15. [Appendix — issue-creation script, templates](#15-appendix)

---

## 0. Changes and fixes to the original plan

These are problems in the PDF plan that would cause bugs, wrong results or surprise cost. Each one is applied in the sections below.

| # | Issue in PDF plan | Consequence if left | Fix in this plan |
|---|---|---|---|
| F1 | `asg.tf` ignores only `desired_capacity` | `asg_mode.py` changes `min_size`/`max_size`; the next `terraform apply` silently resets them mid-experiment | `ignore_changes = [desired_capacity, min_size, max_size]`; the hard max of 6 is enforced in `asg_mode.py` and `proactive_scaler.py` (`MAX_CAP=6`) |
| F2 | `/internal/stats` is served by the app on port 8000, which the ALB forwards | Stats endpoint is publicly reachable through CloudFront | ALB listener rule: `path /internal/*` → fixed 404 (priority 1). Scaler reaches it directly on the private IP |
| F3 | CloudFront price class "100 or 200" | `PriceClass_100` has **no Indian edge locations**; Mumbai viewers would be served from Europe | Use `PriceClass_200` (includes India) |
| F4 | Per-IP rate limit on the origin | Behind CloudFront + ALB, the socket IP is the ALB, and `X-Forwarded-For[0]` is client-spoofable | Key = `CloudFront-Viewer-Address` if present, else the 2nd-from-right `X-Forwarded-For` entry (CloudFront appends the real client, ALB appends the edge) |
| F5 | Scaler "sums rps" from instances | If rps is counted on completion, a saturated instance reports its capacity, not demand, so the scaler underestimates load | `stats.py` counts **arrivals** in the middleware, before the thread-pool queue. Arrival rate ≈ offered load |
| F6 | Dashboard and `results.json` are baked into the container image | Every new result needs a new image → new AMI → instance refresh | Dashboard is a static site in an S3 bucket behind the same CloudFront distribution (default behaviour); `/api/*` goes to the ALB. `make publish-site` = `s3 sync` + invalidation. The app still serves `web/` locally for `make dev` |
| F7 | Terraform state not mentioned | Several members running `terraform apply` with local state → duplicate or orphaned resources, surprise bill | S3 backend with native lock file (`use_lockfile = true`, Terraform **>= 1.10**). Only role A runs `apply`; everyone else runs `plan` |
| F8 | Loadgen "clones the repo" | Needs Git credentials on the instance if the repo is private | `make push-harness` uploads `loadtest/ automation/ config/` as a tarball to the results bucket; loadgen pulls it with its instance role |
| F9 | Baked AMI `systemctl enable streamlite` | The service can start before user_data writes `/etc/streamlite.env`, so it runs with defaults (wrong `WORK_SCALE`) | AMI installs the unit **disabled**; user_data writes the env file and runs `systemctl enable --now streamlite` |
| F10 | Loadtest token in env / user_data | Token visible in launch template and in Git if anyone commits tfvars | `random_password` → SSM **SecureString** `/streamlite/loadtest_token`; app and k6 runner read it at start-up |
| F11 | Public IPv4 cost not mentioned | Since Feb 2024 every public IPv4 address costs $0.005/h (ALB uses one per AZ). Always-on stack costs more than expected | Counted in §13; demo stack uses 1 small instance |
| F12 | k6 CSV timestamp precision | The default CSV timestamp is whole seconds, which is too coarse for some per-second joins | `K6_CSV_TIME_FORMAT=unix_milli` |
| F13 | Only the single-process stats design is specified | If E1 shows GIL contention and you switch to 2 workers, `/internal/stats` breaks | `stats.py` writes per-process snapshots to `/dev/shm/streamlite-<pid>.json`; `/internal/stats` aggregates all of them. Switching to `--workers 2` is a one-line change |
| F14 | Analysis and dashboard wait for real data | Roles B and D are idle on days 3–4 | `analysis/fake_run.py` generates synthetic run folders in the real schema, so parsing, plots and dashboard are built in parallel with infra |
| F15 | E4 has no AWS-native pre-warm baseline | Viva question: "why not AWS scheduled/predictive scaling or warm pools?" | Optional **E4(d)** (P2): ASG *scheduled action* at match start, and a note on Warm Pools. Gives a fair comparison |
| F16 | IMDS hop limit | Containers on a bridge network can't reach IMDSv2 with hop limit 1 | `http_put_response_hop_limit = 2` (harmless with `--network host`) |
| F17 | Packer and "no SSH anywhere" | Packer's default temporary SG opens port 22 to 0.0.0.0/0 | `temporary_security_group_source_public_ip = true` (opens 22 only to the builder's IP, deleted after the build) or `ssh_interface = "session_manager"` |

---

## 1. Global conventions

### 1.1 Names, tags, region

| Thing | Value |
|---|---|
| Region | `ap-south-1` (3 AZs: `ap-south-1a/b/c`) |
| Name prefix | `hsl` (hotstar-scale-lab) — e.g. `hsl-alb`, `hsl-asg`, `hsl-app-sg` |
| Required tags (provider `default_tags`) | `project=hotstar-scale-lab`, `owner=<team>`, `managed_by=terraform`, `course=IT457` |
| SSM parameters | `/streamlite/degrade_level` (String, "0"/"1"), `/streamlite/loadtest_token` (SecureString) |
| Buckets | `hsl-results-<suffix>`, `hsl-site-<suffix>`, `hsl-tfstate-<suffix>` (created by hand, §3.3) |
| Container image | `ghcr.io/<org-lowercase>/streamlite:<git-sha>` and `:latest` |
| App port | 8000 (container uses `--network host`) |

### 1.2 Environment variables (master list — app)

| Var | Default | Used by | Meaning |
|---|---|---|---|
| `WORK_SCALE` | `1.0` | work.py | Multiplies every CPU-burn iteration count. Tuned in §4.6 so C1 ≈ 100 rps |
| `DEGRADE_LEVEL` | `0` | degrade.py | Fallback when SSM is unreachable (local dev) |
| `SSM_DEGRADE_PARAM` | `/streamlite/degrade_level` | degrade.py | SSM parameter polled every 5 s |
| `SSM_TOKEN_PARAM` | `/streamlite/loadtest_token` | ratelimit.py | Read once at start-up |
| `LOADTEST_TOKEN` | *(empty)* | ratelimit.py | Local fallback when SSM is unreachable |
| `AUTO_SHED` | `false` | main.py | Shed non-critical requests when in-flight > `SHED_INFLIGHT` |
| `SHED_INFLIGHT` | `48` | main.py | Shedding threshold (must be < `THREADS`) |
| `THREADS` | `64` | main.py | anyio thread-limiter tokens |
| `RATE_LIMIT_RPS` | `20` | ratelimit.py | Per-client limit on `/api/*` without a valid token |
| `RATE_LIMIT_BURST` | `40` | ratelimit.py | Token-bucket burst |
| `APP_VERSION` | git SHA (baked at build) | whoami | Shown on dashboard |
| `AWS_REGION` | `ap-south-1` | boto3 | |
| `STATS_DIR` | `/dev/shm` | stats.py | Per-process snapshot dir (F13) |

### 1.3 Git workflow

- `main` is protected: 1 approving review, CI green, no force-push. Branches: `feat/<issue#>-slug`, `fix/…`, `infra/…`, `exp/…`, `docs/…`.
- Conventional Commit messages, exactly as the PDF lists (e.g. `feat(app): endpoints and cpu work model`). Reference the issue: `… (#12)`.
- **Every member commits every week.** The reviewer is never the author. Squash-merge so the history reads phase by phase.
- Release tags: `v0.1` app, `v0.2` live URL, `v0.3` harness, `v0.4` results, `v1.0` final.
- Never commit: `*.tfvars` (except `*.tfvars.example`), `.env`, `results/*/raw/`, `*.pem`, `terraform.tfstate*`, `.terraform/`.

### 1.4 Definition of "done" for any task

1. Code merged to `main` via PR, CI green.
2. The acceptance check in this document passes, with evidence pasted in the PR (command output, screenshot or CSV head).
3. If the task changes how to run something, `docs/runbook.md` is updated in the same PR.
4. Issue closed with a link to the PR. `docs/progress.md` gets a line at the end of the day.

---

## 2. Task backlog, dependencies and day-by-day schedule

### 2.1 Backlog (one GitHub issue per row; §15.1 creates them)

Est = focused hours. P = priority tag from the PDF.

| ID | Task | Role | Est | Depends on | P |
|---|---|---|---|---|---|
| **T0.1** | Repo, branch protection, `.gitignore`, licence, PR template, issue labels | A | 0.5 | – | P0 |
| T0.2 | AWS SSO/profile per member, `aws sts get-caller-identity` works | all | 0.5 | – | P0 |
| **T0.3** | Budget ($25/month, alerts 50/80/100 %) + **vCPU quota request (32)** | A | 0.5 | T0.2 | P0 |
| T0.4 | `scripts/doctor.sh` + `make doctor` | B | 0.5 | T0.1 | P0 |
| T0.5 | Terraform state bucket (manual, versioned) | A | 0.25 | T0.2 | P0 |
| T0.6 | `docs/sources.md` with Week 1 sources + confidence labels | D | 2 | – | P0 |
| T0.7 | Issues + project board created (§15.1) | D | 0.5 | T0.1 | P0 |
| **T1.1** | `config.py`, `work.py`, `imds.py` | B | 1.5 | T0.1 | P0 |
| **T1.2** | `stats.py` (arrival counting, in-flight, p95, multi-process snapshots) | B | 2 | T1.1 | P0 |
| **T1.3** | `main.py` endpoints + middleware | B | 2 | T1.2 | P0 |
| T1.4 | `degrade.py` (SSM poller) + auto-shed | B | 1 | T1.3 | P0 |
| T1.5 | `ratelimit.py` + token bypass | B | 1 | T1.3 | P0 |
| T1.6 | pytest suite (§4.7) | B | 2 | T1.3–T1.5 | P0 |
| **T1.7** | Dockerfile + `ci.yml` + `docker.yml` → GHCR public | B | 1.5 | T1.6 | P0 |
| T1.8 | `scripts/calibrate.py` | B | 1 | T1.1 | P0 |
| T1.9 | `docker-compose.yml` (nginx + `--scale app=2`) | C | 1 | T1.7 | P1 |
| **T2.1** | TF: versions, backend, variables, network, iam, ssm | A | 2 | T0.5 | P0 |
| **T2.2** | TF: alb (+ `/internal/*` block rule), asg + launch template, user_data templates | A | 2.5 | T2.1 | P0 |
| **T2.3** | Packer baked AMI + `make ami` | A | 2 | T1.7 | P0 |
| **T2.4** | TF: S3 site + CloudFront (two origins, three behaviours) | A | 2 | T2.2 | P0 |
| T2.5 | TF: loadgen + results bucket + budgets + outputs | A | 1.5 | T2.1 | P0 |
| **T2.6** | First deploy + smoke test script → **live URL** | A | 1 | T2.2–T2.4 | P0 |
| T2.7 | Calibration on c6i.large → `WORK_SCALE`, `ITER` table | B+C | 1.5 | T2.6, T1.8 | P0 |
| **T3.1** | k6 `lib.js` (mix, tags, token, open model) | C | 1.5 | T1.3 | P0 |
| T3.2 | k6 `step.js`, `fixed.js`, `spike.js` | C | 1.5 | T3.1 | P0 |
| **T3.3** | `asg_mode.py` | C | 2 | T2.2 | P0 |
| T3.4 | `monitor_asg.py` (+ instance launch/healthy log) | C | 1.5 | T2.2 | P0 |
| **T3.5** | `proactive_scaler.py` | C | 2.5 | T1.2, T3.3 | P0 |
| T3.6 | `run_experiment.sh` + `collect_cw.py` + `push-harness` | C | 2.5 | T3.2–T3.5, T2.5 | P0 |
| T3.7 | Dry run at C1=10 (acceptance) | C | 1 | T3.6 | P0 |
| T4.1 | E1 single-instance capacity (×3) → write C1 to `experiments.yaml` | C | 1.5 | T2.7, T3.7 | P0 |
| T4.2 | E2 latency vs N (fixed + step) | C | 3 | T4.1 | P0 |
| T4.3 | E5 baked vs naive boot | A | 1.5 | T4.1 | P1 |
| T4.4 | E3 reactive ×3 | C | 1.5 | T4.1 | P0 |
| T4.5 | E4 proactive a/b/c (c ×3, a/b ×1 minimum) | C | 3 | T4.4 | P0 |
| T4.6 | E6 degradation (none / SSM / auto-shed) | C | 1.5 | T4.1 | P1 |
| T4.7 | E7 CDN offload | A | 1 | T4.1 | P1 |
| **T5.1** | `fake_run.py` synthetic data generator | D | 1.5 | T3.6 schema | P0 |
| **T5.2** | `parse_k6.py` → `aggregates.parquet` + `summary.json` | D | 3 | T5.1 | P0 |
| T5.3 | `make_plots.py` F1–F7 | D | 3 | T5.2 | P0 |
| T5.4 | `cost_model.py` + `prices.yaml` + `model.yaml` (E8) | D | 2.5 | – | P0 |
| T5.5 | `results.json` export for the dashboard | D | 1 | T5.3, T5.4 | P0 |
| T6.1 | Dashboard skeleton, case facts, architecture SVG, limitations | B | 3 | T2.4 | P0 |
| T6.2 | Results charts from `results.json` (+ "results pending" state) | B | 2 | T5.5 schema | P0 |
| T6.3 | Live panel (whoami poll) | B | 1 | T6.1 | P0 |
| T6.4 | Mini burst test | B | 1 | T6.3 | P1 |
| T6.5 | Cost calculator widget | B | 1.5 | T5.4 | P1 |
| T7.1 | README, `runbook.md`, `architecture.md` | A+D | 2 | T2.6 | P0 |
| T7.2 | Report sections 1–4 (can start day 1) | D | 6 | T0.6 | P0 |
| T7.3 | Report sections 5–8 | D+all | 5 | T5.3 | P0 |
| T7.4 | Viva slides (10) + rehearsal | all | 3 | T7.3 | P0 |
| T7.5 | Teardown (after viva) | A | 0.5 | viva | P0 |
| T8.x (P2) | Spot mixed-instances; kind+HPA comparison; Locust cross-check; E4(d) scheduled action | any | – | P0 done | P2 |

### 2.2 Critical path

```
T0.3 quota ─┐
T1.1→T1.3→T1.6→T1.7 image ─→ T2.3 AMI ─→ T2.6 LIVE URL ─→ T2.7 calibrate ─→ T4.1 E1 (C1)
T0.5→T2.1→T2.2→T2.4 ───────────────────────┘                                   │
T3.1→T3.2, T3.3→T3.5→T3.6→T3.7 dry run ────────────────────────────────────────┘
                                                                               ↓
                    E2 → E5 → E3 → E4 → E6 → E7 → T5.2/T5.3 real plots → T5.5 → T6.2 → report → viva
```

Everything off this path (sources, report sections 1–4, fake data, analysis code, dashboard skeleton, cost model) runs in parallel. **Ask for the vCPU quota on day 1, hour 1.** It is the only blocker you cannot fix by working harder.

### 2.3 Day-by-day schedule (7 days, 4 roles)

Each day ends with a **gate**: a demo-able check. If a gate slips, cut P1/P2 from later days; never cut a P0.

| Day | A — Infra/IaC | B — App & Frontend | C — Load test & automation | D — Analysis & Docs | Gate (end of day) |
|---|---|---|---|---|---|
| 1 | T0.1, T0.3, T0.5, T2.1 | T0.4, T1.1, T1.2, start T1.3 | Install k6; T3.1 against `make dev` | T0.6, T0.7, report §1–2 outline | `make doctor` green for all; quota requested; app answers `/healthz` locally |
| 2 | T2.2, T2.5 | T1.3–T1.6, T1.7 (image on GHCR) | T3.2, T1.9 local compose; local k6 smoke | T5.1 fake data, T5.4 cost model skeleton | Image `:sha` public on GHCR; `terraform plan` clean |
| 3 | T2.3 AMI, T2.4, **T2.6 live URL** | T6.1 dashboard skeleton → S3 | T3.3, T3.4 against the live ASG | T5.2 parser on fake data | **Live HTTPS URL** shows dashboard + whoami; tag `v0.2` |
| 4 | Support C; T7.1 runbook | T2.7 calibrate (with C); T6.3 live panel | T3.5, T3.6, T3.7 dry run, **T4.1 E1** | T5.3 plots on fake data | C1 written to `experiments.yaml`; dry run artefacts complete; tag `v0.3` |
| 5 | T4.3 E5, T4.7 E7 | T6.2 charts wired to schema; T6.4 | T4.2 E2, T4.4 E3, start T4.5 E4 | Parse real E1/E2 as they land; F1 draft | **F1 (response time vs instance count) from real data** |
| 6 | `make destroy-lab`; cost check in Billing | T6.5 calculator; publish real `results.json` | Finish E4, T4.6 E6 | T5.3 F2–F7 final, T5.5, report §5–6 | All P0 experiments done; dashboard shows real results; tag `v0.4` |
| 7 | Report §8, slides infra part | Slides demo part; phone test | Slides results part | Report §7 + final edit; sources check | Report PDF, slides, rehearsal ×2; tag `v1.0` |

**Team of 3:** see `docs/TEAM_PLAN_3_PEOPLE.md` for the full split, merge order and reviewers (it replaces this table for a 3-person team). **Team of 5:** split A into Infra (T2.x) and CI/CD + Packer (T1.7, T2.3, T7.1).

---

## 3. Phase 0 — Setup and guardrails

### 3.1 Repository skeleton (T0.1)

```
hotstar-scale-lab/
  README.md  LICENSE  Makefile  .gitignore  .editorconfig  pyproject.toml (ruff + pytest config)
  .github/{workflows/ci.yml, workflows/docker.yml, pull_request_template.md, CODEOWNERS}
  app/      main.py config.py work.py stats.py degrade.py ratelimit.py imds.py
            requirements.txt requirements-dev.txt Dockerfile tests/
  web/      index.html app.js styles.css data/results.json img/architecture.svg
  scripts/  doctor.sh calibrate.py smoke.sh
  infra/terraform/  versions.tf backend.tf variables.tf network.tf iam.tf ssm.tf alb.tf asg.tf
                    site.tf cloudfront.tf loadgen.tf budgets.tf outputs.tf
                    templates/{user_data_baked.sh.tftpl,user_data_naive.sh.tftpl,user_data_loadgen.sh.tftpl}
                    terraform.tfvars.example
  infra/packer/     streamlite.pkr.hcl provision.sh
  loadtest/k6/      lib.js step.js fixed.js spike.js
  automation/       asg_mode.py monitor_asg.py proactive_scaler.py collect_cw.py common.py
                    run_experiment.sh run_campaign.sh
  analysis/         fake_run.py parse_k6.py make_plots.py cost_model.py export_results.py requirements.txt
  config/           experiments.yaml model.yaml prices.yaml
  results/          .gitkeep   (E*/run*/raw/ ignored; summary.json + *.png committed)
  docs/             architecture.md sources.md runbook.md progress.md report/ viva.md
  docker-compose.yml  nginx.conf
```

`.gitignore` (minimum):
```
__pycache__/  .venv/  .pytest_cache/  .ruff_cache/
.terraform/  *.tfstate*  *.tfvars  !*.tfvars.example  crash.log
results/*/*/raw/  results/**/k6.csv.gz  results/**/*.parquet
.env  *.pem  packer_cache/  manifest.json
```

### 3.2 `scripts/doctor.sh` (T0.4)

Checks each tool and **minimum** version. Exits non-zero if any are missing.

| Tool | Min | Check command |
|---|---|---|
| python3 | 3.12 | `python3 -c 'import sys; assert sys.version_info >= (3,12)'` |
| docker | 24 | `docker version --format '{{.Server.Version}}'` |
| terraform | 1.10 | `terraform version -json \| jq -r .terraform_version` |
| packer | 1.10 | `packer version` |
| k6 | 1.0 | `k6 version` |
| aws | 2.x | `aws --version` |
| session-manager-plugin | any | `session-manager-plugin --version` (needed for `aws ssm start-session`) |
| jq, make, git | any | `command -v` |

It also prints `aws sts get-caller-identity --query Account` and `aws configure get region` (must be `ap-south-1`).

### 3.3 AWS account (T0.2, T0.3, T0.5) — console steps only role A does

1. IAM Identity Center user per member (or IAM users with MFA). Never use root keys. Profile name `hsl`; everyone exports `AWS_PROFILE=hsl`.
2. **Service Quotas → EC2 → "Running On-Demand Standard (A, C, D, H, I, M, R, T, Z) instances"** → request **32 vCPU**. Need: 6 × c6i.large (12) + 1 × c6i.xlarge loadgen (4) + Packer builder (2) = 18. Write the granted number in `docs/runbook.md`.
3. Budget: Billing → Budgets → monthly cost $25, alerts at 50/80/100 % actual + 100 % forecast, to every member's email. (Terraform adds a second one in T2.5.)
4. Cost Explorer: enable (takes 24 h to populate).
5. State bucket (one-off, by hand so it survives `terraform destroy`):
   ```bash
   SUFFIX=$(openssl rand -hex 3)
   aws s3api create-bucket --bucket hsl-tfstate-$SUFFIX --region ap-south-1 \
     --create-bucket-configuration LocationConstraint=ap-south-1
   aws s3api put-bucket-versioning --bucket hsl-tfstate-$SUFFIX --versioning-configuration Status=Enabled
   aws s3api put-public-access-block --bucket hsl-tfstate-$SUFFIX \
     --public-access-block-configuration BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true
   ```

### 3.4 `docs/sources.md` format (T0.6)

```markdown
| # | Claim | Value | Source (title, URL, date accessed) | Type | Confidence |
|---|-------|-------|------------------------------------|------|-----------|
| S1 | Peak concurrency, final ICC WC 2023 (19 Nov 2023) | 59M | Disney / TechCrunch, … | press | official |
| S2 | Same event, alternative figure | 61M | ByteByteGo, … | blog | secondary (conflicts with S1) |
| S3 | Spike: 1M+ users/min, ~90 s to react | … | Hotstar eng. blog … | eng blog | official |
```
Confidence ∈ {official, secondary, unverified}. Every number in the report and on the dashboard cites an `S#`. Read the Hotstar blogs in a browser (they return 403 to scripts). Confirm the CDN vendor(s) or mark it *unverified*.

**Acceptance (Phase 0):** `make doctor` passes for every member (screenshot in PR) · budget exists · quota request ID and granted value in `runbook.md` · `sources.md` has ≥ 8 rows.
**Commit:** `chore: repo skeleton, tooling check, sources log`

---

## 4. Phase 1 — StreamLite application

### 4.1 Module map

```
main.py ──uses──> config.py   (env parsing → frozen dataclass CFG)
        ──uses──> work.py     (burn(kind): CPU work, GIL released)
        ──uses──> stats.py    (arrivals, in-flight, latency ring, shed counter, snapshots)
        ──uses──> degrade.py  (background SSM poller → level())
        ──uses──> ratelimit.py(token bucket per client, token bypass)
        ──uses──> imds.py     (instance_id, az, launch info; 'local' fallback)
```

### 4.2 `config.py`

```python
from dataclasses import dataclass
import os

def _b(name, default):  return os.getenv(name, str(default)).lower() in ("1", "true", "yes")

@dataclass(frozen=True)
class Config:
    work_scale: float      = float(os.getenv("WORK_SCALE", "1.0"))
    degrade_level: int     = int(os.getenv("DEGRADE_LEVEL", "0"))
    ssm_degrade_param: str = os.getenv("SSM_DEGRADE_PARAM", "/streamlite/degrade_level")
    ssm_token_param: str   = os.getenv("SSM_TOKEN_PARAM", "/streamlite/loadtest_token")
    loadtest_token: str    = os.getenv("LOADTEST_TOKEN", "")
    auto_shed: bool        = _b("AUTO_SHED", False)
    shed_inflight: int     = int(os.getenv("SHED_INFLIGHT", "48"))
    threads: int           = int(os.getenv("THREADS", "64"))
    rate_limit_rps: float  = float(os.getenv("RATE_LIMIT_RPS", "20"))
    rate_limit_burst: int  = int(os.getenv("RATE_LIMIT_BURST", "40"))
    app_version: str       = os.getenv("APP_VERSION", "dev")
    region: str            = os.getenv("AWS_REGION", "ap-south-1")
    stats_dir: str         = os.getenv("STATS_DIR", "/dev/shm")

CFG = Config()
```
Validation at import: `assert CFG.shed_inflight < CFG.threads`.

### 4.3 `work.py` — CPU model

```python
import hashlib
from config import CFG

# Iterations per class. Placeholders until T2.7 calibrates on c6i.large.
ITER = {"critical": 30_000, "heartbeat": 4_000, "state": 2_000, "reco": 80_000}

def burn(kind: str) -> None:
    n = max(1, int(ITER[kind] * CFG.work_scale))
    hashlib.pbkdf2_hmac("sha256", b"streamlite", b"salt", n)   # OpenSSL path releases the GIL
```
Why PBKDF2: it does a fixed amount of CPU work and releases the GIL, so two threads really use two vCPUs. A `while time() < t` loop measures wall time, so on a contended core it does *less* work and hides saturation.

**Calibration maths (to sanity-check T2.7).** Target CPU ms per request: playback 15, heartbeat 2, state 1, reco 40. With the PDF mix (55 % heartbeat, 10 % playback, 20 % state, 15 % reco):

```
mean CPU/request = 0.55·2 + 0.10·15 + 0.20·1 + 0.15·40 = 8.8 ms
2 vCPU = 2000 CPU-ms/s → theoretical ceiling ≈ 227 rps at WORK_SCALE=1
target C1 ≈ 100 rps → WORK_SCALE ≈ 2.0 (minus Python/HTTP overhead, so expect 1.6–1.9)
```
Note: recommendations are **68 %** of CPU (0.15·40/8.8). So degradation (E6) should raise capacity about 3× — write that prediction down **before** running E6.

### 4.4 `stats.py` — the numbers the scaler and dashboard depend on

State (per process):
- `arrivals[10]`: ring of 1-second buckets, incremented **when a request arrives** (in middleware, before `call_next`). `rps = sum(arrivals over last 10 full seconds) / 10`.
- `completions[10]` the same but on completion (useful to compare with arrivals).
- `inflight: int`. Only the event-loop thread changes it (in async middleware), so no lock is needed.
- `lat: deque[(t_end, dur_s, path_class)]` with `maxlen=20000`. Entries older than 10 s are pruned on read. p95 = `statistics.quantiles(…, n=20)[-1]` over entries in the window.
- `shed_total`, `rate_limited_total`, `errors_total` counters.
- `started_at = time.time()`.

Snapshot writer (F13): a background thread writes `{pid, ts, rps, inflight, p95_ms, shed_total, ...}` to `${STATS_DIR}/streamlite-<pid>.json` every 1 s (write to `.tmp`, then `os.replace` so the swap is atomic). `/internal/stats` reads every `streamlite-*.json` with `ts` < 3 s old and aggregates them: sum rps/inflight/shed, max p95 (conservative). With 1 process it reads its own file, so the code path is the same.

`/internal/stats` response (contract shared with the scaler and tests):
```json
{"instance_id":"i-0abc","az":"ap-south-1b","ts":1763000000.12,
 "rps":96.4,"rps_completed":95.8,"in_flight":7,"p95_ms":41.2,
 "active_viewers":1832,"cpu_percent":61.0,"degrade_level":0,
 "auto_shed":false,"shed_total":0,"rate_limited_total":0,"workers":1,"version":"a1b2c3d"}
```

### 4.5 `main.py` — endpoints and middleware

```python
import secrets, time, threading
from contextlib import asynccontextmanager
import anyio, psutil
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from config import CFG
import work, stats, degrade, ratelimit, imds

@asynccontextmanager
async def lifespan(app):
    anyio.to_thread.current_default_thread_limiter().total_tokens = CFG.threads
    imds.load(); degrade.start(); ratelimit.load_token(); stats.start_writer()
    psutil.cpu_percent(None)                       # prime the counter
    yield

app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None)

@app.middleware("http")
async def track(request: Request, call_next):
    path = request.url.path
    stats.on_arrival()
    if path.startswith("/api/") and not ratelimit.allow(request):
        stats.rate_limited()
        return JSONResponse({"error": "rate_limited"}, 429,
                            headers={"Retry-After": "1", "X-Instance-Id": imds.INSTANCE_ID})
    stats.inflight += 1
    t0 = time.perf_counter()
    try:
        resp = await call_next(request)
    except Exception:
        stats.on_error(); raise
    finally:
        stats.inflight -= 1
    stats.on_done(path, time.perf_counter() - t0, resp.status_code)
    resp.headers["X-Instance-Id"] = imds.INSTANCE_ID
    return resp

class PlaybackReq(BaseModel):  user_id: int; match_id: str
class HeartbeatReq(BaseModel): user_id: int; match_id: str

@app.get("/healthz")
def healthz(): return {"ok": True, "instance_id": imds.INSTANCE_ID}

@app.get("/api/v1/whoami")
def whoami():
    return {"instance_id": imds.INSTANCE_ID, "az": imds.AZ, "uptime_s": round(time.time()-stats.STARTED,1),
            "os_uptime_s": imds.os_uptime(), "in_flight": stats.inflight,
            "degrade_level": degrade.level(), "version": CFG.app_version}

@app.post("/api/v1/playback/start")
def playback_start(b: PlaybackReq):
    work.burn("critical")
    return {"manifest": f"https://cdn.example.invalid/{b.match_id}/master.m3u8",
            "token": secrets.token_hex(8), "instance_id": imds.INSTANCE_ID}

@app.post("/api/v1/heartbeat")
def heartbeat(b: HeartbeatReq):
    work.burn("heartbeat"); stats.viewer_seen(b.user_id)
    return {"ok": True}

@app.get("/api/v1/match/state")
def match_state():
    work.burn("state")
    return JSONResponse(stats.fake_score(), headers={"Cache-Control": "public, max-age=5"})

@app.get("/api/v1/recommendations")
def recommendations():
    if degrade.level() >= 1 or (CFG.auto_shed and stats.inflight > CFG.shed_inflight):
        stats.on_shed()
        return JSONResponse({"items": [], "degraded": True}, headers={"Cache-Control": "no-store"})
    work.burn("reco")
    return JSONResponse({"items": stats.fake_reco(), "degraded": False}, headers={"Cache-Control": "no-store"})

@app.get("/internal/stats")
def internal_stats(): return stats.aggregate()

app.mount("/", StaticFiles(directory="web", html=True, check_dir=False), name="web")   # local dev only
```
Rules: all endpoints are plain `def`, so they run in the thread pool. Every non-cacheable response sets `Cache-Control: no-store`, so CloudFront and browsers never cache them by accident. `fake_score()` is deterministic from `time.time()//5`, so every instance returns the same payload within a 5 s window (needed for E7 "identical payload").

`degrade.py`: a daemon thread runs `boto3.client("ssm").get_parameter(Name=…)` every 5 s with `connect_timeout=1, read_timeout=1, retries=0`. On any exception it keeps the last good value (or `CFG.degrade_level` if there never was one). It exposes `level()` and `source()` ∈ {ssm, env}.

`ratelimit.py`: dict `key → (tokens, last_ts)`, refilled at `RATE_LIMIT_RPS` up to `RATE_LIMIT_BURST`. Key per F4. Bypass when `hmac.compare_digest(header("X-Load-Test"), TOKEN)` and `TOKEN != ""`. Prune keys idle for more than 60 s, every 10 s. A `threading.Lock` around the dict (the middleware is async, but keep it safe for the future).

`imds.py`: IMDSv2 `PUT /latest/api/token` (TTL 21600, timeout 0.3 s), then `GET instance-id`, `placement/availability-zone`. On failure: `INSTANCE_ID = "local-" + socket.gethostname()`, `AZ = "local"`. Read once at start-up.

### 4.6 Calibration (T1.8 tool, T2.7 run)

`scripts/calibrate.py`:
1. For each kind, time `burn(kind)` 200 times at `WORK_SCALE=1` in **one** thread → ms/iteration-unit.
2. Print the iterations needed for 15 / 2 / 1 / 40 ms → paste them into `ITER`.
3. Re-run with 2 threads in parallel and report the speed-up (should be ≥ 1.8× on c6i.large, which proves the GIL is released).

Run it on a real c6i.large via SSM (`docker run --rm --entrypoint python ghcr.io/…:sha /app/scripts/calibrate.py`). Then run `step.js` with a guessed C1 and change `WORK_SCALE` until the knee (p95 crosses 300 ms) sits at **95–110 rps**. Record `ITER`, `WORK_SCALE` and the measured knee in `config/experiments.yaml` and the PR.

**GIL check (E1 pre-flight):** during the top step of `step.js`, `cpu_percent` from `/internal/stats` must reach ≥ 90 %. If it stalls around 50–60 % while p95 explodes, set `WEB_CONCURRENCY=2` (uvicorn `--workers 2`). Stats keep working thanks to F13.

### 4.7 Tests (`app/tests/`, pytest + `fastapi.testclient`)

| Test | Asserts |
|---|---|
| `test_endpoints_shape` | every endpoint returns 200 and the JSON keys in §4.4/§4.5; `X-Instance-Id` present |
| `test_cache_headers` | match/state has `public, max-age=5`; reco and playback have `no-store` |
| `test_degrade_level1` | monkeypatch `degrade.level → 1` ⇒ reco returns `{"items":[],"degraded":true}` and `shed_total` +1 |
| `test_auto_shed` | `AUTO_SHED=true`, force `stats.inflight = SHED_INFLIGHT+1` ⇒ fallback; inflight below ⇒ real items |
| `test_rate_limit` | 41 rapid requests without a token → at least one 429; with a valid `X-Load-Test` → none |
| `test_rate_limit_key` | requests with different `CloudFront-Viewer-Address` values have separate buckets |
| `test_internal_stats_keys` | all keys from the contract; `rps` > 0 after 20 requests (with fake time) |
| `test_stats_aggregate_multiproc` | two snapshot files in a tmp `STATS_DIR` ⇒ rps summed, p95 = max |
| `test_work_burn_scales` | `WORK_SCALE=2` takes ≥ 1.6× as long as 1 (loose bound, marked `slow`) |
| `test_imds_fallback` | no IMDS ⇒ `local-*` id |

Run with `make test` (`pytest -q -m "not slow"` in CI, everything locally).

### 4.8 Container

```dockerfile
FROM python:3.12-slim
ARG GIT_SHA=dev
ENV PYTHONUNBUFFERED=1 APP_VERSION=$GIT_SHA WEB_CONCURRENCY=1
LABEL org.opencontainers.image.source="https://github.com/<org>/hotstar-scale-lab" \
      org.opencontainers.image.revision=$GIT_SHA
WORKDIR /app
COPY app/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app/ ./
COPY web/ ./web/
COPY scripts/calibrate.py ./scripts/
RUN useradd -u 10001 -m app
USER app
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=2s CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/healthz',timeout=1)"
CMD ["sh","-c","exec uvicorn main:app --host 0.0.0.0 --port 8000 --no-access-log --workers ${WEB_CONCURRENCY}"]
```
Build context is the repo root: `docker build -f app/Dockerfile -t streamlite .`
`requirements.txt` (pinned): `fastapi`, `uvicorn[standard]`, `boto3`, `psutil`, `pydantic`. Dev: `pytest`, `httpx`, `ruff`.

### 4.9 Local dry run (T1.9, P1)

`docker-compose.yml`: `app` service (image built locally, `WORK_SCALE=1`, `LOADTEST_TOKEN=local`) + `nginx` (round-robin upstream `app:8000`, port 8080). `docker compose up --scale app=2`, then `k6 run -e BASE_URL=http://localhost:8080 -e C1=20 -e TOKEN=local loadtest/k6/fixed.js`. Results are for debugging only, never reported.

**Acceptance (Phase 1):** CI green · container `/healthz` 200 in < 5 s (`time docker run …`) · 30 s local k6 smoke: critical p95 ≪ 300 ms at low load · `/internal/stats` rps within ±10 % of the k6 request rate.
**Commits:** `feat(app): endpoints and cpu work model` · `feat(app): stats with arrival counting` · `feat(app): degrade level and auto-shed` · `feat(app): rate limit with load-test bypass` · `test(app): endpoint and shedding tests` · `ci: lint, test, docker build` → tag `v0.1`.

---

## 5. Phase 2 — Infrastructure and the live URL

### 5.1 Topology

```
                       ┌──────────────── CloudFront (PriceClass_200, *.cloudfront.net HTTPS) ────────────────┐
viewer ──HTTPS──>      │  default (*)          → S3 site origin (OAC)           CachingOptimized           │
                       │  /api/v1/match/*      → ALB origin (http-only)        CachingOptimized (max-age=5)│
                       │  /api/*               → ALB origin                    CachingDisabled + AllViewerExceptHostHeader │
                       └─────────────────────────────────────────────────────────────────────────────────────┘
                                               │ :80
loadgen (c6i.xlarge, loadgen-sg) ──:80──> ALB (alb-sg) ── rule P1: /internal/* → 404 ──> TG :8000 (/healthz)
          │                                                                               │
          └────────────── :8000 /internal/stats (app-sg allows loadgen-sg) ─────> ASG c6i.large ×1..6 (app-sg)
```
Behaviour order matters: `/api/v1/match/*` must come **before** `/api/*`.

### 5.2 Terraform files

**`versions.tf` / `backend.tf`**
```hcl
terraform {
  required_version = ">= 1.10"
  required_providers {
    aws    = { source = "hashicorp/aws",    version = "~> 5.80" }
    random = { source = "hashicorp/random", version = "~> 3.6" }
  }
  backend "s3" {
    bucket = "hsl-tfstate-<suffix>"   # filled by -backend-config in make tf-init
    key = "hsl/terraform.tfstate"  region = "ap-south-1"  use_lockfile = true  encrypt = true
  }
}
provider "aws" {
  region = var.region
  default_tags { tags = { project = "hotstar-scale-lab", managed_by = "terraform", course = "IT457" } }
}
```

**`variables.tf`** — `region`, `ami_id` (baked), `instance_type="c6i.large"`, `loadgen_instance_type="c6i.xlarge"`, `image` (full GHCR ref), `asg_min=1`, `asg_max=6`, `asg_desired=1`, `user_data_mode` (validation: `baked|naive`), `work_scale="2.0"`, `enable_loadgen=false`, `alert_emails` (list), `budget_usd=25`, `suffix`. Add `validation { condition = var.asg_max <= 6 }`.

**`network.tf`** — `data "aws_vpc" "default" { default = true }`, `data "aws_subnets" "default"` filtered by vpc-id and `default-for-az=true`. Security groups:

| SG | Ingress | Egress |
|---|---|---|
| `hsl-alb-sg` | tcp 80 from 0.0.0.0/0 | tcp 8000 to `app-sg` |
| `hsl-app-sg` | tcp 8000 from `alb-sg`; tcp 8000 from `loadgen-sg` | all (GHCR, SSM, S3) |
| `hsl-loadgen-sg` | none | all |

No port 22 anywhere. Access is through SSM Session Manager only.

**`iam.tf`**
- `hsl-app-role` (EC2 trust): managed `AmazonSSMManagedInstanceCore`; inline `ssm:GetParameter` on `arn:aws:ssm:${region}:${acct}:parameter/streamlite/*`.
- `hsl-loadgen-role`: `AmazonSSMManagedInstanceCore` plus inline:
  - `autoscaling:DescribeAutoScalingGroups, DescribeScalingActivities, DescribePolicies, DescribeScheduledActions` (Resource `*`; Describe calls cannot be scoped)
  - `autoscaling:SetDesiredCapacity, UpdateAutoScalingGroup, PutScalingPolicy, DeletePolicy, PutScheduledUpdateGroupAction, DeleteScheduledAction` on the ASG ARN
  - `elasticloadbalancing:DescribeTargetHealth`, `ec2:DescribeInstances`, `cloudwatch:GetMetricData`
  - `ssm:GetParameter, PutParameter` on `/streamlite/*`
  - `s3:ListBucket` on the results bucket; `s3:GetObject, PutObject` on `bucket/*`
- Instance profiles for both.

**`ssm.tf`**
```hcl
resource "aws_ssm_parameter" "degrade" { name = "/streamlite/degrade_level" type = "String" value = "0"
  lifecycle { ignore_changes = [value] } }          # experiments flip it; TF must not reset it
resource "random_password" "token" { length = 32  special = false }
resource "aws_ssm_parameter" "token" { name = "/streamlite/loadtest_token" type = "SecureString" value = random_password.token.result }
```

**`alb.tf`**
```hcl
resource "aws_lb" "app" { name = "hsl-alb" load_balancer_type = "application" internal = false
  security_groups = [aws_security_group.alb.id] subnets = data.aws_subnets.default.ids idle_timeout = 30 }

resource "aws_lb_target_group" "app" {
  name = "hsl-tg" port = 8000 protocol = "HTTP" vpc_id = data.aws_vpc.default.id
  deregistration_delay = 30
  health_check { path = "/healthz" interval = 5 timeout = 3 healthy_threshold = 2 unhealthy_threshold = 2 matcher = "200" }
}
resource "aws_lb_listener" "http" { load_balancer_arn = aws_lb.app.arn port = 80 protocol = "HTTP"
  default_action { type = "forward" target_group_arn = aws_lb_target_group.app.arn } }

resource "aws_lb_listener_rule" "block_internal" {                         # F2
  listener_arn = aws_lb_listener.http.arn  priority = 1
  action { type = "fixed-response"
           fixed_response { content_type = "text/plain" status_code = "404" message_body = "not found" } }
  condition { path_pattern { values = ["/internal/*"] } }
}
```
Load balancing algorithm: keep **round robin** for E1–E7 (that is what the hockey-stick theory assumes). Mention `least_outstanding_requests` as discussion only.

**`asg.tf`**
```hcl
data "aws_ssm_parameter" "al2023" { name = "/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64" }

resource "aws_launch_template" "app" {
  name_prefix   = "hsl-app-"
  image_id      = var.user_data_mode == "baked" ? var.ami_id : data.aws_ssm_parameter.al2023.value
  instance_type = var.instance_type
  update_default_version = true
  iam_instance_profile { name = aws_iam_instance_profile.app.name }
  network_interfaces { associate_public_ip_address = true  security_groups = [aws_security_group.app.id] }
  metadata_options { http_endpoint = "enabled" http_tokens = "required" http_put_response_hop_limit = 2 }   # F16
  monitoring { enabled = true }
  credit_specification { cpu_credits = "standard" }    # only matters if you fall back to t3
  user_data = base64encode(templatefile("${path.module}/templates/user_data_${var.user_data_mode}.sh.tftpl", {
    image = var.image, work_scale = var.work_scale, region = var.region }))
  tag_specifications { resource_type = "instance" tags = { Name = "hsl-app", project = "hotstar-scale-lab" } }
}

resource "aws_autoscaling_group" "app" {
  name                      = "hsl-asg"
  min_size                  = var.asg_min
  max_size                  = var.asg_max
  desired_capacity          = var.asg_desired
  vpc_zone_identifier       = data.aws_subnets.default.ids
  target_group_arns         = [aws_lb_target_group.app.arn]
  health_check_type         = "ELB"
  health_check_grace_period = var.user_data_mode == "baked" ? 60 : 240
  default_instance_warmup   = 60
  metrics_granularity       = "1Minute"
  enabled_metrics = ["GroupDesiredCapacity","GroupInServiceInstances","GroupPendingInstances","GroupTotalInstances","GroupTerminatingInstances"]
  launch_template { id = aws_launch_template.app.id  version = aws_launch_template.app.latest_version }
  instance_refresh { strategy = "Rolling"  preferences { min_healthy_percentage = 100  max_healthy_percentage = 200 } }
  lifecycle { ignore_changes = [desired_capacity, min_size, max_size] }   # F1
}
# NO aws_autoscaling_policy here. Modes are applied by automation/asg_mode.py.
```

**`templates/user_data_baked.sh.tftpl`** (F9, F10)
```bash
#!/bin/bash
set -euo pipefail
cat >/etc/streamlite.env <<EOF
WORK_SCALE=${work_scale}
AWS_REGION=${region}
WEB_CONCURRENCY=1
EOF
systemctl enable --now streamlite
```
**`templates/user_data_naive.sh.tftpl`**: `dnf install -y docker && systemctl enable --now docker && docker pull ${image}`, write the same env file, then `docker run -d --restart always --network host --env-file /etc/streamlite.env ${image}`. Log `date +%s.%N` at the start and end of each step to `/var/log/hsl-boot.log`. E5 reads it through `aws ssm send-command` for the time breakdown.

**`site.tf`** (F6): private S3 bucket `hsl-site-<suffix>`, public access fully blocked, `aws_cloudfront_origin_access_control` (s3, sigv4, always). The bucket policy allows `s3:GetObject` for principal `cloudfront.amazonaws.com` with condition `AWS:SourceArn = aws_cloudfront_distribution.main.arn`.

**`cloudfront.tf`**
```hcl
data "aws_cloudfront_cache_policy"          "disabled"  { name = "Managed-CachingDisabled" }
data "aws_cloudfront_cache_policy"          "optimized" { name = "Managed-CachingOptimized" }
data "aws_cloudfront_origin_request_policy" "all_but_host" { name = "Managed-AllViewerExceptHostHeader" }

resource "aws_cloudfront_distribution" "main" {
  enabled = true  price_class = "PriceClass_200"  default_root_object = "index.html"  comment = "hsl"
  origin { origin_id = "site" domain_name = aws_s3_bucket.site.bucket_regional_domain_name
           origin_access_control_id = aws_cloudfront_origin_access_control.site.id }
  origin { origin_id = "alb"  domain_name = aws_lb.app.dns_name
           custom_origin_config { http_port = 80 https_port = 443 origin_protocol_policy = "http-only"
                                  origin_ssl_protocols = ["TLSv1.2"] origin_read_timeout = 30 } }
  default_cache_behavior { target_origin_id = "site" viewer_protocol_policy = "redirect-to-https"
    allowed_methods = ["GET","HEAD"] cached_methods = ["GET","HEAD"] compress = true
    cache_policy_id = data.aws_cloudfront_cache_policy.optimized.id }
  ordered_cache_behavior { path_pattern = "/api/v1/match/*" target_origin_id = "alb"
    viewer_protocol_policy = "redirect-to-https" allowed_methods = ["GET","HEAD"] cached_methods = ["GET","HEAD"]
    compress = true cache_policy_id = data.aws_cloudfront_cache_policy.optimized.id }
  ordered_cache_behavior { path_pattern = "/api/*" target_origin_id = "alb"
    viewer_protocol_policy = "redirect-to-https"
    allowed_methods = ["GET","HEAD","OPTIONS","PUT","POST","PATCH","DELETE"] cached_methods = ["GET","HEAD"]
    cache_policy_id = data.aws_cloudfront_cache_policy.disabled.id
    origin_request_policy_id = data.aws_cloudfront_origin_request_policy.all_but_host.id }
  restrictions { geo_restriction { restriction_type = "none" } }
  viewer_certificate { cloudfront_default_certificate = true }
}
```
`CloudFront-Viewer-Address` is not forwarded by `AllViewerExceptHostHeader`, so the rate limiter falls back to `X-Forwarded-For[-2]` (F4). That is enough. A custom origin-request policy that adds the header is an optional upgrade.

**`loadgen.tf`**: `count = var.enable_loadgen ? 1 : 0`, AL2023, c6i.xlarge, 30 GB gp3, loadgen-sg, loadgen profile. user_data: install a pinned k6 1.x release from GitHub (tarball → `/usr/local/bin/k6`), `dnf install -y python3-pip jq`, `pip3 install boto3 pyyaml`, `sysctl -w net.ipv4.ip_local_port_range="1024 65535"`, `ulimit -n 1048576` in `/etc/security/limits.d`. Results bucket `hsl-results-<suffix>` (versioning off, lifecycle: expire `harness/` after 30 days).

**`budgets.tf`**: `aws_budgets_budget` monthly `var.budget_usd`, notifications at 80 % actual and 100 % forecast to `var.alert_emails`.

**`outputs.tf`**: `cloudfront_url`, `cloudfront_id`, `alb_dns`, `asg_name`, `target_group_arn`, `tg_arn_suffix`, `alb_arn_suffix`, `loadgen_instance_id`, `results_bucket`, `site_bucket`. `make env` writes them to `.env.tf` (git-ignored), which the automation scripts source.

### 5.3 Packer (T2.3)

`infra/packer/streamlite.pkr.hcl`:
```hcl
packer { required_plugins { amazon = { source = "github.com/hashicorp/amazon", version = ">= 1.3.0" } } }
variable "org" {}  variable "tag" {}  variable "region" { default = "ap-south-1" }
source "amazon-ebs" "al2023" {
  region = var.region  instance_type = "c6i.large"  ssh_username = "ec2-user"
  ami_name = "hsl-streamlite-${var.tag}-{{timestamp}}"
  source_ami_filter { filters = { name = "al2023-ami-2023.*-x86_64", virtualization-type = "hvm" }
                      owners = ["amazon"]  most_recent = true }
  temporary_security_group_source_public_ip = true                     # F17
  metadata_options { http_tokens = "required" http_endpoint = "enabled" }
  tags = { project = "hotstar-scale-lab", git_sha = var.tag }
}
build { sources = ["source.amazon-ebs.al2023"]
  provisioner "shell" { script = "provision.sh" environment_vars = ["ORG=${var.org}", "TAG=${var.tag}"] execute_command = "sudo -E bash '{{.Path}}'" }
  post-processor "manifest" { output = "manifest.json" } }
```
`provision.sh` = PDF Appendix A with two changes: **do not** `systemctl enable streamlite` (F9), and add `EnvironmentFile=-/etc/streamlite.env` (the `-` makes the file optional). Also `dnf clean all`. `make ami` runs `packer init && packer build -var org=… -var tag=$(git rev-parse --short HEAD)`, extracts the AMI ID from `manifest.json` with `jq`, and writes it to `infra/terraform/ami.auto.tfvars` (git-ignored).

Fallback if Packer fails: launch one AL2023 instance, SSM in, run `provision.sh`, then `aws ec2 create-image --instance-id … --name hsl-streamlite-manual-<sha>`. Document it in the runbook.

### 5.4 First deployment (T2.6)

```bash
make tf-init                          # backend config from .backend.hcl
make ami                              # → ami.auto.tfvars
make tf-apply                         # ALB, ASG(1), CloudFront, site, SSM, budget
make publish-site                     # aws s3 sync web/ s3://$SITE --delete && invalidation /*
make smoke                            # scripts/smoke.sh
```
`scripts/smoke.sh`:
1. `curl -sf https://$CF/` contains `<title>`.
2. `curl -sf https://$CF/api/v1/whoami | jq -e .instance_id`.
3. `curl -s -o /dev/null -w '%{http_code}' https://$CF/internal/stats` → **404** (F2).
4. `curl -sI https://$CF/api/v1/match/state` twice → second has `x-cache: Hit from cloudfront`.
5. `python automation/asg_mode.py static 3`, then 30 × whoami directly on the ALB → ≥ 2 distinct `instance_id` and ≥ 2 AZs. Then `asg_mode.py reset`.
6. `aws ec2 describe-security-groups … | jq` → no rule with port 22.

CloudFront takes 5–15 min to deploy the first time. Start `tf-apply` before lunch, not before the demo.

**Acceptance (Phase 2):** smoke script all green (paste output into the PR) · `make destroy-lab` leaves exactly ALB + CloudFront + site bucket + 1 instance · tag `v0.2`.
**Commits:** `infra: network, iam, alb, asg` · `infra: packer baked ami` · `infra: cloudfront https front door and static site` · `infra: loadgen and results bucket` · `docs: runbook for deploy and teardown`.

---

## 6. Phase 3 — Load-test harness and automation

### 6.1 `loadtest/k6/lib.js`

```javascript
import http from "k6/http";
export const BASE = __ENV.BASE_URL;
export const C1 = Number(__ENV.C1 || 100);
const TOKEN = __ENV.TOKEN || "";
const N_USERS = Number(__ENV.N_USERS || 50000);
const MIX_NAME = __ENV.MIX || "default";
const MIXES = {
  default:    [["heartbeat",0.55],["playback",0.10],["state",0.20],["reco",0.15]],
  match_only: [["state",1.0]],
};
const MIX = MIXES[MIX_NAME];
const H = { "Content-Type": "application/json", "X-Load-Test": TOKEN };
const P = (cls, name) => ({ headers: H, tags: { class: cls, name }, timeout: "5s" });
const rid = () => 1 + Math.floor(Math.random() * N_USERS);

export function pick() {
  let r = Math.random(), k = MIX[MIX.length - 1][0];
  for (const [name, w] of MIX) { if ((r -= w) < 0) { k = name; break; } }
  switch (k) {
    case "heartbeat": return http.post(`${BASE}/api/v1/heartbeat`, JSON.stringify({ user_id: rid(), match_id: "m1" }), P("critical","heartbeat"));
    case "playback":  return http.post(`${BASE}/api/v1/playback/start`, JSON.stringify({ user_id: rid(), match_id: "m1" }), P("critical","playback"));
    case "state":     return http.get(`${BASE}/api/v1/match/state`, P("public","state"));
    case "reco":      return http.get(`${BASE}/api/v1/recommendations`, P("noncritical","reco"));
  }
}
export const THRESHOLDS = {   // reported, never abort
  "http_req_duration{class:critical}": [{ threshold: "p(95)<300", abortOnFail: false }],
  "http_req_failed": [{ threshold: "rate<0.01", abortOnFail: false }],
};
export const BASE_SCN = { executor: "ramping-arrival-rate", timeUnit: "1s",
  preAllocatedVUs: 200, maxVUs: 2000, gracefulStop: "10s" };
export function summaryTo(path) { return (data) => ({ [path]: JSON.stringify(data, null, 1) }); }
```
Run with `--discard-response-bodies` (saves loadgen CPU). Use a fixed `--tag run_id=…` so every sample carries the run id.

### 6.2 Profiles

**`step.js` (E1, E2b)**: `GUESS = Number(__ENV.GUESS || C1)`. Ten levels `r_i = (0.1 + i·1.9/9) · GUESS`, i = 0..9. Each level has a 5 s ramp plus a 55 s hold, so the total is 10 min. Export `STEP_STARTS` in `meta.json` so the parser can label steps.

**`fixed.js` (E2a, E6, E7)**: stages `[{target: FIXED_RPS, duration: "30s"}, {target: FIXED_RPS, duration: __ENV.HOLD || "5m"}]`, `startRate: 1`. The parser drops the first 30 s.

**`spike.js` (E3, E4)** — generated stages, total 12 m 30 s:
```javascript
import { pick, C1, BASE_SCN, THRESHOLDS } from "./lib.js";
const s = (x, d) => ({ target: Math.round(x * C1), duration: d });
const burst = [s(4.2,"5s"), s(4.2,"20s"), s(3.0,"5s")];
export const options = {
  scenarios: { match: { ...BASE_SCN, startRate: Math.round(0.3 * C1), stages: [
    s(0.3,"2m"),            // 0:00–2:00 pre-match
    s(3.0,"90s"),           // 2:00–3:30 match start ramp (Hotstar's ~90 s window)
    s(3.0,"90s"),           // 3:30–5:00 hold
    ...burst, s(3.0,"90s"), // 5:00–5:30 wicket, 5:30–7:00 hold
    ...burst, s(3.0,"90s"), // 7:00–7:30 wicket, 7:30–9:00 hold
    ...burst,               // 9:00–9:30 wicket
    s(0.5,"3m"),            // 9:30–12:30 innings break / ramp down
  ]}},
  thresholds: THRESHOLDS,
};
export default function () { pick(); }
```
Event markers for plots (seconds from start): ramp 120–210, bursts 300–330, 420–450, 540–570.

### 6.3 `automation/common.py`

Shared code: loads `.env.tf` / env (`ASG_NAME`, `TG_ARN`, `TG_SUFFIX`, `ALB_SUFFIX`, `RESULTS_BUCKET`), boto3 clients with `Config(retries={"mode":"adaptive","max_attempts":10})`, `MAX_CAP = 6`, `log()` with UTC ISO timestamps, `wait_stable(desired, quiet_s=120, timeout_s=900)`.

`wait_stable`: poll every 5 s until `in_service == desired`, `healthy_targets == desired`, `pending == 0`, `terminating == 0`, and no ASG activity `InProgress`. Then hold for `quiet_s` and confirm it stays stable; restart the quiet timer if anything changes.

### 6.4 `asg_mode.py`

```
usage: asg_mode.py {static N | reactive | proactive | scheduled AT_UTC N | reset} [--no-wait]
```
Every mode starts with `clear()`: delete all scaling policies (`describe_policies` → `delete_policy`) and scheduled actions. Then:

| Mode | Calls |
|---|---|
| `static N` | `assert 1 <= N <= MAX_CAP`; `update_auto_scaling_group(Min=N, Max=N, Desired=N)` |
| `reactive` | `update(Min=1, Max=6, Desired=1)`; `put_scaling_policy(PolicyName="cpu50", PolicyType="TargetTrackingScaling", EstimatedInstanceWarmup=120, TargetTrackingConfiguration={"PredefinedMetricSpecification":{"PredefinedMetricType":"ASGAverageCPUUtilization"},"TargetValue":50.0})` |
| `proactive` | `update(Min=1, Max=6, Desired=1)`; no policies (the scaler owns desired) |
| `scheduled` (P2, E4d) | `reactive` + `put_scheduled_update_group_action(StartTime=AT, MinSize=4, DesiredCapacity=4)` |
| `reset` | `static 1` |

Then `wait_stable(...)` unless `--no-wait`. Write the final ASG config as JSON to stdout (the runner saves it into `meta.json`).
Self-check at the end: `describe_policies` must list exactly the expected policy names, otherwise exit 2.

### 6.5 `monitor_asg.py`

Every `--interval` (default 5 s; E5 uses 2 s) it appends to two CSVs in the run folder:

`asg_timeline.csv`: `ts, desired, in_service, pending, terminating, healthy_targets, unhealthy_targets, initial_targets, draining_targets`

`instances.csv` (one row per instance, written once at first sight and updated when it changes): `instance_id, az, launch_time (EC2 API), first_seen_ts, in_service_ts, first_healthy_ts, terminated_ts`

Flush after every row. Exit cleanly on SIGTERM.

### 6.6 `proactive_scaler.py`

```
usage: proactive_scaler.py --per-instance-rps C1 [--headroom 1.6] [--prewarm N] [--floor-until UTC]
                           [--hold-min 5] [--tick 10] [--out results/E4/runK/scaler.csv]
```
Loop every `tick` seconds:
```python
ins  = in_service_instances()                      # ASG InService ∩ TG healthy
st   = fetch_stats(ins, timeout=1.0)               # parallel GETs to http://<private-ip>:8000/internal/stats
ok   = [s for s in st if s]                        # missing/timeout → None
rps  = sum(s["rps"] for s in ok) * (len(ins) / max(1, len(ok)))   # extrapolate if some failed
need = ceil(rps * headroom / per_instance_rps)
floor = prewarm if now < floor_until else 1
target = clamp(max(floor, need), 1, MAX_CAP)
if target > desired:   set_desired(target); last_change = now          # up: immediately, no cooldown
elif target < desired:
    if below_since is None: below_since = now
    if now - below_since >= hold_min*60 and now - last_change >= hold_min*60:
        set_desired(desired - 1); last_change = now; below_since = None   # down: one step per hold
else: below_since = None
log(ts, len(ins), len(ok), rps, need, floor, target, desired_before, desired_after, action)
```
- `set_desired` = `set_desired_capacity(AutoScalingGroupName, DesiredCapacity, HonorCooldown=False)`.
- Re-read `desired` from the ASG every tick. Do not trust a local copy.
- `--prewarm N`: before k6 starts, the runner calls `proactive_scaler.py --prewarm-only N`, which sets desired N and waits for `wait_stable` ("we know the match starts at 7 pm"). Then the main loop starts with `--floor-until = k6_start + 13 min`.
- Variants for E4: **(a)** prewarm 4, no ladder (`--headroom 0`, so `need = 0` and the floor rules); **(b)** ladder only, prewarm 1; **(c)** prewarm 4 + ladder.
- Unit tests (`automation/tests/test_scaler.py`) with a fake ASG: ramp 30→300 rps ⇒ desired 1→2→4→5; load drop ⇒ one step down per 5 min; a stats timeout on 1 of 3 instances ⇒ extrapolates; never > 6.

Why "arrivals" matter (F5): if a saturated instance reports completed requests, `rps` stops at N·C1 and `need = ceil(1.6·N)`. The ladder still climbs, but one step at a time. With arrivals, the scaler sees the true offered load and jumps straight to the right N.

### 6.7 `collect_cw.py`

`get_metric_data` for `[start − 5 min, end + 10 min]` (CloudWatch lags), `Period=60`, writing one CSV per metric into `cw/`:

| Namespace | Metric | Dimensions | Stat |
|---|---|---|---|
| AWS/ApplicationELB | RequestCount | LoadBalancer | Sum |
| AWS/ApplicationELB | RequestCountPerTarget | TargetGroup | Sum |
| AWS/ApplicationELB | TargetResponseTime | LoadBalancer | p50, p95, p99 |
| AWS/ApplicationELB | HTTPCode_ELB_5XX_Count, HTTPCode_Target_5XX_Count | LoadBalancer | Sum |
| AWS/ApplicationELB | HealthyHostCount, UnHealthyHostCount | TargetGroup, LoadBalancer | Max |
| AWS/EC2 | CPUUtilization | AutoScalingGroupName | Average, Maximum |
| AWS/AutoScaling | GroupDesiredCapacity, GroupInServiceInstances, GroupPendingInstances | AutoScalingGroupName | Max |

Dimension values: `LoadBalancer = alb_arn_suffix` (`app/hsl-alb/…`), `TargetGroup = tg_arn_suffix` (`targetgroup/hsl-tg/…`).

### 6.8 `run_experiment.sh`

```
usage: run_experiment.sh EXP_ID RUN_NO MODE PROFILE [extra k6 -e args...]
  e.g. run_experiment.sh E3 1 reactive spike
       run_experiment.sh E4c 2 "proactive --prewarm 4" spike
       run_experiment.sh E2a 1 "static 3" fixed FIXED_RPS=200
```
Steps (with `set -euo pipefail` and `trap cleanup EXIT INT TERM`, so a crash or Ctrl-C **always** resets the ASG, kills the monitor/scaler and syncs what exists):

1. `OUT=results/$EXP/run$RUN`; refuse if it exists (no accidental overwrite) unless `--force`. Read defaults (C1, WORK_SCALE, headroom…) from `config/experiments.yaml` via `yq` or a 5-line Python helper.
2. Pre-flight: `asg_mode.py reset` was run ≥ 5 min ago (timestamp file) **or** wait; loadgen 1-min load average < 0.5; `aws ssm get-parameter /streamlite/degrade_level` equals what the experiment expects.
3. `asg_mode.py $MODE` (waits stable). Start `monitor_asg.py &`. For proactive, start `proactive_scaler.py &`.
4. Write `meta.json` (schema §8.1) with start time.
5. `TOKEN=$(aws ssm get-parameter --with-decryption …)`; `K6_CSV_TIME_FORMAT=unix_milli k6 run --discard-response-bodies --tag run_id=$EXP-$RUN --out csv=$OUT/raw/k6.csv.gz -e BASE_URL=http://$ALB -e C1=$C1 -e TOKEN=$TOKEN … loadtest/k6/$PROFILE.js 2>&1 | tee $OUT/k6.log`. `handleSummary` writes `$OUT/summary.json`.
6. Record `k6_end`. Sleep 300 s (observe scale-in). Stop monitor/scaler.
7. `collect_cw.py --start … --end … --out $OUT/cw` (it waits until `end + 3 min` so CloudWatch has caught up).
8. Validity checks written into `meta.json.validity`: `dropped_iterations == 0`; loadgen CPU max < 70 % (sampled with `mpstat 5` in the background); no 429 in k6 output. A failing check marks the run `"valid": false` but still keeps it.
9. `aws s3 sync results/$EXP/ s3://$RESULTS_BUCKET/results/$EXP/`. `asg_mode.py reset --no-wait`; touch the reset timestamp.

`run_campaign.sh` reads a list (e.g. `config/campaign_day5.txt`) and runs the lines back to back, with the 5-min reset gap enforced by step 2. Run it inside `tmux` on the loadgen so an SSM disconnect does not kill it.

**Shipping the harness (F8):** `make push-harness` → `tar czf - loadtest automation config analysis/requirements.txt | aws s3 cp - s3://$RESULTS_BUCKET/harness/harness.tgz`. On the loadgen: `make pull-harness` (the same, reversed). Put the git SHA in `harness/VERSION` so `meta.json` can record it.

**Acceptance (Phase 3):** dry run `run_experiment.sh DRY 1 reactive spike` with `C1=10` produces `meta.json, summary.json, raw/k6.csv.gz, asg_timeline.csv, instances.csv, cw/*.csv` · `asg_mode.py static 3 → reactive → reset` leaves `describe-policies` empty · scaler raises desired within 10–20 s of a rate step (check `scaler.csv`) · scaler unit tests green · tag `v0.3`.
**Commits:** `test(load): k6 mix and profiles` · `feat(auto): asg mode switcher` · `feat(auto): asg monitor` · `feat(auto): proactive scaler` · `feat(auto): experiment runner and cloudwatch collector`.

---

## 7. Phase 4 — Experiment run-book

### 7.1 Before every session

```bash
make lab-up                    # terraform apply -var enable_loadgen=true
make push-harness
aws ssm start-session --target $(terraform -chdir=infra/terraform output -raw loadgen_instance_id)
# on loadgen:
sudo su - ec2-user; tmux new -s lab; make pull-harness; source .env.tf
python3 automation/asg_mode.py reset
```
At the end of every session: `make destroy-lab` (laptop) and check in the console that the ASG is at 1 and the loadgen is gone.

### 7.2 Run matrix

`config/experiments.yaml` (single source of truth; the runner and analysis both read it):
```yaml
global:
  instance_type: c6i.large
  work_scale: 1.8          # from T2.7
  c1: 100                  # from E1 (median of 3)
  slo: {critical_p95_ms: 300, error_rate: 0.01}
  warmup_discard_s: 30
experiments:
  E1:  {mode: "static 1", profile: step,  env: {GUESS: 150}, runs: 3}
  E2a: {mode_sweep: [1,2,3,4,5], profile: fixed, env: {FIXED_RPS: "2.0*c1"}, runs: 3}
  E2b: {mode_sweep: [1,2,3,4,5], profile: step,  env: {GUESS: "2.0*c1*N"}, runs: 1}
  E3:  {mode: reactive, profile: spike, runs: 3}
  E4a: {mode: "proactive --prewarm 4 --headroom 0", profile: spike, runs: 1}
  E4b: {mode: "proactive", profile: spike, runs: 1}
  E4c: {mode: "proactive --prewarm 4", profile: spike, runs: 3}
  E5:  {modes: [naive, baked], action: "static 1 -> desired 5", runs: 3}
  E6:  {mode: "static 2", profile: fixed, env: {FIXED_RPS: "3.0*c1"}, variants: [none, ssm_level1, auto_shed], runs: 3}
  E7:  {mode: "static 2", profile: fixed, env: {MIX: match_only, FIXED_RPS: "3.0*c1", HOLD: 3m}, targets: [alb, cloudfront], runs: 3}
```

| Exp | Wall time / run | Runs | Session total | Peak instances | Notes |
|---|---|---|---|---|---|
| E1 | 10 m load + 7 m overhead | 3 | ~50 m | 1 | Before: GIL check (§4.6). After: write `c1` |
| E2a | 5.5 m + ~5 m switch | 5 N × 3 | ~2.5 h | 5 | Loop N inside one session: 1,2,3,4,5,5,4,3,2,1,1,…; alternating the order cancels drift |
| E2b | 10 m + 5 m | 5 | ~75 m | 5 | Gives capacity per N (the linearity panel of F1) |
| E5 | ~6 m | 2 × 3 | ~40 m | 5 | `make tf-apply -var user_data_mode=naive` first; switch back after |
| E3 | 12.5 m + 5 m scale-in + 5 m reset | 3 | ~70 m | 6 | |
| E4 | same | 5 (c×3, a, b) | ~2 h | 6 | Add a×2, b×2 if time remains |
| E6 | 5.5 m + 5 m | 3 × 3 | ~95 m | 2 | Variant via `aws ssm put-parameter` / `AUTO_SHED` (redeploy env through `asg_mode` + instance refresh, or set `AUTO_SHED` per-instance via SSM Run Command and restart the service) |
| E7 | 3.5 m + 5 m | 2 × 3 | ~50 m | 2 | `BASE_URL=https://$CF` for the CloudFront arm |
| **Total** | | | **≈ 11–12 h** across days 4–6 | | Order: E1 → E2 → E5 → E3 → E4 → E6 → E7 |

### 7.3 Per-experiment specifics

**E1 — C1.** Knee = the highest step where critical p95 < 300 ms **and** error rate < 1 % for the whole 55 s hold. C1 = the rate at that step (median of 3 runs). If the knee is outside 80–130 rps, change `WORK_SCALE` and redo E1. Commit `results(E1): single-instance capacity` with `c1` in `experiments.yaml`.

**E2 — required F1.** (a) fixed 2.0·C1 for N = 1..5: expect N=1 saturated (p95 in seconds, timeouts), N=2 at the knee, N≥3 flat. (b) step per N gives capacity(N). Report efficiency = capacity(N) / (N·C1).

**E3 — reactive.** Extract: time from ramp start (t=120 s) to the first *new* healthy instance; SLO-violation seconds; peak p95; instance-minutes. Expected: the first scale-out alarm fires ~3 min after the ramp (3 × 1-min datapoints), and capacity arrives about 4–5 min late.

**E4 — proactive.** Same metrics. Also: extra instance-minutes compared with E3. That is the price of safety, and it is the core trade-off slide.

**E5 — boot time.** No k6. `asg_mode.py static 1` → `set_desired_capacity(5)` with the monitor at 2 s. Per new instance: `launch_time → in_service_ts → first_healthy_ts`. For naive, add the `hsl-boot.log` breakdown (docker install / image pull / container start). Compare with Hotstar's ~90 s window.

**E6 — degradation.** Three variants at 3.0·C1 on 2 instances: none, `degrade_level=1` (set via SSM **before** k6 starts; wait 10 s), `AUTO_SHED=true`. Measure critical p95/errors and `shed_total` (from `/internal/stats`, sampled by the monitor; add `--stats` to `monitor_asg.py` to log it).

**E7 — CDN.** Same load (`match_only`, 3.0·C1, 3 min) against the ALB vs CloudFront. Compare ALB RequestCount (CloudWatch) and origin CPU. Expected: origin requests ≈ 1 per 5 s per edge PoP (Mumbai has several), so tens of requests in total instead of ~54,000.

### 7.4 Run hygiene (non-negotiable)

- Same AMI, instance type, `WORK_SCALE` and harness SHA within one comparison. The runner records them, and the analysis refuses to mix runs with different values unless `--allow-mixed`.
- Never delete an invalid run. Mark it in `docs/runbook.md` → *Run log* and rerun.
- Report median and min–max of 3 runs. Never pick the best one.
- If the loadgen CPU goes above 70 % or k6 reports `dropped_iterations`, the run is invalid. Raise `maxVUs` or use c6i.2xlarge for the loadgen.

**Run log line format** (`docs/runbook.md`):
`2026-11-18 10:42 UTC | E3 run2 | valid | ami-0abc sha a1b2c3d ws 1.8 c1 100 | note: none`

**Acceptance (Phase 4):** every run folder complete · 3 runs where required · C1 and the knee in `experiments.yaml` · raw synced to S3, `summary.json` committed · each commit `results(EX): …` contains a 5-line `summary.md` (what, numbers, surprise, validity, next).

---

## 8. Phase 5 — Analysis, plots and cost model

### 8.1 Data contracts

**`meta.json`** (written by the runner)
```json
{"exp":"E3","run":2,"valid":true,"mode":"reactive","profile":"spike",
 "k6_start_utc":"2026-11-18T10:42:05Z","k6_end_utc":"2026-11-18T10:54:35Z",
 "c1":100,"work_scale":1.8,"instance_type":"c6i.large","ami_id":"ami-0abc","image":"ghcr.io/org/streamlite:a1b2c3d",
 "harness_sha":"a1b2c3d","region":"ap-south-1","asg_config":{...},"scaler_args":null,
 "events_s":{"ramp":[120,210],"bursts":[[300,330],[420,450],[540,570]]},
 "validity":{"dropped_iterations":0,"loadgen_cpu_max":41.2,"http_429":0},"notes":""}
```

**`summary.json`** (written by `parse_k6.py`, committed)
```json
{"exp":"E3","run":2,"duration_s":750,"requests":198340,
 "critical":{"p50_ms":22,"p95_ms":1840,"p99_ms":4950,"error_rate":0.031},
 "slo_violation_s":214,"peak_p95_ms":4870,
 "time_to_first_new_instance_s":268,"instance_minutes":41.5,"peak_instances":6,
 "shed_total":null,"throughput_rps_max":412}
```

**Metric definitions** (put these in the report verbatim):
- *Per-second buckets*: requests grouped by `floor(ts_end)` relative to `k6_start`; the first `warmup_discard_s` are dropped for fixed/step only (never for spike, where the start *is* the test).
- *SLO-violation second*: a bucket with ≥ 10 critical requests where critical p95 > 300 ms **or** critical error rate > 1 %.
- *Error*: `http_req_failed = 1` (status ≥ 400, timeout after 5 s, or connection error).
- *Time to first new instance*: first `asg_timeline.ts` where `healthy_targets > baseline` minus the ramp start (k6_start + 120 s).
- *Instance-minutes*: ∫ (in_service + pending) dt over [k6_start, k6_end + 300 s]. This is billing-relevant: you pay for pending instances too.
- *Capacity (E2b)*: highest step rate meeting the SLO.

### 8.2 `fake_run.py` (F14)

Generates `results/FAKE_E3/run1/…` with the exact schemas: a k6 CSV with plausible latency (lognormal, inflating when rate > N·C1), `asg_timeline.csv` with a delayed staircase, `instances.csv`, `meta.json`. Roles B and D build everything against this on days 2–4. **Fake folders are never committed** (`results/FAKE_*` in `.gitignore`).

### 8.3 `parse_k6.py`

- `pandas.read_csv(path, compression="gzip", chunksize=1_000_000, usecols=["metric_name","timestamp","metric_value","extra_tags","name","status"])`. Keep `metric_name ∈ {http_req_duration, http_req_failed}`. Parse `class` out of `extra_tags` (`class=critical&run_id=…`).
- Join duration and failed rows on (timestamp, name, row order). Simpler: compute the error rate from the `http_req_failed` rows and latency from the `http_req_duration` rows separately, then merge per-second aggregates.
- Per run, write `aggregates.parquet` with one row per (second, class): `count, p50, p95, p99, err_rate, rps`.
- Then `summary.json` per the definitions above. `parse_k6.py --all` walks `results/E*/run*/`. It is idempotent and skips folders whose `summary.json` is newer than the raw data.
- Expected size: ~300 k requests × ~12 metric rows ≈ 3–4 M rows per spike run, ~40–60 MB gzipped. Chunked parsing keeps memory < 1 GB.

### 8.4 Figures (`make_plots.py`, 150 dpi PNG + SVG, consistent palette, every axis with units)

| Fig | Content | Key details |
|---|---|---|
| **F1 (required)** | Panel A: critical p50/p95/p99 (ms, log y) vs N at fixed 2·C1, SLO line at 300 ms, median dot with min–max whisker. Panel B: capacity at SLO vs N, with dashed ideal N·C1 | Caption states C1 and N runs |
| F2 | Match-day timeline: p95 (left, log) + in-service count (right, step) for reactive vs proactive (c); shade ramp and bursts | One run each (the median run by SLO-violation seconds) |
| F3 | SLO-violation seconds and error rate per strategy (E3, E4a/b/c) with min–max whiskers | |
| F4 | Time-to-ready strip plot: naive vs baked, split into launch→InService→healthy | 90 s reference line |
| F5 | Critical p95 and shed count: none vs degrade vs auto-shed | |
| F6 | Origin request count (log) and client p95: ALB vs CloudFront | |
| F7 | Cost per 4-h match per strategy, and the instance count needed for 10.3M/18.6M/25.3M/59M | Assumptions in a footer |

Caption template: *"F2 — Match-day spike, reactive vs proactive (c). Reactive capacity arrives 4.5 min after the ramp; proactive keeps p95 < 300 ms throughout at +38 % instance-minutes. N = 3 runs, median run shown. c6i.large, C1 = 100 rps."*

### 8.5 Cost model (`cost_model.py`, `config/model.yaml`, `config/prices.yaml`)

`prices.yaml` (filled in by a human from the AWS Pricing Calculator; the code never contains a price):
```yaml
retrieved: 2026-11-15
source: "https://calculator.aws/#/estimate?id=…"
region: ap-south-1
ec2_on_demand_usd_per_h: {c6i.large: null, c6i.xlarge: null}
spot_discount_pct: {c6i.large: null}        # observed range from the Spot pricing history
alb_usd_per_h: null
alb_lcu_usd_per_h: null
public_ipv4_usd_per_h: 0.005
cloudfront_usd_per_10k_https_requests_india: null
```
`model.yaml`:
```yaml
viewers_per_rps: 25          # 25.3M concurrent vs ~1M rps (2019) — approximate; sensitivity 10..50
planning_utilisation: 0.8
peaks: {ipl_2019: 10.3e6, ipl_2019_final: 18.6e6, wc_2019: 25.3e6, wc_2023_final: 59e6}
match_hours: 4
spot_shares: [0.0, 0.35, 0.70]   # 0.70 is an unverified claim being tested
hulk: {vcpus: 108000, test_hours: 1}
```
Formulas (the script prints every intermediate value):
```
viewers_per_instance = C1 × planning_utilisation × viewers_per_rps        # e.g. 100×0.8×25 = 2,000
instances(peak)      = ceil(peak / viewers_per_instance)                   # 59M → 29,500
strategy_cost_match  = measured instance-minutes(spike run) / spike_minutes × match_minutes × price/60   (scaled per strategy)
always_on_cost_24h   = instances(peak) × 24 × price
spot_cost            = cost × (1 − spot_share × spot_discount)
hulk_cost            = vcpus × hours × (price_per_instance_h / vcpus_per_instance)
```
Output: `results/E8/summary.json` + table in markdown + F7. Sensitivity table: `viewers_per_rps ∈ {10, 25, 50}` × `spot_share ∈ {0, 0.35, 0.7}`. Every table row lists its assumptions (§8 "out of scope": CDN/egress, databases, caches, k8s control plane, support, people).

### 8.6 `export_results.py` → `web/data/results.json`

```json
{"generated_utc":"…","c1":100,"instance_type":"c6i.large",
 "key_numbers":[{"label":"Single-instance capacity (C1)","value":"100 rps","exp":"E1"}, …],
 "figures":[{"id":"F1","title":"…","png":"img/F1.png","caption":"…"}, …],
 "series":{"F1":{"n":[1,2,3,4,5],"p95_ms":[…],"p95_min":[…],"p95_max":[…],"capacity":[…]},
           "F2":{"t":[…],"reactive_p95":[…],"reactive_n":[…],"proactive_p95":[…],"proactive_n":[…]}},
 "cost":{"price_c6i_large":…,"viewers_per_instance":2000,"peaks":{…}}}
```
`make analyze` = parse → plots → cost → export, and it finishes in < 1 min from committed summaries (the per-run `aggregates.parquet` is regenerated from S3 raw data only with `make analyze-full`).

**Acceptance (Phase 5):** `make analyze` < 1 min · F1 shows the knee and states C1 · every figure has units, N runs and a one-sentence takeaway · cost tables show their assumptions.
**Commits:** `feat(analysis): k6 parser and aggregates` · `feat(analysis): figures F1-F6` · `feat(analysis): cost model and F7`.

---

## 9. Phase 6 — Dashboard on the live URL

Static `web/` → S3 → CloudFront default behaviour. No build step. Chart.js pinned from cdnjs (e.g. `chart.js/4.4.1/chart.umd.min.js`).

### 9.1 Page layout (single page, anchor nav, phone-first)

1. **Header** — "Hotstar Scale Lab", one-paragraph problem statement, links to repo/report.
2. **Case facts** — peak timeline chart (10.3M → 18.6M → 25.3M → 59M), each with a badge `official`/`secondary` linked to `sources.md`; the 61M vs 59M note.
3. **Architecture** — `img/architecture.svg` (same as report Figure 1), plus a small table: Hotstar 2019 (EC2/ASG) vs 2023 (EKS, Envoy, split CDN domains) vs our replica.
4. **Results** — key-number tiles, then F1–F7 (Chart.js for F1 and F2 from `series`, PNGs for the rest) with captions.
5. **Live panel** — polls `/api/v1/whoami` every 1 s: current instance id/AZ, a per-instance hit counter (bars), degrade level, version. Stops polling when the tab is hidden (`visibilitychange`).
6. **Mini burst test (P1)** — button sends 100 GET `/api/v1/recommendations` spread over 5 s (20 req/s, at the rate limit); plots latency per request coloured by instance. Disabled for 10 s after a click. Handles 429 gracefully ("rate-limited — this protects the demo").
7. **Cost calculator (P1)** — inputs: concurrent viewers (slider 1M–60M, log), Spot share (0/35/70 %), viewers-per-rps (10–50). Outputs: instances, $/h, $/4-h match. Uses `results.json.cost`. Shows the formula below the numbers.
8. **Limitations** — the five bullets from PDF §8.1.

### 9.2 Behaviour rules

- `fetch("data/results.json")` fails or has `pending:true` ⇒ result sections show "Results pending — experiments run on <date>" and the page still works.
- No secrets in `web/` (CI greps for `X-Load-Test` and the token pattern).
- Works on a 360 px wide screen; no horizontal scroll; charts `maintainAspectRatio:false` inside fixed-height containers.
- Cache: `index.html` `Cache-Control: no-cache`; other assets `max-age=300` (set via `aws s3 sync --cache-control`), and invalidate `/*` on every publish.

**Acceptance (Phase 6):** loads in < 3 s on CloudFront (Lighthouse mobile) · zero console errors · works with `results.json` missing · tested on a real phone on mobile data.
**Commits:** `feat(web): dashboard skeleton and case facts` · `feat(web): results charts` · `feat(web): live panel and burst test` · `feat(web): cost calculator`.

---

## 10. Phase 7 — Report, README and viva

### 10.1 Writing assignments

| Report section | Pages | Writer | Reviewer | Can start |
|---|---|---|---|---|
| 1 Introduction | 1 | D | A | Day 1 |
| 2 Case study (2019 EC2, 2023 EKS, degradation, HULK) | 2–3 | D | B | Day 1 |
| 3 Analysis (problem decomposition; why standard ASG failed) | 1–2 | A | D | Day 2 |
| 4 Exercise design (H1–H6, StreamLite, infra, profiles, SLO, metric definitions §8.1) | 2 | C | A | Day 3 |
| 5 Results (E1–E7, F1–F6, tables, 3-run stats) | 3–4 | C + D | B | Day 5 |
| 6 Cost analysis (E8, F7, sensitivity, out-of-scope) | 1 | D | C | Day 5 |
| 7 Discussion (lessons, threats to validity, what we'd do at real scale) | 1 | all | – | Day 6 |
| 8 Team and process (roles, commit stats from `git shortlog -sn`, progress) | 0.5 | A | – | Day 7 |
| References + appendix (sources with confidence, repro steps) | 1 | D | – | Day 7 |

Each result subsection uses the same pattern: **Hypothesis → Setup → Result (figure + numbers) → Interpretation → Link to Hotstar.**

Threats to validity (pre-write them): same-region loadgen; tiny scale; synthetic CPU model; round-robin ALB; CloudWatch 1-min granularity; 3 runs per arm; single instance type; 25 viewers/rps is a derived ratio.

### 10.2 `docs/progress.md` (the professor reads this weekly)

```markdown
## Week 3 (17–23 Nov 2026)
- Done: live URL (v0.2) https://dxxxx.cloudfront.net — PR #21, #24; harness (v0.3) PR #30
- Results: C1 = 100 rps (E1, 3 runs), F1 draft
- Blockers: vCPU quota granted at 16 (requested 32) → N sweep capped at 5
- Next: E3/E4, dashboard charts
```

### 10.3 Viva slides (10)

1. Problem: a 1M users/min wall in ~90 s; peaks timeline.
2. What Hotstar did (2019 EC2 → 2023 EKS; pre-warm + custom scaler; degradation; HULK).
3. Our replica: architecture figure; what maps to what (PDF §1.3 table).
4. StreamLite + method: CPU model, open-model load, SLO, 3 runs.
5. **F1: response time vs instance count** (the required plot).
6. F2/F3: reactive vs proactive on match day.
7. F4: baked vs naive boot; F5: degradation.
8. F6: CDN offload; F7: cost and extrapolation.
9. Limitations and what breaks at 59M.
10. Live demo: dashboard → live panel → burst test → (optional) flip degrade level via SSM.

Everyone rehearses the cheat-sheet in PDF §7.3, plus: *"Why not AWS predictive scaling / warm pools / scheduled actions?"* (predictive needs 24 h+ of history and ignores one-off events; scheduled actions are the AWS-native version of our pre-warm (E4d); warm pools cut boot time like baked AMIs) and *"Why is the loadgen in the same region?"*

---

## 11. Makefile reference

| Target | Does |
|---|---|
| `doctor` | `scripts/doctor.sh` |
| `dev` | `uvicorn main:app --reload --app-dir app` with `LOADTEST_TOKEN=local` |
| `test` / `lint` | `pytest app/tests automation/tests` / `ruff check . && ruff format --check . && terraform fmt -check -recursive infra` |
| `image` | `docker build -f app/Dockerfile --build-arg GIT_SHA=$(SHA) -t streamlite:$(SHA) .` |
| `calibrate` | runs `scripts/calibrate.py` in the container |
| `tf-init` / `tf-plan` / `tf-apply` | terraform in `infra/terraform`, `-backend-config=.backend.hcl` |
| `ami` | Packer build → `ami.auto.tfvars` |
| `env` | terraform outputs → `.env.tf` |
| `publish-site` | `s3 sync web/` + CloudFront invalidation |
| `smoke` | `scripts/smoke.sh` |
| `lab-up` | `tf-apply` with `enable_loadgen=true` |
| `destroy-lab` | `asg_mode.py reset --no-wait` + `tf-apply enable_loadgen=false`; prints remaining EC2 count |
| `push-harness` / `pull-harness` | §6.8 |
| `exp EXP=E3 RUN=1` | runs the line for that exp from `experiments.yaml` (on loadgen) |
| `results-pull` | `aws s3 sync s3://$BUCKET/results/ results/ --exclude "*/raw/*"` (add `RAW=1` for raw) |
| `analyze` / `analyze-full` | §8.6 |
| `destroy-all` | **after viva only**: `terraform destroy`, deregister AMIs + delete snapshots (asks for confirmation) |

---

## 12. CI/CD

**`.github/workflows/ci.yml`** (on PR and push to main):
- `python`: setup 3.12 → `pip install -r app/requirements-dev.txt` → `ruff check` → `pytest -m "not slow"`.
- `terraform`: `terraform fmt -check -recursive` → `terraform init -backend=false` → `terraform validate`.
- `packer`: `packer fmt -check` + `packer init` + `packer validate -syntax-only`.
- `k6`: `docker run --rm -v $PWD/loadtest:/s grafana/k6 inspect /s/k6/spike.js` (catches JS errors).
- `shell`: `shellcheck automation/*.sh scripts/*.sh infra/packer/provision.sh`.
- `secrets`: GitHub secret scanning + push protection on (repo settings); also `gitleaks` action.

**`.github/workflows/docker.yml`** (push to main touching `app/**` or `web/**`): `permissions: packages: write, contents: read` → `docker/login-action` with `GITHUB_TOKEN` → `docker/build-push-action` tags `ghcr.io/${{ github.repository_owner }}/streamlite:${{ github.sha short }}` and `:latest`. After the first push, set the package visibility to **public** (once, in GitHub UI) so instances pull without credentials.

---

## 13. Cost estimate and budget guardrails

Fill in exact numbers from the calculator in `prices.yaml`. The orders of magnitude below are only for planning.

| Item | When it runs | Rough cost |
|---|---|---|
| Demo stack: ALB (~$0.02–0.03/h + LCU) + 1 × c6i.large (~$0.08–0.10/h) + public IPv4 (ALB ×3 + instance ×1 = 4 × $0.005/h) | always on until teardown | ~$3–4 / day → ~$25 for a week. Use `instance_type=t3.small` for the idle demo if the budget is tight |
| Experiments: avg ~3 × c6i.large + c6i.xlarge loadgen, ~12 h | days 4–6 | ~$5–8 |
| Packer builds (few minutes each), AMI snapshots (8 GB × few) | | < $1 |
| CloudFront, S3, SSM, CloudWatch GetMetricData | | ≈ $0–1 (free-tier scale) |
| **Total campaign** | | **≈ $30–40** incl. one week of the demo stack |

Guardrails: budget alerts · `asg_max ≤ 6` validation in TF and in code · loadgen `count` toggle · `destroy-lab` at the end of every session (add it to the session checklist) · no NAT gateways · public rate limit · check Billing → Bills daily during days 4–6.

---

## 14. Troubleshooting run-book

| Symptom | Likely cause | Fix |
|---|---|---|
| Targets stay `unhealthy` | app not listening on 8000, SG missing alb→app rule, or env file missing | `aws ssm start-session` → `systemctl status streamlite`, `journalctl -u streamlite -n 50`, `curl localhost:8000/healthz` |
| Instances cycle (launch → terminate) | ELB health check fails before the grace period ends | naive mode needs grace 240 s; check `hsl-boot.log` |
| `VcpuLimitExceeded` in ASG activities | quota | `aws service-quotas get-service-quota --service-code ec2 --quota-code L-1216C47A`; cap N |
| Whoami always the same instance | client keep-alive pins one connection; the ALB balances per request, but the browser reuses the connection to CloudFront, which reuses it to the ALB | expected for one browser; the burst test and k6 spread it; explain in the viva |
| `docker pull` 403/denied on instances | GHCR package still private | make it public |
| CloudFront 502 | ALB has no healthy targets, or the origin protocol is wrong | origin must be `http-only` on port 80 |
| CloudFront 403 on `/` | OAC bucket policy missing, or `default_root_object` not set | re-apply `site.tf` |
| Scaler logs `rps=0` | app-sg lacks 8000 from loadgen-sg, or the scaler uses public IPs | use `PrivateIpAddress` from `describe_instances` |
| k6 `dropped_iterations` > 0 | `maxVUs` too low (latency × rate > VUs) | `maxVUs = rate × timeout(5 s)` = 420 × 5 ≈ 2100 → set 2500 |
| p95 explodes but CPU only ~55 % | GIL contention | `WEB_CONCURRENCY=2` (§4.6) |
| `terraform apply` wants to change min/max/desired | `ignore_changes` missing | F1 |
| State lock stuck | someone's apply crashed | `terraform force-unlock <id>` only after asking the team |

---

## 15. Appendix

### 15.1 Create the issues from §2.1

Save the backlog as `docs/backlog.tsv` (`id<TAB>title<TAB>role<TAB>priority<TAB>est`), then:
```bash
gh label create P0 -c B60205; gh label create P1 -c FBCA04; gh label create P2 -c 0E8A16
for r in A B C D; do gh label create "role:$r"; done
tail -n +2 docs/backlog.tsv | while IFS=$'\t' read -r id title role prio est; do
  gh issue create --title "$id $title" --label "$prio" --label "role:$role" \
    --body "Est: ${est}h. Spec: docs/IMPLEMENTATION_PLAN_DETAILED.md (search $id). Acceptance: see the phase acceptance block."
done
```

### 15.2 PR template (`.github/pull_request_template.md`)

```markdown
Closes #
## What
## How verified (paste command output / screenshot)
## Acceptance checks from the plan
- [ ]
## Cost impact (new AWS resources? always-on?)
## Docs/runbook updated?  [ ] yes  [ ] n/a
```

### 15.3 Session checklist (print it; tick it every lab session)

```
[ ] AWS_PROFILE=hsl, region ap-south-1          [ ] Billing page checked, < budget
[ ] make lab-up && make push-harness           [ ] tmux on loadgen, pull-harness, source .env.tf
[ ] asg_mode.py reset, 5 min wait              [ ] experiments.yaml c1/work_scale correct
[ ] run(s) — log each in runbook.md            [ ] results synced to S3
[ ] make destroy-lab                           [ ] console: ASG desired = 1, no loadgen instance
```

### 15.4 Plan B (AWS unavailable) — unchanged from PDF §8.3, made concrete

- Live URL: same container on Render/Fly.io (free tier), with dashboard + live panel.
- E1/E2/E6 locally: `docker compose up --scale app=N` behind nginx, pinning each replica to its own CPU (`cpus: "1.0"` per service) so N actually adds capacity.
- E3/E4 analogue: `kind` cluster + metrics-server; HPA on CPU 50 % vs a 30-line proactive script that `kubectl scale`s from `/internal/stats`. The same k6 profiles and analysis code (only `monitor` swaps to a `kubectl get pods` poller with the same CSV schema).
- The cost model stays calculator-based. The report states clearly that autoscaling was simulated on containers.

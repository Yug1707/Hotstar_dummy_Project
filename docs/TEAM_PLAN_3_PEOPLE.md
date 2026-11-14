# Hotstar Scale Lab — 3-Person Team Plan

> Companion to `IMPLEMENTATION_PLAN_DETAILED.md` (task IDs `T*.*` and section numbers `§` refer to it).
> This file decides **who owns what, who commits what, in which order, after whose PR, and who reviews it.**
> Write your names in the table below and keep the letters A / B / C everywhere else.

| Letter | Role | Name |
|---|---|---|
| **A** | Infra & Platform + Case study + Cost | _________ |
| **B** | App + Dashboard + Analysis/Plots | _________ |
| **C** | Load Lab + Experiments + Report lead | _________ |

---

## 1. Role split

### 1.1 What each person owns

| | A — Infra & Platform | B — App, Dashboard, Analysis | C — Load Lab & Experiments |
|---|---|---|---|
| **Builds** | Terraform (all of it), Packer AMI, CloudFront + S3 site, budgets, smoke test, cost model, cost calculator widget | StreamLite app + tests, Dockerfile, CI, calibration, dashboard, k6 parser, figures F1–F6, `results.json` export | k6 scripts, `asg_mode`, monitor, proactive scaler, runner, CloudWatch collector, fake-data generator, docker-compose |
| **Runs** | E5 (boot time), E7 (CDN) | Calibration (with C) | E1, E2, E3, E4, E6 |
| **Writes (report)** | §2 Case study, §3 Analysis, §6 Cost, §8 Team; README, runbook, architecture; `sources.md` | §4 StreamLite part, all figure captions; assembles the viva slides | §1 Intro, §4 harness/SLO part, §5 Results, §7 Discussion; assembles the final report |
| **Folders (CODEOWNERS)** | `infra/`, `config/prices.yaml`, `config/model.yaml`, `analysis/cost_model.py`, `docs/sources.md`, `docs/runbook.md`, `README.md` | `app/`, `web/`, `scripts/`, `.github/`, `analysis/parse_k6.py`, `analysis/make_plots.py`, `analysis/export_results.py` | `loadtest/`, `automation/`, `config/experiments.yaml`, `analysis/fake_run.py`, `docker-compose.yml`, `results/` |
| **Est. hours** | ~31 h | ~30 h | ~31 h (plus experiment wall-clock) |
| **PRs authored** | 19 | 19 | 18 |
| **Tags cut** | `v0.2` live URL, `v1.0` final | `v0.1` app, `v0.4` results | `v0.3` harness |

Why this split:
- **A** works where the cloud resources are. A also owns the cost model (prices and AWS billing) and the case study (A reads the sources while Terraform applies or CloudFront deploys).
- **B** owns the full path of a number: the app produces it, the parser reads it, the figures plot it, the dashboard shows it. The schemas then stay consistent.
- **C** owns the lab. One person runs most experiments, so the run hygiene is consistent. C is also report lead because the results section is the largest part.

### 1.2 Avoiding merge conflicts (do this in PR #1)

1. **CODEOWNERS** = the folders table above. GitHub auto-requests the owner when someone else touches their files.
2. **Split shared files** so two people never edit the same file:
   - `Makefile` contains only `include make/*.mk`. A owns `make/infra.mk`, B owns `make/app.mk` and `make/analysis.mk`, C owns `make/lab.mk`.
   - Report = one file per section: `docs/report/01-intro.md` … `09-references.md`. Pandoc joins them at the end.
   - `docs/progress.md`: only the **scribe of the day** (§5) commits it.
   - `.gitignore`: A writes it complete in PR #1; later additions go in the PR that needs them.
3. Small PRs (≤ ~300 lines). Run `git pull --rebase origin main` before every push. Squash-merge.
4. **Pair work counts for both people.** When two people build something together (calibration, PR #30), the author adds `Co-authored-by: Name <email>` to the commit message. GitHub then credits both.

---

## 2. Handoffs (the only moments someone waits on someone else)

| # | From → To | What exactly | Needed by | Unblocks | If late, the receiver does… |
|---|---|---|---|---|---|
| H1 | B → A | Public image `ghcr.io/<org>/streamlite:<sha>` (PR #17) | end of Day 2 | Packer AMI (#20) | Build the AMI from a local `docker save`, or start the CloudFront/site work (#21) first |
| H2 | A → C | ASG + target group exist; `make env` writes `.env.tf` (PR #13, #18) | end of Day 2 | asg_mode / monitor tests on real AWS (#22, #25) | Write and unit-test the scripts against a fake boto3 client (`botocore.stub.Stubber`) |
| H3 | C → B | Run-folder schema + synthetic runs (PR #15) | end of Day 2 | k6 parser (#27) | Hand-write a 50-line sample CSV in the same format |
| H4 | A → all | **Live HTTPS URL** + smoke test green (PR #26) | end of Day 3 | calibration, dashboard publishing, dry run | Keep working locally (`make dev`, docker-compose) |
| H5 | B (+C) → A | Calibrated `ITER` table merged → new image (PR #30) | Day 4 midday | AMI rebuild (#31) → every real experiment | – (critical path: B and C pair on it first thing on Day 4) |
| H6 | C → A, B | `c1` written to `config/experiments.yaml` (PR #37) | end of Day 4 | E2–E7, cost model, F1 | Use the dry-run estimate and mark it "provisional" |
| H7 | B → A | `results.json` schema (PR #42) | Day 5 | cost calculator (#50) | Build the calculator against the schema in §8.6 of the detailed plan |
| H8 | C, A → B | Each `results(EX)` PR with `summary.json` | Days 5–6 | final figures (#51) | Plot whatever has landed; mark the rest "pending" |
| H9 | A → B, C | Cost model with measured instance-minutes (PR #49) | Day 6 | F7, results.json cost block, report §6 | – |

**Lab lock.** There is only one ASG, so only one experiment can run at a time. `run_experiment.sh` writes `s3://<results-bucket>/lab.lock` containing `{owner, exp, started}`, refuses to start if the lock exists, and deletes it in its `trap`. A runs E5/E7 only in the slots given in §4.

---

## 3. Master merge sequence — who commits what, after whom

Read it top to bottom. **"After"** = the PR(s) that must be merged before this one can merge. Work on a branch can start earlier; only the *merge* waits. The reviewer is never the author, and the work is spread so each person reviews about 18 PRs.

Branch name = `<type>/<#>-<slug>`, e.g. `feat/11-endpoints`. The commit message (after squash) = the "Commit message" column.

### Day 1 — Setup (gate: `make doctor` green for all 3, quota requested, app skeleton runs locally)

| # | Author | Commit message | Task | After | Reviewer |
|---|---|---|---|---|---|
| 1 | **A** | `chore: repo skeleton, gitignore, licence, codeowners, pr template` | T0.1 | – (direct push, **then** turn on branch protection) | – |
| 2 | B | `chore: make doctor and split makefile` | T0.4 | #1 | C |
| 3 | C | `docs: backlog, issue script and progress log` | T0.7 | #1 | A |
| 4 | A | `infra: terraform versions, s3 backend, variables` | T0.5, T2.1 | #1 | B |
| 5 | B | `feat(app): config, cpu work model and imds` | T1.1 | #2 | C |
| 6 | A | `docs: sources log with week 1 sources` | T0.6 | #1 | C |
| 7 | C | `test(load): k6 lib with traffic mix` | T3.1 | #1 | B |
| 8 | C | `docs(report): introduction draft` | T7.2 | #1 | A |
| – | C | `docs(progress): day 1` (scribe) | – | #1–#8 | any |

Not a commit, but A does it in the first hour: **AWS Budget + vCPU quota request (32)** (T0.3). B starts the branch for #9 the same afternoon.

### Day 2 — App + Terraform core (gate: image on GHCR, `terraform plan` clean, `v0.1`)

| # | Author | Commit message | Task | After | Reviewer |
|---|---|---|---|---|---|
| 9 | B | `feat(app): stats with arrival counting` | T1.2 | #5 | C |
| 10 | A | `infra: network, iam, ssm parameters` | T2.1 | #4 | B |
| 11 | B | `feat(app): endpoints and middleware` | T1.3 | #9 | C |
| 12 | C | `test(load): step, fixed and spike profiles` | T3.2 | #7 | B |
| 13 | A | `infra: alb, asg, launch template and user data` | T2.2 | #10 | C |
| 14 | B | `feat(app): degrade level, auto-shed and rate limit` | T1.4, T1.5 | #11 | A |
| 15 | C | `feat(analysis): fake run generator and run schema` → **H3** | T5.1 | #12 | B |
| 16 | B | `test(app): endpoint, shedding and rate-limit tests` | T1.6 | #14 | C |
| 17 | B | `ci: lint, test, docker build and ghcr push` → **H1**, B tags **`v0.1`** | T1.7 | #16 | A |
| 18 | A | `infra: loadgen, results bucket, budgets and outputs` → **H2** | T2.5 | #13 | C |
| – | A | `docs(progress): day 2` (scribe) | – | | any |

C also builds `docker-compose.yml` locally today to dry-run k6 against #11. It is committed as part of #15's branch or a tiny follow-up (P1).

### Day 3 — Live URL (gate: **HTTPS URL works on a phone**, `v0.2`)

| # | Author | Commit message | Task | After | Reviewer |
|---|---|---|---|---|---|
| 20 | A | `infra: packer baked ami` | T2.3 | #17 (H1) | B |
| 21 | A | `infra: s3 site and cloudfront https front door` | T2.4 | #13 | C |
| 22 | C | `feat(auto): asg mode switcher` | T3.3 | #18 (H2) | A |
| 23 | B | `feat(app): calibration script` | T1.8 | #5 | A |
| 24 | B | `feat(web): dashboard skeleton and case facts` | T6.1 | #6 | C |
| 25 | C | `feat(auto): asg and target monitor` | T3.4 | #22 | A |
| 26 | A | `chore: smoke test; docs: runbook for deploy and teardown` → **H4**, A tags **`v0.2`** | T2.6, T7.1 | #20, #21 | C |
| 27 | B | `feat(analysis): k6 parser and aggregates` | T5.2 | #15 (H3) | A |
| 28 | A | `docs(report): case study draft` | T7.2 | #6 | B |
| – | B | `docs(progress): day 3` (scribe) | – | | any |

Timing tip for A: start `terraform apply` for #21 **before lunch**. CloudFront takes 5–15 min to deploy; read sources for #28 while it does.

### Day 4 — Harness + calibration + E1 (gate: dry run complete, C1 known, `v0.3`)

| # | Author | Commit message | Task | After | Reviewer |
|---|---|---|---|---|---|
| 29 | C | `feat(auto): proactive scaler with unit tests` | T3.5 | #25, #11 | A |
| 30 | B (`Co-authored-by` C) | `perf(app): calibrated work table and work scale` → **H5** | T2.7 | #23, #26 | A |
| 31 | A | `infra: rebuild ami for calibrated image` | T2.3 | #30 | B |
| 32 | C | `feat(auto): experiment runner, cloudwatch collector, harness shipping` | T3.6 | #29, #18 | A |
| 33 | C | `test(load): harness dry run evidence`, C tags **`v0.3`** | T3.7 | #32, #31 | B |
| 34 | B | `feat(web): live whoami panel` | T6.3 | #24, #26 | C |
| 35 | A | `feat(analysis): cost model, prices and model config` | T5.4 | #1 | B |
| 36 | B | `feat(analysis): figures F1-F6 on synthetic data` | T5.3 | #27 | C |
| 37 | C | `results(E1): single-instance capacity` → **H6** (`c1` in experiments.yaml) | T4.1 | #33 | B |
| – | C | `docs(progress): day 4` (scribe) | – | | any |

Day 4 is C's heaviest day. **B and C pair on calibration (#30) at 09:00**, so A can rebuild the AMI (#31) by midday. If #37 slips, E1 moves to the first slot of Day 5 and everything on Day 5 moves down by one slot. A covers by running E5 earlier.

### Day 5 — Experiments I (gate: **F1 from real data**)

Lab slots (lab lock): **09:00–12:30 C: E2** · **12:30–13:30 A: E5** · **13:30–15:00 C: E3** · rest: analysis/writing.

| # | Author | Commit message | Task | After | Reviewer |
|---|---|---|---|---|---|
| 38 | C | `results(E2): latency vs instance count` | T4.2 | #37 | B |
| 39 | A | `results(E5): baked vs naive boot time` | T4.3 | #31, #25 | C |
| 40 | B | `feat(analysis): figure F1 from real E2 data` | T5.3 | #38 | A |
| 41 | C | `results(E3): reactive scaling under match spike` | T4.4 | #37 | A |
| 42 | B | `feat(web): results charts and results.json schema` → **H7** | T6.2 | #36 | A |
| 43 | B | `feat(web): mini burst test` (P1) | T6.4 | #34 | C |
| 44 | C | `docs(report): exercise design section` | T7.2 | #37 | B |
| 45 | A | `docs(report): analysis section, why standard autoscaling failed` | T7.2 | #28 | B |
| – | A | `docs(progress): day 5` (scribe) | – | | any |

### Day 6 — Experiments II + real results on the live site (gate: all P0 experiments done, `v0.4`)

Lab slots: **09:00–11:30 C: E4** · **11:30–13:00 C: E6** · **13:00–14:00 A: E7** · **14:00 A: `make destroy-lab`**.

| # | Author | Commit message | Task | After | Reviewer |
|---|---|---|---|---|---|
| 46 | C | `results(E4): proactive pre-warm and ladder variants` | T4.5 | #41 | A |
| 47 | C | `results(E6): graceful degradation and auto-shed` | T4.6 | #37 | B |
| 48 | A | `results(E7): cdn offload of cacheable api` | T4.7 | #37 | C |
| 49 | A | `feat(analysis): cost model with measured instance-minutes and F7` → **H9** | T5.4 | #35, #46 | B |
| 50 | A | `feat(web): cost calculator` (P1) | T6.5 | #42, #49 | C |
| 51 | B | `feat(analysis): final figures and results export`, then `make publish-site`, B tags **`v0.4`** | T5.3, T5.5 | #46, #47, #48, #49 | C |
| 52 | B | `docs(report): streamlite design and figure captions` | T7.3 | #51 | A |
| – | B | `docs(progress): day 6` (scribe) | – | | any |

### Day 7 — Report and viva (gate: report PDF, slides, 2 rehearsals, `v1.0`)

| # | Author | Commit message | Task | After | Reviewer |
|---|---|---|---|---|---|
| 53 | C | `docs(report): results and discussion` | T7.3 | #51 | A |
| 54 | A | `docs(report): cost analysis, team and process` | T7.3 | #49 | B |
| 55 | A | `docs: final readme, architecture and runbook` | T7.1 | #51 | C |
| 56 | B | `docs(viva): slides and cheat-sheet` | T7.4 | #53 | A |
| 57 | C | `docs(report): assembled final report` | T7.3 | #52, #53, #54 | B |
| – | C | `docs(progress): day 7` (scribe) | – | | any |
| – | **A** | tag **`v1.0`** after #57 is merged | – | #55, #56, #57 | – |

Teardown (T7.5, A) happens **after the viva** and is not a commit. A records it in `runbook.md` in a final PR.

---

## 4. Per-person queues (print your column)

The numbers are PRs from §3, in the order you merge them. `→Hn` = someone is waiting on you.

| Day | A — Infra & Platform | B — App, Dashboard, Analysis | C — Load Lab & Experiments |
|---|---|---|---|
| 1 | #1 skeleton · budget + **quota** · #4 TF backend · #6 sources | #2 doctor · #5 work model · start #9 | #3 backlog · #7 k6 lib · #8 intro draft · *scribe* |
| 2 | #10 network/iam · #13 ALB/ASG · #18 loadgen →H2 · *scribe* | #9 stats · #11 endpoints · #14 degrade/rate-limit · #16 tests · #17 CI →H1 | #12 profiles · #15 fake runs →H3 · local compose dry run |
| 3 | #20 Packer · #21 CloudFront · **#26 live URL →H4** · #28 case study | #23 calibrate script · #24 dashboard · #27 parser · *scribe* | #22 asg_mode · #25 monitor · review A's infra PRs |
| 4 | #31 AMI rebuild · #35 cost model · review C's harness | **09:00 pair with C:** #30 calibration →H5 · #34 live panel · #36 figures (fake) | #29 scaler · #32 runner · #33 dry run · **#37 E1 →H6** · *scribe* |
| 5 | E5 slot 12:30 → #39 · #45 report §3 · *scribe* | #40 F1 real · #42 results charts →H7 · #43 burst test | E2 → #38 · E3 → #41 · #44 report §4 |
| 6 | E7 slot 13:00 → #48 · #49 cost+F7 →H9 · #50 calculator · destroy-lab | #51 final figures + publish · #52 captions · *scribe* | E4 → #46 · E6 → #47 · start results section |
| 7 | #54 report §6/§8 · #55 README · tag v1.0 | #56 slides | #53 results + discussion · #57 final report · *scribe* |

### When you are blocked

| You are | Waiting on | Do this meanwhile (also commit-worthy) |
|---|---|---|
| A | H1 image (Day 2–3) | #21 CloudFront/site, #35 cost model, case study reading |
| B | H4 live URL | dashboard against `make dev`; parser against fake runs |
| C | H2 real ASG | unit tests with `botocore.stub.Stubber`; k6 against docker-compose |
| anyone | a review | review someone else's PR first, then ping. Review SLA = **4 working hours**; if the reviewer is busy, the third person reviews |
| C | lab lock held by A | parse your last run, write `summary.md`, draft report §5 |

---

## 5. Team rhythm

- **Daily stand-up, 10 min, 09:00:** yesterday's merged PR numbers, today's queue, any Hn at risk. Every blocker gets an owner and a time.
- **End-of-day sync, 10 min:** check the day's gate. The **scribe** (Day 1 C, 2 A, 3 B, 4 C, 5 A, 6 B, 7 C) commits `docs(progress): day N` with done PRs, numbers learned, blockers, next.
- **Merge windows:** merge whenever approved, but **never merge infra (A) PRs during a C lab slot**. A changed launch template mid-run invalidates the run.
- **Review checklist:** (1) acceptance check from the detailed plan pasted as evidence; (2) no secrets/tfvars/raw results; (3) runbook updated if behaviour changed; (4) for `results(EX)` PRs: `meta.json` `valid:true` for 3 runs, `summary.md` present.
- **Who may touch AWS:** only A runs `terraform apply`/`destroy`. C (and A in their slots) run `asg_mode.py` / experiments. B uses read-only access (`terraform plan`, CloudWatch console).
- **Session closing:** whoever ran the last lab slot of the day runs `make destroy-lab` and posts a console screenshot (ASG desired 1, no loadgen) in the progress entry.

---

## 6. Commit-history check (what the professor will see)

| | A | B | C |
|---|---|---|---|
| Feature/infra/results PRs | 19 | 19 | 18 |
| Progress (scribe) commits | 2 | 2 | 3 |
| Days with ≥ 1 merged PR | 7/7 | 7/7 | 7/7 |
| Reviews given (approx.) | 18 | 19 | 18 |
| Tags | v0.2, v1.0 | v0.1, v0.4 | v0.3 |

Before the viva, run `git shortlog -sn --no-merges` and `gh pr list --state merged --json author,number --limit 100 | jq 'group_by(.author.login) | map({a: .[0].author.login, n: length})'`. Put the output in report §8 (Team and process).

### Cut list, if the schedule slips (in this order; never cut a P0)

1. #43 burst test, #50 cost calculator (P1 web) → both skipped without breaking anything.
2. E4 a/b down to 1 run each (already the minimum); E6 down to 2 variants (none vs SSM level 1).
3. E7 (#48) → described in the report as "designed, not run", with the reason.
4. E5 (#39) → keep only baked ×3 + naive ×1.

If any cut happens, the person who owned it says so in that day's progress entry, and C lists it in report §7 (limitations).

# harness/: Phase 3 load-test harness and lab automation

Everything for Phase 3 lives in this one folder: the k6 traffic profiles, the scaling-mode switcher,
the ASG monitor, the proactive scaler, the CloudWatch collector, the experiment runner and the
experiment matrix. Owner: **C**. The repo-wide hooks are a single include line in `make/lab.mk` and a
`s3:DeleteObject` permission on `lab.lock` in `infra/iam.tf`.

| File | What | Plan |
|---|---|---|
| `lib.js` | traffic mix (55 % heartbeat, 10 % playback, 20 % match state, 15 % reco), tags, token header, open model, `http_429` counter, summary writer | §6.1 |
| `step.js` / `fixed.js` / `spike.js` | E1+E2b steps · E2a/E6/E7 fixed rate · E3/E4 match-day spike (12 m 30 s, peak 2.8 × C1 for the 4-instance cap) | §6.2 |
| `common.py` | env and `.env.tf`, boto3 clients with adaptive retry, `group_state`, `wait_stable`, `/internal/stats` fetch | §6.3 |
| `asg_mode.py` | `static N`, `reactive`, `proactive`, `scheduled AT N`, `desired N`, `reset`, plus a self-check | §6.4 |
| `monitor_asg.py` | `asg_timeline.csv`, `instances.csv`, and `stats.csv` with `--stats` | §6.5 |
| `proactive_scaler.py` | pre-warm floor plus a ladder on arrival rps; scales out at once, scales in one step per 5 min | §6.6 |
| `collect_cw.py` | 14 CloudWatch series → `cw/*.csv` | §6.7 |
| `run_experiment.sh` | one run end to end; a `trap` always resets the ASG, restores SSM and AUTO_SHED, syncs to S3 and releases the lock | §6.8 |
| `boot_test.sh` | E5: scale 1 → 4 with the monitor at 2 s, then collect `/var/log/hsl-boot.log` over SSM | §7.3 |
| `fleet.py` | SSM Run Command: `auto-shed on/off` (E6), `boot-logs` (E5) | §7.3 |
| `lab_lock.py` | `s3://<results>/lab.lock`, taken with a conditional write; only one experiment runs at a time | TEAM §1 |
| `sample_cpu.py` | loadgen CPU % for the validity check (< 70 %) | §6.8 |
| `experiments.yaml` | the run matrix (single source of truth), `c1`, `work_scale`, SLO | §7.2 |
| `exp_config.py`, `exp.sh` | `exp.sh E2a 1 3` → resolves the yaml entry and runs it | §7.2 |
| `run_campaign.sh`, `campaign_example.txt` | runs listed back to back (inside tmux) | §6.8 |
| `labfuncs.sh` | shell helpers shared by the runners | |
| `tests/` | 41 unit tests with fake AWS clients (scaler, modes, stability wait, monitor, config, CloudWatch, lock) | §6.6 |

## Checks that need no AWS account

```bash
make harness-test     # 41 unit tests
make harness-lint     # ruff, shellcheck, k6 inspect of all three profiles
make dev &            # StreamLite on :8000, then:
make dry-local        # the full runner against it: spike at C1=10, 10x faster (~80 s) → results/FAKE_LOCAL/
```
`--local URL` skips everything that touches AWS: ASG, lock, monitor, CloudWatch and S3. The k6
profile, the CSV output, `meta.json`, `profile.json`, the loadgen CPU sampler and the validity
checks still run for real.

## On the loadgen (each lab session)

From the laptop:
```bash
make lab-up && make push-harness && make loadgen-shell
```
Then on the loadgen:
```bash
sudo su - ec2-user && tmux new -s lab        # SSM disconnects must not kill a run
cd /opt/hsl && aws s3 cp "s3://$RESULTS_BUCKET/harness/harness.tgz" - | tar xz
python3.11 harness/asg_mode.py reset          # then the runner enforces a 5 min cool-down
harness/run_experiment.sh DRY 1 reactive spike C1=10    # T3.7 acceptance dry run
harness/exp.sh E1 1                           # from experiments.yaml
harness/run_campaign.sh harness/campaign_example.txt
```
`/etc/profile.d/hsl.sh` (written by the loadgen user_data) exports `ASG_NAME`, `TG_ARN`, the ARN
suffixes, `ALB_DNS`, `CLOUDFRONT_URL`, `RESULTS_BUCKET` and `PYTHON=python3.11`, so nothing needs Terraform.
At the end of the session, run `make destroy-lab` on the laptop.

## What one run produces: `results/<EXP>/run<N>/`

| File | From |
|---|---|
| `meta.json` | runner: plan §8.1 schema, plus `app_version`, `speed`, `k6_exit_code` and `validity` |
| `raw/k6.csv.gz` | k6 (`K6_CSV_TIME_FORMAT=unix_milli`, tags `class`, `name`, `run_id`); stays in S3, git-ignored |
| `k6_summary.json`, `profile.json`, `k6.log` | k6 `handleSummary` (stages, event markers / step windows) |
| `asg_timeline.csv`, `instances.csv`, `stats.csv` | `monitor_asg.py --stats` |
| `scaler.csv` | `proactive_scaler.py` (E4 only) |
| `cw/*.csv` | `collect_cw.py` |
| `loadgen_cpu.csv`, `runner.log` | runner |

`summary.json` is written later by `analysis/parse_k6.py` (Phase 5), not by the runner.

**Validity.** A run is `valid: true` only if:
- `dropped_iterations == 0`;
- `http_429 == 0`, meaning the token bypassed the rate limit;
- loadgen CPU stays below 70 %;
- k6 exits with 0 or 99 (99 means a threshold was crossed, which is a result, not an error).

An invalid run is kept, never deleted. Log it in `docs/runbook.md` and run it again.

## Experiment cheat sheet

| Run | Command |
|---|---|
| E1 | `exp.sh E1 1` (then `2`, `3`); put the median knee into `experiments.yaml` → `global.c1` |
| E2a / E2b | `exp.sh E2a RUN N` with N = 1..4; alternate the order (see `campaign_example.txt`) |
| E3 | `exp.sh E3 RUN` |
| E4 | `exp.sh E4c RUN`, `exp.sh E4a 1`, `exp.sh E4b 1`, optional `exp.sh E4d 1` (AWS scheduled action) |
| E5 | laptop: `make tf-apply MODE=naive`; loadgen: `exp.sh E5 RUN naive`; then `make tf-apply`, then `exp.sh E5 RUN baked` |
| E6 | `exp.sh E6 RUN none`, `… ssm_level1`, `… auto_shed` (baked AMI only: it restarts the service) |
| E7 | `exp.sh E7 RUN alb`, `exp.sh E7 RUN cloudfront` |

Options of `run_experiment.sh`: `--force`, `--target alb|cloudfront`, `--degrade 0|1`, `--auto-shed`,
`--observe S`, `--no-cooldown`, `--no-cw`, `--no-s3`, `--no-lock`, `--local URL`. Run it with `-h`
for the full help. `make lab-status` shows who holds the lock. `make lab-unlock` removes a stale lock
after it asks you to confirm.

## Phase 3 acceptance (tag `v0.3`, needs the live stack)

- [ ] `run_experiment.sh DRY 1 reactive spike C1=10` produces `meta.json`, `raw/k6.csv.gz`, `asg_timeline.csv`, `instances.csv`, `cw/*.csv`
- [ ] `asg_mode.py static 3`, then `reactive`, then `reset` leaves `aws autoscaling describe-policies` empty
- [ ] `scaler.csv` shows desired rising within 10–20 s of a rate step (E4b dry run)
- [x] scaler unit tests green (`make harness-test`)
- [x] local dry run green (`make dry-local`)

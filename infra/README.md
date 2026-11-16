# infra/ — Phase 2: infrastructure and the live URL

Everything for Phase 2 is in this one flat folder. It is the Terraform root module (all `*.tf`)
and also holds the Packer template, the boot scripts and the deploy and teardown scripts.
Owner: **A**. Only A runs `tf-apply`, `ami` and `destroy-*`; everyone else may run `tf-plan`
and the offline checks.

**AWS Free plan (USD 118 credit).** Free-plan accounts may only launch free-tier-eligible instance
types; `c6i.large` fails with `InvalidParameterCombination: The specified instance type is not eligible
for Free Tier`. Everything therefore runs on **c7i-flex.large** (2 vCPU, 4 GiB, x86_64, eligible), the
fleet is capped at **4** app servers (8 vCPU + 2 for the loadgen), and the budget alarm tracks gross
usage (`include_credit = false`), because the credit keeps the net bill at $0. `deploy_aws.sh` checks
which types the account may launch and writes `instance.auto.tfvars`; `APP_TYPE=…` overrides it.

```
CloudFront (HTTPS, PriceClass_200)
 ├─ default (*)       → S3 site bucket (private, OAC)      cached
 ├─ /api/v1/match/*   → ALB                                cached, max-age=5 from origin (E7)
 └─ /api/*            → ALB                                not cached, viewer headers forwarded
ALB :80 ── rule 1: /internal/* → 404 ──► target group :8000 (/healthz) ──► ASG c7i-flex.large × 0..4
loadgen c7i-flex.large (lab sessions only) ── :8000 /internal/stats on private IPs ──► app instances
```

| File | What |
|---|---|
| `versions.tf` | Terraform ≥ 1.10, providers, S3 backend with lock file (F7), default tags |
| `variables.tf` | all inputs; `asg_max ≤ 4` validation, Free-plan instance types |
| `network.tf` | default VPC/subnets (ASG + loadgen only in AZs that offer the instance type); SGs `hsl-alb-sg`, `hsl-app-sg`, `hsl-loadgen-sg`; **no port 22** |
| `iam.tf` | app role (read `/streamlite/*`), loadgen role (drive the ASG, SSM params, results bucket) |
| `ssm.tf` | `/streamlite/degrade_level` (TF ignores value changes), `/streamlite/loadtest_token` SecureString (F10) |
| `alb.tf` | ALB, target group (round robin, `/healthz` every 5 s), listener, `/internal/*` → 404 (F2) |
| `asg.tf` | launch template (IMDSv2, hop limit 2 (F16)), ASG with `ignore_changes` on capacity (F1), no scaling policy |
| `user_data_baked.sh.tftpl` | baked AMI boot: write `/etc/streamlite.env`, then start the disabled unit (F9) |
| `user_data_naive.sh.tftpl` | E5 baseline: install Docker and pull the image at boot |
| `user_data_loadgen.sh.tftpl` | k6 (pinned), Python 3.11, fd/port limits, `/etc/profile.d/hsl.sh` with the stack names |
| `site.tf` | private site bucket + OAC + bucket policy for this distribution only (F6) |
| `cloudfront.tf` | distribution with two origins and three behaviours (F3) |
| `loadgen.tf` | results bucket (`harness/` expires after 30 d) + loadgen instance (`enable_loadgen`) |
| `budgets.tf` | $25 monthly budget, 80 % actual / 100 % forecast (only if `alert_emails` is set) |
| `outputs.tf` | names and ARNs → `make env` → `.env.tf` |
| `streamlite.pkr.hcl`, `provision.sh` | Packer baked AMI: Docker + pre-pulled image + disabled unit; SSH only from the builder's IP (F17) |
| `smoke.sh` | Phase 2 acceptance checks |
| `reset_asg.sh` | ASG back to idle (no policies or scheduled actions, 1/6/1) |
| `hsl.tftest.hcl` | offline `terraform test` against mock providers: no AWS account and no cost |
| `terraform.tfvars.example`, `backend.hcl.example` | copy these and fill them in; the copies are git-ignored |

## Checks that need no AWS account

```bash
make tf-validate   # terraform fmt -check + validate
make tf-test       # 6 terraform tests against mock providers
make infra-lint    # + packer fmt/validate + shellcheck
```

## One-time setup (A)

1. Finish T0.2/T0.3/T0.5 (profile, budget, vCPU quota, state bucket; plan §3.3). `export AWS_PROFILE=hsl`.
2. `cp infra/backend.hcl.example infra/.backend.hcl` and set the state bucket.
3. `cp infra/terraform.tfvars.example infra/terraform.tfvars` and set `suffix` and `alert_emails`.
4. On GitHub, make the `streamlite` package public: Profile → Packages → streamlite → Package settings → Change visibility.
   `make image-check` confirms that it worked.

## First deploy (T2.6) → live URL, tag `v0.2`

```bash
make tf-init
make ami                 # Packer, ~6 min → infra/ami.auto.tfvars (IMAGE_TAG=<sha7> to choose the image)
make tf-apply            # ALB, ASG(1), CloudFront (first deploy takes 5–15 min), site, SSM, budget
make env                 # → .env.tf
make publish-site        # web/ → S3, invalidate CloudFront
make smoke               # checks 1–4 and 6; `make smoke SPREAD=1` also scales to 3 for check 5
```
Paste the `make smoke` output into the PR, write the CloudFront URL in the top-level README, then tag `v0.2`.

`IMAGE_TAG` defaults to the newest commit that changed `app/`, `web/` or the docker workflow. GHCR only
has tags for commits that were the head of a push to `main`. If `image-check` fails, copy a tag from the
GHCR package page and pass it, e.g. `make ami IMAGE_TAG=86c00d4`.

## Lab session (A starts it, C runs experiments)

```bash
make lab-up              # same stack + loadgen (c7i-flex.large); refreshes .env.tf
make loadgen-shell       # SSM shell; `source /etc/profile.d/hsl.sh` already exported
...                      # Phase 3: make push-harness / pull-harness / exp
make destroy-lab         # reset ASG to 1, remove loadgen, list what is still running
```
`make tf-apply` on its own always means `LOADGEN=false`. Running it during a session removes the
loadgen, so use `make lab-up` instead.

## Changing the fleet

| Change | Command | Effect |
|---|---|---|
| New app version | push to `main` (docker workflow) → `make ami` → `make tf-apply` | rolling instance refresh, capacity never drops |
| `work_scale` / `web_concurrency` | edit `terraform.tfvars` → `make tf-apply` | new user_data → instance refresh |
| E5 naive boot | `make tf-apply MODE=naive`; afterwards `make tf-apply` | stock AL2023 + Docker install at boot, grace 240 s |
| Scaling mode | Phase 3 `automation/asg_mode.py` | Terraform ignores min/max/desired (F1) |

Boot timings for E5 are in `/var/log/hsl-boot.log` on each instance (`<step> <epoch> <os_uptime>`).

## Packer fallback (if `make ami` fails)

Launch one AL2023 c7i-flex.large with the `hsl-app-profile` instance profile, open an SSM shell, copy
`provision.sh` over and run `sudo IMAGE=ghcr.io/<owner>/streamlite:<sha7> bash provision.sh`. Then run
`aws ec2 create-image --instance-id <id> --name hsl-streamlite-manual-<sha7>`. Put the new id in
`infra/ami.auto.tfvars` as `ami_id = "ami-…"` and terminate the instance.

## Teardown

- After each session: `make destroy-lab` (or `./deploy_aws.sh lab-down`). The demo stack (ALB +
  CloudFront + 1 instance) keeps running, at about $3 of credit per day.
- Not needed for a day or more: `./deploy_aws.sh pause` (ASG to 0, about $1 per day for the ALB and its
  IPs); `./deploy_aws.sh resume` brings 1 server back in ~2 min.
- After the viva: `make results-pull`, then `make destroy-all`. It asks you to type `destroy`, deletes
  the results bucket, deregisters every `hsl` AMI and deletes their snapshots. The state bucket is kept.

## Troubleshooting

See plan §14. The most common problems: targets stay unhealthy (`systemctl status streamlite` over SSM),
the GHCR package is still private (`make image-check`), or `VcpuLimitExceeded` (quota not granted yet), or `Your account must be verified before you can add new CloudFront resources` (AWS Support case; the
stack runs with `enable_cloudfront = false` meanwhile), or `not eligible for Free Tier` (set `APP_TYPE` to an
eligible type: `aws ec2 describe-instance-types --filters Name=free-tier-eligible,Values=true`).

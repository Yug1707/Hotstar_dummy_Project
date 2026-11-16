# 8 Team and process

## 8.1 Roles

| Role | Owns | Name |
|---|---|---|
| A, Infra and Platform | `infra/`, cost model inputs, case study | `TODO(team)` |
| B, App, Dashboard, Analysis | `app/`, `web/`, `analysis/` | `TODO(team)` |
| C, Load Lab and Experiments | `harness/`, `results/` | `TODO(team)` |

## 8.2 Process

Work was split by folder and by Makefile fragment so two people rarely edited the same file. Every change went through a pull
request with the template's "how verified" and "cost impact" sections; CI runs lint, tests, Terraform and Packer validation,
shellcheck, a container smoke test, the web checks and the analysis pipeline on synthetic data. Handoffs between roles were fixed
in advance (image to AMI, ASG to harness, run-folder schema to parser, live URL, C1 to everything downstream), and the parser and
dashboard were built against a synthetic campaign so they were ready before the first real run. A daily progress entry
(`docs/progress.md`) records what was done, what was learned and what blocked.

## 8.3 Contribution statistics

`TODO(team)`: paste `git shortlog -sn --no-merges` and the list of merged pull requests per role at the end.

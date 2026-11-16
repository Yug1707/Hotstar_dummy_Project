# Viva: slides and cheat sheet

Ten slides, about ten minutes, plus questions. Slides 5 to 8 are filled in from the real figures after Phase 4; until then the
**Source** column says where each number will come from, and no number is to be quoted that is not in a committed `summary.json`.

## Slides

| # | Slide | Content | Source |
|---|---|---|---|
| 1 | The problem | a wall of 1 M+ new viewers per minute, about 90 s to react, servers that boot slower; the peaks timeline | dashboard "The case", `docs/sources.md` S1 to S5 |
| 2 | What Hotstar did | 2019 EC2 and Auto Scaling, pre-warm and a custom scaler, baked AMIs, degradation, HULK; 2023 EKS, Envoy, split CDN domains | `docs/report/02-case-study.md` |
| 3 | Our replica | architecture figure; what maps to what and what we do not claim | `docs/architecture.md` section 6, `web/img/architecture.svg` |
| 4 | StreamLite and method | CPU model, open-model load, SLO (p95 < 300 ms, errors < 1 %), three runs, median and range | `docs/report/04-exercise-design.md` |
| 5 | **F1: latency against instance count** (the required plot) | knee, C1, linear capacity and efficiency | `results/figures/F1.png`, E1 and E2 |
| 6 | F2 and F3: reactive against proactive | the 90 s ramp, violation seconds, the extra instance-minutes it costs | F2, F3, E3 and E4 |
| 7 | F4 and F5: boot time and degradation | baked against naive against the 90 s window; what shedding protects | F4, F5, E5 and E6 |
| 8 | F6 and F7: CDN and cost | origin offload; cost per strategy and fleet size at 25 M and 59 M | F6, F7, E7 and E8 |
| 9 | Limitations and what breaks at 59 M | the five limitations; shared components that saturate first | dashboard "What this does not show", `07-discussion.md` |
| 10 | Live demo | dashboard, then the live panel, then the burst test, then optionally flip the degrade level through SSM and show the shed count | the deployed URL |

**Demo script (slide 10).** Open the dashboard on a phone over mobile data. Show the live panel (instance id, AZ, degrade level). Run the
burst test and point at the instances in the colours. Optionally, from a laptop,
`aws ssm put-parameter --name /streamlite/degrade_level --value 1 --overwrite`, run the burst again, and show that recommendations
come back degraded; set it back to 0 afterwards. Have a screenshot of each step ready in case the network fails.

## Cheat sheet (every member must be able to answer these)

| Question | Short answer to build on |
|---|---|
| Why did standard Auto Scaling not work for Hotstar? | Capacity errors, one instance type per group, step limits, AZ constraints, and a 1 M+/min ramp that outruns metrics and boot time; hence pre-warming and a custom proactive scaler. |
| What does your F1 show? | Latency against instance count at fixed load: saturated below the knee, flat above it; capacity grows roughly linearly with N. Quote C1 and the efficiency from `summary.json`. |
| Why an open-model load? | Real viewers do not wait for the server; closed-model tools slow down when the server does and hide overload (coordinated omission). |
| Reactive against proactive: what happened? | State the measured numbers from F2 and F3 and the extra instance-minutes proactive pays. That is the trade-off. |
| Why bake the AMI? | Instances must be useful inside the reaction window; quote the E5 numbers against 90 s. |
| What is graceful degradation and why is it safe? | Switch off non-critical features (recommendations) to protect playback and payments; E6 shows the critical p95 holding while non-critical work is shed. |
| What changed in 2023? | Clusters capped near 25 M; moved to EKS, datacentre abstraction, Envoy replacing 200+ ALBs, split cacheable and personalised CDN domains. |
| How reliable is your cost estimate? | Compute tier only and assumption-driven; no official Hotstar infrastructure cost exists; we show sensitivity. |
| What would break at 59 M? | Load balancer and NAT limits, API-server throttling, CDN capacity, quotas, the database tier: none are in the replica. |
| Why not AWS predictive scaling, warm pools or scheduled actions? | Predictive scaling needs a day or more of history and assumes recurring patterns, so it ignores a one-off event. Scheduled actions are the AWS-native version of our pre-warm (E4d). Warm pools cut boot time the way baked AMIs do but do not change the decision signal. |
| Why is the load generator in the same region? | To keep the internet out of the measurement and make runs comparable; the cost is that latencies are kinder than real. Stated as a limitation. |
| Why does the live panel often show one instance? | The ALB balances per request, but one browser reuses one connection to CloudFront, which reuses connections to the ALB, so a single browser mostly lands on one instance. The burst test and k6 open many connections and spread out. |
| Why 25 viewers per request per second? | Derived from rounded public numbers (about 25.3 M concurrent against about 1 M requests per second in 2019); it is a planning ratio, varied from 10 to 50 in the sensitivity table. |

## Rehearsal checklist

- [ ] Each member answers three random questions from the table without notes.
- [ ] The demo runs end to end on the live URL from a phone, twice, at least a day before.
- [ ] Every number on slides 5 to 8 is checked against a committed `summary.json`.
- [ ] `grep -rn "TODO(" docs/report` is empty.

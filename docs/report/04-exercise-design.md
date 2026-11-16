# 4 Exercise design

## 4.1 Hypotheses

| ID | Hypothesis | Experiments |
|---|---|---|
| H1 | Throughput grows roughly linearly with instance count; at fixed load, latency against instance count is a hockey stick (saturated at low N, flat after the knee). | E1, E2 |
| H2 | Standard reactive autoscaling lags a steep spike (metric delay plus boot time) and produces a latency and error burst; pre-warming plus a concurrency-driven scaler avoids it. | E3, E4 |
| H3 | Fully baked AMIs make new capacity ready much faster than installing at boot. | E5 |
| H4 | Graceful degradation (switching off non-critical features) protects the critical playback path under overload. | E6 |
| H5 | Fronting cacheable APIs with a CDN, separate from personalised ones, offloads the origin. | E7 |
| H6 | Event-shaped capacity is far cheaper than always-on peak capacity; Spot lowers cost further; compute-only cost extrapolates to 25 M and 59 M concurrency. | E8 |

## 4.2 The system under test

**StreamLite** is a FastAPI service with four request classes of known CPU cost: critical (`playback/start` 15 ms, `heartbeat` 2 ms),
public and cacheable (`match/state` 1 ms, `Cache-Control: public, max-age=5`), non-critical (`recommendations` 40 ms) and
infrastructure (`healthz`, `whoami`). The cost is a calibrated CPU burn, multiplied by one `WORK_SCALE` factor chosen so that a
`c7i-flex.large` saturates at about 100 requests per second. Statistics count arrivals, not completions. Section 3 of
[`docs/architecture.md`](../architecture.md) gives the infrastructure: CloudFront, ALB, an Auto Scaling Group of one to four
`c7i-flex.large` instances (the AWS Free plan only launches free-tier-eligible types), a baked AMI, and a load
generator (`c7i-flex.large`) in the same region.

## 4.3 Load profiles

All profiles use k6's **open model** (`ramping-arrival-rate`): arrivals do not wait for responses, so overload appears as latency and
errors instead of being hidden by coordinated omission. The traffic mix is 55 % heartbeat, 10 % playback start, 20 % match state and
15 % recommendations. Profiles are expressed in multiples of C1, the capacity of one instance measured in E1.

| Profile | Shape | Used by |
|---|---|---|
| `step` | ten rate steps from 0.1 x to 2.0 x a guess, each 5 s ramp plus 55 s hold | E1, E2b |
| `fixed` | 30 s ramp to a fixed rate, then hold (default 5 min) | E2a, E6, E7 |
| `spike` | 2 min at 0.3 x, 90 s ramp to 3 x, hold, three 30 s wicket bursts to 4.2 x, then 3 min at 0.5 x (12 min 30 s) | E3, E4 |

## 4.4 Service-level objective and validity

The **SLO** is: critical-class p95 below 300 ms and error rate below 1 %. A run is **valid** only if k6 reports no dropped
iterations, no HTTP 429 (the load-test token must bypass the rate limit), the load generator's CPU stays under 70 %, and k6 exits
with 0 or 99 (99 means a threshold was crossed, which is a result). Invalid runs are kept and logged, never deleted.

## 4.5 Metric definitions

- **Per-second bucket.** Requests grouped by `floor(timestamp - k6 start)`. The first `warmup_discard_s` (30 s) are dropped for the
  fixed and step profiles, never for the spike, where the start is the test.
- **SLO-violation second.** A bucket with at least 10 critical requests where critical p95 exceeds the SLO or the critical error rate exceeds 1 %.
- **Error.** `http_req_failed = 1`: status of 400 or more, a timeout after 5 s, or a connection error.
- **Time to first new instance.** The first `asg_timeline` row where healthy targets exceed the baseline, minus the ramp start (k6 start plus 120 s).
- **Instance-minutes.** The integral of (in service plus pending) over [k6 start, k6 end plus 300 s]. This is the billing-relevant quantity: pending instances are paid for.
- **Capacity (E2b).** The highest step rate before the first step that breaks the SLO.
- **Knee (E1).** The highest step where critical p95 is under 300 ms and the error rate under 1 % for the whole hold; C1 is the median over three runs.

## 4.6 Method and run hygiene

Three runs per arm where required; the report states the median and the min to max, never the best run. Within one comparison the
AMI, instance type, `WORK_SCALE` and harness SHA are identical and recorded in `meta.json`. The experiment order is E1, E2, E5, E3,
E4, E6, E7. One experiment runs at a time (a lock object in S3), the ASG is always reset on exit, and the stack is torn down after
every session. The analysis is `analysis/parse_k6.py`, `make_plots.py` and `cost_model.py`, tested on synthetic data
(`analysis/fake_run.py`) so it was finished before the first real run.

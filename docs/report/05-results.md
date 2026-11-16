# 5 Results

Numbers are *median (min to max of N runs)* from `results/<EXP>/run*/summary.json`. Every `TODO(EX)` marks a measurement that
does not exist yet; nothing here is estimated. All runs: `c7i-flex.large`, same AMI, `WORK_SCALE` and harness SHA (see `meta.json`),
C1 = `TODO(E1)` rps.

## 5.1 E1 and E2: capacity and latency against instance count (H1)

**Hypothesis.** Capacity grows roughly linearly with N; at a fixed load latency is a hockey stick.

**Setup.** E1: step profile on one instance, three runs, to find the knee (C1). E2a: fixed 2 x C1 for N = 1 to 4, three runs each,
alternating the order of N to cancel drift. E2b: step profile for each N, one run each, to find capacity(N).

**Result.** Figure F1 (`results/figures/F1.png`). C1 = `TODO(E1)` rps (range `TODO(E1)`). At 2 x C1, critical p95 is `TODO(E2a)` ms
at N = 1, `TODO(E2a)` ms at N = 2 and `TODO(E2a)` ms from N = 3. Capacity at N = 5 is `TODO(E2b)` rps against an ideal of 5 x C1;
efficiency = capacity(N) / (N x C1) = `TODO(E2b)`.

**Interpretation.** `TODO(E2)`: does the knee sit where H1 predicts, and where does efficiency fall away from 1 (ALB balancing,
GIL, noisy neighbours)?

**Link to Hotstar.** Capacity planning: viewers per instance follows from C1 (section 6).

## 5.2 E3 and E4: reactive against proactive scaling (H2)

**Hypothesis.** A reactive CPU policy lags the 90 s ramp; pre-warming plus an arrival-rate ladder avoids the violation.

**Setup.** Spike profile (12 min 30 s). E3: target tracking at 50 % CPU, three runs. E4c: pre-warm to 4 plus ladder, three runs. E4a:
pre-warm only. E4b: ladder only. E4d (optional): scheduled action at the ramp start.

**Result.** Figures F2 (timeline, median run) and F3 (violations and errors). Time from ramp start to the first new healthy
instance: reactive `TODO(E3)` s. SLO-violation seconds: reactive `TODO(E3)`, proactive (c) `TODO(E4c)`, pre-warm only `TODO(E4a)`,
ladder only `TODO(E4b)`. Peak critical p95: `TODO(E3)` ms against `TODO(E4c)` ms. Extra instance-minutes of proactive over reactive:
`TODO(E4c)` %.

**Interpretation.** `TODO(E3/E4)`: which of the two parts of the proactive scaler (floor or ladder) carries the result, and what the
extra instance-minutes buy. State the price of safety explicitly.

**Link to Hotstar.** Pre-warming plus a custom request-rate scaler (S6).

## 5.3 E5: baked against naive boot (H3)

**Hypothesis.** A baked AMI makes capacity useful much sooner than installing Docker and pulling the image at boot.

**Setup.** No load. Scale 1 to 4 with the monitor at 2 s, three runs per AMI mode; for the naive mode the `hsl-boot.log` breakdown
(Docker install, image pull, container start).

**Result.** Figure F4. Launch to first healthy target: baked `TODO(E5)` s, naive `TODO(E5)` s; the naive breakdown is `TODO(E5)`.

**Interpretation.** `TODO(E5)`: compare each with the 90 s window; say which step dominates the naive boot.

**Link to Hotstar.** Fully baked AMIs (S7).

## 5.4 E6: graceful degradation (H4)

**Hypothesis.** Switching off recommendations protects the critical path under overload.

**Setup.** 3 x C1 on two instances, three variants, three runs each: no degradation, degrade level 1 set through SSM before k6
starts, and `AUTO_SHED=true`.

**Result.** Figure F5. Critical p95: none `TODO(E6)` ms, level 1 `TODO(E6)` ms, auto-shed `TODO(E6)` ms; requests shed `TODO(E6)`.

**Interpretation.** `TODO(E6)`: what was lost (non-critical responses) against what was kept; manual against automatic.

**Link to Hotstar.** Non-critical features switched off to protect playback (S8).

## 5.5 E7: CDN offload (H5)

**Hypothesis.** A short cache on the cacheable endpoint removes almost all of its load from the origin.

**Setup.** Match-state-only traffic at 3 x C1 for 3 minutes against the ALB directly and through CloudFront, three runs each.

**Result.** Figure F6. Requests reaching the origin (CloudWatch ALB `RequestCount`): ALB arm `TODO(E7)`, CloudFront arm `TODO(E7)`.
Client p95: `TODO(E7)` ms against `TODO(E7)` ms.

**Interpretation.** `TODO(E7)`: with a 5 s cache the origin should see on the order of one request per edge location per 5 s; compare.

**Link to Hotstar.** Cacheable and personalised APIs on separate CDN domains (S10).

## 5.6 Summary of hypotheses

| Hypothesis | Verdict | Evidence |
|---|---|---|
| H1 | `TODO(E1/E2)` | F1 |
| H2 | `TODO(E3/E4)` | F2, F3 |
| H3 | `TODO(E5)` | F4 |
| H4 | `TODO(E6)` | F5 |
| H5 | `TODO(E7)` | F6 |
| H6 | see section 6 | F7 |

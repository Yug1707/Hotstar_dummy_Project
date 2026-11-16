# 3 Analysis

## 3.1 Decomposing the problem

Keeping latency flat through a spike needs four things to be true at once.

1. **Enough capacity at the moment of demand.** Capacity must exist before the ramp finishes, not after.
2. **Fast capacity.** What cannot be pre-built has to become useful inside the reaction window: image baked, dependencies present,
   health checks passing quickly.
3. **A signal that leads.** Scaling on a lagging signal (average CPU, one-minute metrics) answers the previous minute's load.
4. **A way to refuse gracefully.** When 1 to 3 are not enough, the platform should lose the cheapest features first.

Each experiment targets one of these: E2 asks how much capacity a given load needs; E5 how fast new capacity is useful; E3 and E4
how the signal and pre-warming change the outcome; E6 what degradation buys; E7 how much load never reaches the origin.

## 3.2 Why a standard Auto Scaling group falls short

A target-tracking policy on average CPU has three delays in series: the metric is published once a minute, the alarm needs several
consecutive datapoints, and the new instance then takes time to launch, boot and pass health checks. For a ramp that completes in
90 seconds the sum of these delays is several times the ramp itself. The policy is also reactive by construction: it can only
respond to load that is already hurting users. Hotstar's reported answer (S6) was to make the capacity decision **before** the
demand, from knowledge of the match schedule, and to steer with a faster signal while the match runs. Our proactive scaler
implements the same two ideas at small scale: a pre-warm floor and a ladder driven by the measured arrival rate.

## 3.3 What AWS already offers, and why we still built a scaler

| AWS feature | Fit to a match-day spike |
|---|---|
| Scheduled actions | the native form of pre-warming; included as E4d. Needs the schedule to be known, which is true for a match |
| Predictive scaling | learns from at least a day of history and assumes recurring patterns; poor at one-off events |
| Warm pools | shorten boot time much as baked AMIs do; they do not change the decision signal |
| Target tracking and step scaling | reactive; the baseline in E3 |

The experiments therefore compare *where the decision comes from* (a metric, a schedule, or the arrival rate) and *how long
capacity takes to be useful* (baked or installed at boot), at a scale a student account can afford.

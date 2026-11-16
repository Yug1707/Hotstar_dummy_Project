# 1 Introduction

Streaming a cricket match to tens of millions of people is a scaling problem with an unusual shape. Demand does not grow
smoothly: when a match starts, or a wicket falls, viewers arrive in a wall. Disney+ Hotstar reported more than a million new
viewers per minute and about 90 seconds in which to react (S5), while a fresh server needs longer than that to boot, register
and pass health checks. A scaling system that waits for a metric to cross a threshold, then asks for machines, answers a spike
that has already happened.

This project builds a scaled-down, honest replica of that problem and measures it. We deploy a small streaming-style API,
**StreamLite**, behind an AWS Application Load Balancer and an Auto Scaling Group, put it on a public HTTPS address through
CloudFront, and use k6 to replay a match-day traffic spike under different scaling strategies. We measure latency, errors,
scaling behaviour and cost, and we compare what we see with what Hotstar says it did.

We ask six questions, stated as hypotheses H1 to H6 in section 4:

1. How does latency depend on the number of instances at a fixed load, and does capacity grow linearly (H1)?
2. Does standard reactive autoscaling lag a steep spike, and does pre-warming plus a request-rate scaler avoid it (H2)?
3. How much faster does a fully baked image make new capacity useful (H3)?
4. Does switching off non-critical features protect the critical path under overload (H4)?
5. How much origin load does a CDN remove when cacheable and personalised APIs are separated (H5)?
6. What does event-shaped capacity cost compared with always-on peak capacity, and how does that extrapolate (H6)?

The scale is small (at most six instances) and the questions are about shape, not magnitude. Section 7 says what that does and does
not let us conclude. The repository, the plans, the run summaries and a live dashboard are linked from `README.md`.

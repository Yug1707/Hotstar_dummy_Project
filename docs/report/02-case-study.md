# 2 Case study: Disney+ Hotstar and live cricket

Every figure in this section cites a row of [`docs/sources.md`](../sources.md). Rows whose confidence is still _verify_ there
are marked **(to verify)** here and must be checked against the primary source before submission.

## 2.1 The load

| Event | Peak concurrent viewers | Source |
|---|---|---|
| IPL 2019 | 10.3 M (to verify) | S3 |
| IPL 2019 final | 18.6 M (to verify) | S3 |
| ICC World Cup 2019 semi-final | 25.3 M (to verify) | S4 |
| ICC World Cup 2023 final | 59 M (official, S1); a secondary source reports 61 M (S2) | S1, S2 |

We use 59 M and treat 61 M as a conflict between sources, not as an average. Two features of the load matter more than the peaks:
the **ramp** (more than a million new viewers per minute at the start of a match, S5) and the **bursts** (wickets and the end of an
innings change viewing behaviour within seconds).

## 2.2 2019: EC2, Auto Scaling and a custom scaler

Hotstar described standard Auto Scaling as insufficient for this ramp and replaced it with **pre-warming** (capacity ready before the
match) plus a custom scaler driven by request rate and concurrency rather than CPU (S6). Instances were fully baked images so a new
machine was useful quickly, and fleets used diversified instance types and Spot capacity (S7; the Spot share is unverified, S12).
Under overload the platform **degraded gracefully**: non-critical features such as recommendations were switched off to protect
playback (S8, to verify). Load testing at scale (**Project HULK**) used on the order of 108,000 CPUs across several regions
(S9, to verify).

## 2.3 2023: Kubernetes, Envoy and split CDN domains

By 2023 the clusters had a ceiling near 25 M. The platform moved to Amazon EKS, abstracted the datacentre layer, replaced more than
200 ALBs with Envoy-based routing, and separated **cacheable** from **personalised** APIs onto different CDN domains so that the CDN
could absorb the cacheable traffic (S10, to verify). The CDN vendors are not confirmed (S11).

## 2.4 What the lab takes from this

| Hotstar fact | In the lab |
|---|---|
| ramp of 1 M+/min in about 90 s | k6 ramps to 3 x C1 in 90 s |
| standard scaling failed; pre-warm and a request-rate scaler | reactive CPU policy against our proactive scaler |
| fully baked images | Packer AMI against install-at-boot |
| graceful degradation | SSM degrade level and auto-shed |
| cacheable and personalised APIs split | `/api/v1/match/*` cached by CloudFront, personal APIs not |

The mapping and its limits are in [`docs/architecture.md`](../architecture.md) section 6. The roughly US$3 billion figure that
circulates is a media-rights fee, not cloud spend (S13), and is not used anywhere in the cost analysis.

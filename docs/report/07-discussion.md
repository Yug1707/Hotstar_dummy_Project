# 7 Discussion

## 7.1 Lessons

`TODO(all)`: written after Phase 4 by the whole team, one short paragraph each on: what surprised us in the measurements; what the
harness caught (invalid runs, saturated load generator, scaling-policy leftovers); what was harder than the plan assumed.

## 7.2 Threats to validity

| Threat | Effect | Mitigation or statement |
|---|---|---|
| Load generator in the same region | latency and CDN behaviour are kinder than reality | stated; comparisons are relative |
| Tiny scale (1 to 4 instances, AWS Free plan) | shape, not magnitude | extrapolation labelled as arithmetic |
| Synthetic CPU model | real paths have databases, caches and licences | classes with fixed CPU cost; calibrated once |
| Round-robin ALB | no least-outstanding-requests balancing | stated; E2b measures the efficiency it causes |
| `c7i-flex` runs at full speed only "most of the time" | a slower instance looks like a lower C1 | E1 measures C1 on the same type; three runs per point |
| CloudWatch one-minute granularity | reactive timing is coarse | the monitor samples the ASG every 2 s |
| Three runs per arm | median and range, not a confidence interval | quoted as such, never the best run |
| One instance type | no diversification, no Spot behaviour | Spot enters only through the cost model |
| 25 viewers per rps is derived | order of magnitude | sensitivity 10 to 50 |
| Hotstar numbers are partly secondary | some inputs unconfirmed | each cited with its confidence label |

## 7.3 What changes at real scale

What would break at 59 M viewers and is not covered by a replica: load balancer and NAT limits, Kubernetes API-server throttling,
CDN capacity and cache hit ratio, account quotas, and the database tier. At that scale the interesting questions move from "how
many instances" to "which shared component saturates first", which is where Hotstar's 2023 changes (Envoy instead of 200 ALBs,
split CDN domains) were aimed. `TODO(all)`: add what our measured efficiency curve suggests about the first limit we would hit.

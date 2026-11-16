# 6 Cost analysis (E8)

## 6.1 Method

The cost model (`analysis/cost_model.py`, inputs in `config/model.yaml` and `config/prices.yaml`) is arithmetic on measured values
and published prices. It never contains a price itself. It prints every intermediate value.

```
viewers_per_instance = C1 x planning_utilisation x viewers_per_rps          (planning_utilisation 0.8, viewers_per_rps 25)
instances(peak)      = ceil(peak / viewers_per_instance)
strategy_cost_match  = (measured instance-minutes / measured window minutes) x match_hours x price_per_hour
always_on_cost_24h   = instances(peak) x 24 x price_per_hour
spot_cost            = cost x (1 - spot_share x spot_discount)
hulk_cost            = vcpus x hours x price_per_hour / vcpus_per_instance
```

The 25 viewers per request-per-second is derived from two rounded public numbers (about 25.3 M concurrent viewers against about 1 M
requests per second in 2019) and is a planning assumption, not a measurement; the sensitivity table varies it from 10 to 50. The
Spot shares are 0 %, 35 % and 70 %; the 70 % figure is an unverified claim (S12) that the model tests rather than asserts.

## 6.2 Results

- **Per strategy** (F7, panel A; table in `results/E8/cost.md`): measured instance-minutes of the spike runs, scaled to a four-hour
  match. Reactive `TODO(E3)`, proactive `TODO(E4c)`; extra cost of safety `TODO(E4c)` %. Prices: `TODO(prices.yaml)`.
- **Always-on against event-shaped** at the 2023 peak: `TODO(E8)` instances; always-on for 24 h `TODO(E8)`; event-shaped for four hours
  `TODO(E8)`.
- **Fleet size at each peak** (F7, panel B): 10.3 M, 18.6 M, 25.3 M and 59 M viewers need `TODO(E1)` instances each at the measured C1.
- **Sensitivity** at 59 M: viewers per rps 10 / 25 / 50 against Spot 0 / 35 / 70 %: `TODO(E8)`.

## 6.3 What is not counted

CDN and egress, databases, caches, the Kubernetes control plane, support and people. The compute tier is a small part of the real bill, so
these figures bound the cost of one slice of the platform; they are not an estimate of Hotstar's infrastructure cost, for which no
official figure exists. The US$3 billion that circulates is a rights fee, not cloud spend (S13).

## 6.4 The lab's own bill

Budget guardrails and the actual spend for the campaign (from Billing, daily during Phase 4): `TODO(billing)`.

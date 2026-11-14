# Sources log

Every number in the report and on the dashboard cites an `S#` from this table.
Confidence: **official** (Disney/Hotstar/AWS first-party), **secondary** (reputable press/blog citing others),
**unverified** (claimed, no primary source found).

> Hotstar's engineering blog returns HTTP 403 to scripts: open it in a browser and paste the URL + access date.
> Rows marked _verify_ were carried over from the Week 1 summary and still need the exact URL.

| # | Claim | Value | Source (title, URL, date accessed) | Type | Confidence |
|---|---|---|---|---|---|
| S1 | Peak concurrent viewers, ICC World Cup 2023 final (19 Nov 2023) | 59M | Disney / TechCrunch — _verify URL_ | press | official |
| S2 | Same event, conflicting figure | 61M | ByteByteGo — _verify URL_ | blog | secondary (conflicts with S1) |
| S3 | Peak concurrency, IPL 2019 | 10.3M → 18.6M (final) | Hotstar engineering blog — _verify URL_ | eng blog | _verify_ |
| S4 | Peak concurrency, ICC World Cup 2019 (Ind v NZ semi-final) | 25.3M | Hotstar / press — _verify URL_ | press | _verify_ |
| S5 | Traffic spike: 1M+ new users per minute, ~90 s reaction window | 1M+/min, ~90 s | AWS re:Invent 2019 CMY302 (Gaurav Kamboj) — _verify URL_ | talk | official |
| S6 | Standard Auto Scaling insufficient; pre-warming + custom scaler on request rate / concurrency | – | re:Invent 2019 CMY302; Rootconf 2019 talk — _verify URL_ | talk | official |
| S7 | Fully baked AMIs, Spot fleets with diversified instance types | – | re:Invent 2019 CMY302 — _verify URL_ | talk | official |
| S8 | Graceful degradation: non-critical features (recommendations, personalisation) switched off under load | – | Hotstar engineering blog — _verify URL_ | eng blog | _verify_ |
| S9 | Project HULK load tests: 108,000 CPUs, ~200 Gbps, 8 regions | 108k CPUs | Hotstar engineering blog — _verify URL_ | eng blog | _verify_ |
| S10 | 2023 re-architecture: KOPS clusters capped near 25M → EKS, datacenter abstraction, Envoy replacing 200+ ALBs, separate CDN domains for cacheable vs personalised APIs | – | Hotstar engineering blog (2023) — _verify URL_ | eng blog | _verify_ |
| S11 | CDN vendor(s) used (Akamai flagged "to confirm") | – | _to confirm_ | – | unverified |
| S12 | ~70 % Spot share, ~35 % savings | 70 %, 35 % | _secondary only_ | – | unverified (tested as sensitivity, not asserted) |
| S13 | ~US$3B figure is a media-rights fee, **not** cloud spend | – | _verify URL_ | press | secondary |

Weak sources (Medium, TechAhead, GeeksforGeeks) are leads only and are never cited for a number.

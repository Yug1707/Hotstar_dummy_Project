# References and reproduction

## References

The full list, with URL, access date, type and confidence, is [`docs/sources.md`](../sources.md) (S1 to S13). Weak sources
(blog aggregators and tutorial sites) are leads only and are never cited for a number. Before submission every row marked _verify_
there needs its exact URL and an access date; this report cites rows by their `S#`.

## Reproducing the results

1. **Local, no AWS:** `make doctor && make venv && make test && make dev`; `make tf-test` for the offline Terraform tests;
   `make harness-test` and `make dry-local` for the harness; `make analysis-test` and `make fake-campaign` for the analysis chain.
2. **Deploy:** [`infra/README.md`](../../infra/README.md): one-time setup, `make ami`, `make tf-apply`, `make smoke`, `make publish-site`.
3. **Experiments:** [`harness/README.md`](../../harness/README.md) and [`results/README.md`](../../results/README.md): `make lab-up`,
   `make push-harness`, `harness/exp.sh EXP RUN [N|VARIANT]` on the load generator, `make destroy-lab`.
4. **Analysis:** `make results-pull RAW=1`, `python analysis/parse_k6.py --all`, `make analyze`, `make publish-site`.
5. **Cost:** fill `config/prices.yaml` from one AWS Pricing Calculator estimate, then `make analyze`.

Every run folder holds its own `meta.json` (AMI, image tag, `WORK_SCALE`, C1, harness SHA, ASG configuration, validity), so a
number in this report can be traced to the exact configuration that produced it.

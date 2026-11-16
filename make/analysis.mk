# Owner: B (Analysis). Phase 5 targets. Needs the analysis dependencies: `make venv-analysis`.

PYA ?= .venv/bin/python

.PHONY: venv-analysis analyze analyze-full analysis-test fake-campaign

venv-analysis: ## install pandas, matplotlib, ... into .venv
	@if command -v uv >/dev/null 2>&1; then uv pip install -q --python $(PYA) -r analysis/requirements.txt; \
	else .venv/bin/pip install -q -r analysis/requirements.txt; fi

analyze: ## committed summaries -> figures F1-F7 -> cost model -> web/data/results.json (< 1 min)
	$(PYA) analysis/make_plots.py
	$(PYA) analysis/cost_model.py
	$(PYA) analysis/export_results.py

analyze-full: ## like analyze, but first re-parse the raw k6 CSVs (needs `make results-pull RAW=1`)
	$(PYA) analysis/parse_k6.py --all --force
	$(MAKE) analyze

analysis-test: ## analysis unit tests on synthetic data (no AWS)
	$(PYA) -m pytest -q analysis/tests

fake-campaign: ## write + parse + plot a synthetic E1-E7 campaign (results/FAKE_*, git-ignored)
	$(PYA) analysis/fake_campaign.py
	$(PYA) analysis/parse_k6.py --all --pattern 'FAKE_*'
	$(PYA) analysis/make_plots.py --prefix FAKE_ --out results/figures-fake

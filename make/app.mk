# Owner: B (App, Dashboard, Analysis)

APP_ENV := IMDS_ENABLED=false SSM_MODE=off LOADTEST_TOKEN=local

.PHONY: venv dev test test-all lint fmt image run-image calibrate

venv: ## create .venv with app + dev dependencies
	@if command -v uv >/dev/null 2>&1; then \
	  uv venv -q -p 3.12 .venv && uv pip install -q --python .venv/bin/python -r app/requirements-dev.txt -r analysis/requirements.txt; \
	else \
	  python3.12 -m venv .venv && .venv/bin/pip install -q -r app/requirements-dev.txt -r analysis/requirements.txt; \
	fi
	@echo "ok: .venv ready"

dev: ## run StreamLite locally with reload on :8000
	$(APP_ENV) .venv/bin/uvicorn main:app --app-dir app --reload --port 8000

test: ## fast tests (CI)
	$(PY) -m pytest -q -m "not slow"

test-all: ## all tests including slow CPU-timing ones
	$(PY) -m pytest -q

lint: ## ruff lint + format check
	.venv/bin/ruff check .
	.venv/bin/ruff format --check .

fmt: ## auto-format
	.venv/bin/ruff format .
	.venv/bin/ruff check --fix .

image: ## build the container image streamlite:<sha>
	docker build -f app/Dockerfile --build-arg GIT_SHA=$(SHA) -t streamlite:$(SHA) -t streamlite:latest .

run-image: ## run the image locally on :8000
	docker run --rm -p 8000:8000 -e IMDS_ENABLED=false -e SSM_MODE=off -e LOADTEST_TOKEN=local streamlite:latest

calibrate: ## time each CPU work class (run on the target instance type)
	$(APP_ENV) $(PY) scripts/calibrate.py

# Owner: C (Load Lab & Experiments). Phase 3 make targets; included from make/lab.mk.
# Runs on the laptop. On the loadgen there is no repo or make: see harness/README.md.

HARNESS_PY ?= .venv/bin/python
LOCAL_URL  ?= http://127.0.0.1:8000

.PHONY: push-harness results-pull harness-test harness-lint dry-local lab-status lab-unlock

push-harness: ## upload harness/ to s3://$RESULTS_BUCKET/harness/harness.tgz (VERSION = git sha)
	@$(LOAD_ENV) && tmp=$$(mktemp -d) && trap 'rm -rf "$$tmp"' EXIT && \
	  tar -C . --exclude='__pycache__' --exclude='.state' --exclude='.pytest_cache' --exclude='.ruff_cache' -cf - harness | tar -C "$$tmp" -xf - && \
	  ver=$$(git rev-parse --short HEAD); [ -z "$$(git status --porcelain -- harness)" ] || ver="$$ver-dirty"; \
	  echo "$$ver" > "$$tmp/harness/VERSION" && \
	  tar -C "$$tmp" -czf - harness | aws s3 cp - "s3://$$RESULTS_BUCKET/harness/harness.tgz" && \
	  echo "pushed harness $$ver -> s3://$$RESULTS_BUCKET/harness/harness.tgz"

results-pull: ## sync results from S3 (summaries only; RAW=1 also pulls raw k6 CSVs)
	@$(LOAD_ENV) && aws s3 sync "s3://$$RESULTS_BUCKET/results/" results/ $(if $(RAW),,--exclude "*/raw/*")

harness-test: ## harness unit tests (fake AWS clients, no account needed)
	$(HARNESS_PY) -m pytest -q harness/tests

harness-lint: ## ruff + shellcheck for harness/, and k6 inspect if k6 is installed
	.venv/bin/ruff check harness
	.venv/bin/ruff format --check harness
	shellcheck -x -P harness harness/*.sh
	@if command -v k6 >/dev/null; then for p in spike step fixed; do \
	  k6 inspect -e BASE_URL=http://x harness/$$p.js >/dev/null && echo "k6 inspect $$p.js ok"; done; \
	else echo "k6 not installed: skipped k6 inspect"; fi

dry-local: ## laptop dry run of the full runner against `make dev` (spike, C1=10, 10x faster, ~80 s)
	PYTHON=$(HARNESS_PY) harness/run_experiment.sh --local $(LOCAL_URL) FAKE_LOCAL $$(date +%s) none spike \
	  C1=10 SPEED=10

lab-status: ## who holds the lab lock, and the ASG state
	@$(LOAD_ENV) && { aws s3 cp "s3://$$RESULTS_BUCKET/lab.lock" - 2>/dev/null || echo "lab lock: free"; } && \
	  aws autoscaling describe-auto-scaling-groups --auto-scaling-group-names "$$ASG_NAME" \
	    --query 'AutoScalingGroups[0].{min:MinSize,max:MaxSize,desired:DesiredCapacity,instances:length(Instances)}' \
	    --output table

lab-unlock: ## remove a stale lab lock (only after checking nobody is running!)
	@$(LOAD_ENV) && aws s3 cp "s3://$$RESULTS_BUCKET/lab.lock" - && \
	  read -r -p "Delete this lock? [y/N] " a && [ "$$a" = y ] && \
	  aws s3 rm "s3://$$RESULTS_BUCKET/lab.lock"

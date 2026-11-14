# Hotstar Scale Lab — top-level Makefile.
# Each owner keeps their targets in make/<area>.mk so two people never edit the same file
# (docs/TEAM_PLAN_3_PEOPLE.md §1.2).

SHELL := /bin/bash
.DEFAULT_GOAL := help

SHA ?= $(shell git rev-parse --short HEAD 2>/dev/null || echo dev)
PY  ?= .venv/bin/python

include $(sort $(wildcard make/*.mk))

.PHONY: help doctor
help: ## list targets
	@grep -hE '^[a-zA-Z0-9_-]+:.*## ' $(MAKEFILE_LIST) | sort | \
	  awk 'BEGIN{FS=":.*## "}{printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

doctor: ## check every required tool and its version
	@bash scripts/doctor.sh

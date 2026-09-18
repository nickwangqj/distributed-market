# distributed-market — task runner
#
# Conventions (see .claude/docs/08-deployment.md §11):
#   - every target is .PHONY; none produce a file of their own name
#   - `help` is the default goal, generated from the `##` comments below
#   - recipes stay one command per line; real multi-line logic lives in scripts/
#   - bash with `-eu -o pipefail`, so a failing command fails the target

SHELL := bash
.SHELLFLAGS := -eu -o pipefail -c
.DEFAULT_GOAL := help

VENV := .venv
PY := $(VENV)/bin/python
PIP := $(VENV)/bin/pip

# Which loop `smoke` runs against: compose (default) or kind.
TARGET ?= compose

# Phases that have not landed yet fail with a pointer rather than a confusing error.
define not_yet
@echo "make $(1): not implemented until Phase $(2)."
@echo "See .claude/docs/10-implementation-progress.md"
@exit 1
endef

.PHONY: help
help: ## Show this help
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

# --- Development ----------------------------------------------------------

.PHONY: venv
venv: ## Create .venv and install the project with dev extras
	test -d $(VENV) || python3 -m venv $(VENV)
	$(PIP) install --quiet --upgrade pip
	$(PIP) install --quiet -e ".[dev]"
	@echo "venv ready: source $(VENV)/bin/activate"

.PHONY: fmt
fmt: ## Format the code (ruff format)
	$(VENV)/bin/ruff format src tests scripts
	$(VENV)/bin/ruff check --fix src tests scripts

.PHONY: lint
lint: ## Check formatting and lint rules
	$(VENV)/bin/ruff format --check src tests scripts
	$(VENV)/bin/ruff check src tests scripts

.PHONY: typecheck
typecheck: ## Run mypy
	$(VENV)/bin/mypy

.PHONY: test
test: ## Unit, property, replay and service layers (fast)
	$(VENV)/bin/pytest || test $$? -eq 5   # exit 5 = no tests collected yet

.PHONY: test-all
test-all: ## Everything in `test`, plus the compose integration layer
	$(call not_yet,test-all,11)

# --- Inner loop: docker compose -------------------------------------------

.PHONY: build
build: ## Build the base image and all four service images
	docker build -f deploy/docker/Dockerfile.base -t dm-base:latest .
	docker compose build

.PHONY: up
up: build ## Start the venue under docker compose
	docker compose up -d --wait
	@echo "gateway    http://localhost:8080"
	@echo "marketdata http://localhost:8081"

.PHONY: down
down: ## Stop the compose stack and remove its containers
	docker compose down --remove-orphans

.PHONY: logs
logs: ## Tail all service logs
	docker compose logs -f

# --- Outer loop: kind -----------------------------------------------------

.PHONY: kind-up
kind-up: ## Create the kind cluster, load images, apply manifests
	$(call not_yet,kind-up,2)

.PHONY: kind-down
kind-down: ## Delete the kind cluster
	$(call not_yet,kind-down,2)

# --- Operating the venue --------------------------------------------------

.PHONY: seed
seed: ## Deposit fixture balances into the seeded accounts
	$(call not_yet,seed,8)

.PHONY: smoke
smoke: ## Assert the venue is standing end to end (TARGET=compose|kind)
	scripts/smoke.sh $(TARGET)

.PHONY: keys
keys: ## Generate a local data/config/api_keys.json (git-ignored)
	$(PY) scripts/make_api_keys.py

.PHONY: clean
clean: ## Remove generated runtime state (journal, snapshots, balances)
	rm -rf data/journal/* data/snapshots/* data/state/*
	@echo "runtime state cleared; .gitkeep files and data/config left untouched"

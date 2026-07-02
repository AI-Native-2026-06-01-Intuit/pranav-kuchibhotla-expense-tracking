SHELL := /usr/bin/env bash
.SHELLFLAGS := -eu -o pipefail -c

COMPOSE      ?= docker compose
ENV_FILE     := --env-file envs/expense.env
COMPOSE_FILES := $(ENV_FILE) -f compose.yaml -f compose.override.yaml
PROFILE_FILE  := -f compose.profiles.yaml
WAIT_TIMEOUT ?= 90

.DEFAULT_GOAL := help

.PHONY: help up down logs ps smoke dev test e2e clean nuke

help: ## Show available targets
	@awk 'BEGIN {FS = ":.*##"; printf "Targets:\n"} /^[a-zA-Z_-]+:.*##/ { printf "  %-8s %s\n", $$1, $$2 }' $(MAKEFILE_LIST)

up: ## Bring the base stack up and wait for healthy
	$(COMPOSE) $(COMPOSE_FILES) up -d --wait --wait-timeout $(WAIT_TIMEOUT)

down: ## Stop containers (keeps volumes)
	$(COMPOSE) $(COMPOSE_FILES) down --remove-orphans

logs: ## Tail logs for the base stack
	$(COMPOSE) $(COMPOSE_FILES) logs -f --tail 200

ps: ## Show container state
	$(COMPOSE) $(COMPOSE_FILES) ps

smoke: ## Run the end-to-end smoke test (per-invocation project)
	./scripts/smoke.sh

dev: ## Bring up the bind-mount dev service (requires: gradlew bootJar --continuous)
	$(COMPOSE) $(COMPOSE_FILES) --profile dev up -d expense-api-dev
	$(COMPOSE) $(COMPOSE_FILES) --profile dev logs -f expense-api-dev

test: ## Start the base stack and run the seed-fixtures profile
	$(COMPOSE) $(COMPOSE_FILES) $(PROFILE_FILE) --profile test up -d --wait --wait-timeout $(WAIT_TIMEOUT)

e2e: ## Bring the full end-to-end stack up (web + observability)
	$(COMPOSE) $(COMPOSE_FILES) $(PROFILE_FILE) --profile e2e up -d --wait --wait-timeout $(WAIT_TIMEOUT)

clean: ## Stop and remove containers + networks (keeps volumes)
	$(COMPOSE) $(COMPOSE_FILES) $(PROFILE_FILE) down --remove-orphans

nuke: ## Remove containers, volumes, and locally-built images
	$(COMPOSE) $(COMPOSE_FILES) $(PROFILE_FILE) down --volumes --remove-orphans --rmi local

# -*- Mode: Makefile -*-
ROOT_DIR := $(shell git rev-parse --show-toplevel)

PYTHON_VERSION := $(shell cat $(ROOT_DIR)/.python-version)
UV_RUN := uv run

.PHONY: clean lint mypy ruff-format formatting squeegee help uv-sync uv-lock uv-add uv-add-dev uv-upgrade

# The hook runs pre-commit through `uv run`, so it uses the `.venv` of
# whichever machine it runs on; `.git/hooks` is shared by every machine
# that syncs the checkout, so it holds no interpreter path.
#
.git/hooks/pre-commit: Makefile
	@mkdir -p $(@D)
	@printf '%s\n' '#!/usr/bin/env bash' \
	  'exec uv run --quiet pre-commit hook-impl --config=.pre-commit-config.yaml --hook-type=pre-commit --hook-dir "$$(cd "$$(dirname "$$0")" && pwd)" -- "$$@"' > $@
	@chmod +x $@
	@echo "pre-commit hook installed"

$(ROOT_DIR)/.venv: pyproject.toml uv.lock $(ROOT_DIR)/.python-version
	@uv sync
	@touch $@

.venv:: $(ROOT_DIR)/.venv

PY_DIRS := $(ROOT_DIR)/bofa_scraper/ $(ROOT_DIR)/tools/
PY_FILES=$(shell find $(PY_DIRS) -type f -name '*.py' 2>/dev/null)

.ruff_formatted: $(PY_FILES) .venv
	@$(UV_RUN) ruff format $(PY_DIRS)
	@touch .ruff_formatted

ruff-format: .ruff_formatted  ## Run `ruff format` over all Python files

formatting: ruff-format  ## Run formatters over all files in project

squeegee: .venv ruff-format mypy  ## Manually run ruff format, mypy, and ruff check over all project files
	@$(UV_RUN) ruff check $(PY_DIRS)

lint: .venv .git/hooks/pre-commit  ## Run all pre-commit hooks
	@$(UV_RUN) pre-commit run -a

mypy: .venv  ## Run `mypy` over `bofa_scraper/` and `tools/`
	@$(UV_RUN) mypy --install-types --non-interactive --explicit-package-bases ./bofa_scraper/ ./tools/

uv-sync: .venv  ## Sync .venv with uv.lock (run after updating pyproject.toml or pulling changes)
	@uv sync

uv-lock:  ## Update uv.lock file from pyproject.toml dependencies
	@uv lock

uv-add:  ## Add a new dependency (usage: make uv-add PACKAGE=requests)
	@if [ -z "$(PACKAGE)" ]; then \
		echo "Error: PACKAGE not specified. Usage: make uv-add PACKAGE=requests"; \
		exit 1; \
	fi
	@uv add $(PACKAGE)

uv-add-dev:  ## Add a new dev dependency (usage: make uv-add-dev PACKAGE=pytest)
	@if [ -z "$(PACKAGE)" ]; then \
		echo "Error: PACKAGE not specified. Usage: make uv-add-dev PACKAGE=pytest"; \
		exit 1; \
	fi
	@uv add --dev $(PACKAGE)

uv-upgrade:  ## Upgrade all dependencies to latest compatible versions
	@uv sync --upgrade

help:  ## Show this help.
	@grep -hE '^[A-Za-z0-9_ \-]*?:.*##.*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-30s\033[0m %s\n", $$1, $$2}'

clean::  ## Swab the decks! Does not touch docker images or volumes.
	@find $(ROOT_DIR) -name \*~ -exec rm '{}' +
	@find $(ROOT_DIR) -name \*.pyc -exec rm '{}' +
	@find $(ROOT_DIR) -name __pycache__ -prune -exec rm -fr '{}' +
	@find $(ROOT_DIR) -name .mypy_cache -prune -exec rm -fr '{}' +
	@rm -rf build bdist cover dist sdist distribute-* *.egg *.egg-info
	@rm -rf *.tar.gz junit.xml coverage.xml .cache
	@rm -rf .tox .eggs .ruff_formatted .ruff_cache
	@rm -rf venv* .venv
	@find $(ROOT_DIR) \( -name \*.orig -o -name \*.bak -o -name \*.rej \) -exec rm '{}' +
	@mkdir -p .mypy_cache

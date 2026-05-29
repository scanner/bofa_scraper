# -*- Mode: Makefile -*-
ROOT_DIR := $(shell git rev-parse --show-toplevel)

PYTHON_VERSION := 3.13
UV_RUN := uv run

.PHONY: clean lint mypy ruff-format formatting squeegee help uv-sync uv-lock uv-add uv-add-dev uv-upgrade

.git/hooks/pre-commit .git/hooks/pre-push: .venv
	@$(UV_RUN) pre-commit install
	@echo "pre-commit hooks installed!"
	@touch .git/hooks/pre-commit .git/hooks/pre-push

$(ROOT_DIR)/.venv: pyproject.toml uv.lock
	@uv sync
	@touch $@

.venv:: $(ROOT_DIR)/.venv

PY_FILES=$(shell find $(ROOT_DIR)/bofa_scraper/ -type f -name '*.py' 2>/dev/null)

.ruff_formatted: $(PY_FILES) .venv
	@$(UV_RUN) ruff format $(ROOT_DIR)/bofa_scraper/
	@touch .ruff_formatted

ruff-format: .ruff_formatted  ## Run `ruff format` over all Python files

formatting: ruff-format  ## Run formatters over all files in project

squeegee: .venv ruff-format mypy  ## Manually run ruff format, mypy, and ruff check over all project files
	@$(UV_RUN) ruff check $(ROOT_DIR)/bofa_scraper/

lint: .venv .git/hooks/pre-commit  ## Run all pre-commit hooks
	@$(UV_RUN) pre-commit run -a

mypy: .venv  ## Run `mypy` over `bofa_scraper/`
	@$(UV_RUN) mypy --install-types --non-interactive --explicit-package-bases ./bofa_scraper/

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

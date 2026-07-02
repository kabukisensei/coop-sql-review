# Canonical dev commands for coop-sql-review — see AGENTS.md "Commands (dev)".
# macOS/Linux (GNU make). Windows has no make: run the underlying commands,
# swapping .venv/bin/ -> .venv\Scripts\.
#
# NEVER `pip install -e .` here — the editable .pth is not processed on the
# Homebrew Python 3.14 venv; tests and the dev CLI use PYTHONPATH=src instead.

PY := .venv/bin/python
RUFF := .venv/bin/ruff
CORE_SRC ?= $(HOME)/Developer/coop-review-core/src

.PHONY: setup test test-local-core lint build release-check

setup:  ## create .venv, install deps (non-editable) + dev tools, activate git hooks
	python3 -m venv .venv
	$(PY) -m pip install --upgrade pip
	$(PY) -m pip install ".[dev]" build
	git config core.hooksPath .githooks
	@echo "python:    $$($(PY) --version)"
	@echo "hooksPath: $$(git config core.hooksPath)"
	@echo "setup: OK — run 'make test' next (expect all tests passing)"

test:  ## full suite against the INSTALLED coop-review-core (the normal run)
	PYTHONPATH=src $(PY) -m pytest -q

test-local-core:  ## full suite with LOCAL core edits shadowing the installed copy
	@test -d "$(CORE_SRC)" || { echo "FAIL: $(CORE_SRC) not found — clone coop-review-core there or pass CORE_SRC=<path>"; exit 1; }
	PYTHONPATH="$(CORE_SRC):$(CURDIR)/src" $(PY) -m pytest -q

lint:  ## ruff lint + format check (CI runs both — format --check is easy to forget)
	$(RUFF) check src tests
	$(RUFF) format --check src tests

build:  ## build the wheel exactly as publish.yml does
	$(PY) -m build --wheel

release-check:  ## version single-sourcing wiring + CHANGELOG entry + tag collision warning
	$(PY) scripts/release_check.py

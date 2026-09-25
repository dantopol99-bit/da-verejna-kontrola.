# Platforma veřejné kontroly – hlavní příkazy.
#   make test    – testy včetně podmínek nepublikování (shodí build)
#   make pilot   – celý pilot: stažení vzorků do raw, měření P1–P4, report
#   make gate    – kontrola publikačních podmínek nad výstupy

SHELL := /bin/bash
.DEFAULT_GOAL := help

export DATABASE_URL ?= postgresql://pvk:pvk@localhost:55432/pvk
export PVK_DATA_DIR ?= data

VENV := .venv
PY := $(VENV)/bin/python
STAMP := $(VENV)/.nainstalovano

.PHONY: help setup db migrate test lint gate pilot pilot-report db-stop

help:
	@echo "make setup   – virtuální prostředí (Python 3.12) a závislosti"
	@echo "make db      – spustí PostgreSQL (docker compose, případně lokální pg_ctl)"
	@echo "make migrate – aplikuje SQL migrace (schémata raw, core, ind)"
	@echo "make test    – všechny testy (vyžadují databázi)"
	@echo "make lint    – ruff"
	@echo "make gate    – publikační podmínky nad výstupy (docs/pilot_report.md, vystupy/)"
	@echo "make pilot   – pilot měření kvality dat (P1–P4) -> docs/pilot_report.md"

$(STAMP): pyproject.toml
	@if command -v uv >/dev/null 2>&1; then \
		uv venv --allow-existing --python 3.12 $(VENV) && \
		uv pip install --python $(PY) -e '.[dev]'; \
	else \
		python3.12 -m venv $(VENV) && $(PY) -m pip install -q --upgrade pip && \
		$(PY) -m pip install -q -e '.[dev]'; \
	fi
	@touch $(STAMP)

setup: $(STAMP)

db:
	@./scripts/db_up.sh

db-stop:
	docker compose stop db

migrate: setup db
	$(PY) -m pvk.db migrate

test: migrate
	$(PY) -m pytest

lint: setup
	$(PY) -m ruff check src tests

gate: setup
	$(PY) -m pvk.publikace

pilot: migrate
	$(PY) -m pvk.pilot vse
	$(PY) -m pvk.publikace

# Jen přegeneruje report z již stažených dat (bez sítě)
pilot-report: migrate
	$(PY) -m pvk.pilot report
	$(PY) -m pvk.publikace

# caio-code — único ponto de entrada para setup, teste, lint e PR.
# Funciona em Linux, macOS e Windows (Git Bash / runners do GitHub).

SHELL := /bin/sh

ifeq ($(OS),Windows_NT)
  VENV_BIN := .venv/Scripts
  PY_BOOT  := python
else
  VENV_BIN := .venv/bin
  PY_BOOT  ?= python3
endif

PY      := $(VENV_BIN)/python
PYTEST  := $(PY) -m pytest
RUFF    := $(PY) -m ruff

.DEFAULT_GOAL := help

.PHONY: help setup setup-ci test test-changed test-unit smoke lint format check \
        clean hooks pr stack-new linear-status install

help: ## Mostra os alvos disponíveis
	@printf "caio-code\n\n"
	@awk 'BEGIN {FS = ":.*## "} /^[a-zA-Z_-]+:.*## / {printf "  %-14s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

setup: ## Cria .venv, instala dependências e os git hooks
	$(PY_BOOT) -m venv .venv
	$(PY) -m pip install --upgrade pip
	$(PY) -m pip install -e ".[dev]"
	$(PY) scripts/install_hooks.py
	@echo "Ambiente pronto. Rode 'make test'."

setup-ci: ## Setup enxuto para CI (sem venv, o runner já tem Python)
	$(PY_BOOT) -m pip install --upgrade pip
	$(PY_BOOT) -m pip install -e ".[dev]"

test: ## Suíte completa de testes unitários
	$(PYTEST) tests

test-unit: test ## Alias de test

test-changed: ## Testa apenas os módulos alterados (mesma lógica do CI de PR)
	$(PY) scripts/ci/changed_tests.py --run

smoke: ## Teste de fumaça ponta a ponta, offline
	$(PY) scripts/smoke.py

lint: ## ruff check
	$(RUFF) check src tests scripts

format: ## ruff format
	$(RUFF) format src tests scripts
	$(RUFF) check --fix src tests scripts

check: lint test ## Lint + testes

install: ## Instala o pacote no ambiente atual
	$(PY_BOOT) -m pip install -e ".[dev]"

hooks: ## (Re)instala os git hooks
	$(PY_BOOT) scripts/install_hooks.py

pr: ## Abre PR para a base correta (CARD=CM-12)
	@test -n "$(CARD)" || (echo "uso: make pr CARD=CM-12" && exit 1)
	$(PY_BOOT) scripts/ci/open_pr.py --card "$(CARD)"

stack-new: ## Cria branch empilhada (NAME=slug CARD=CM-12 [BASE=main])
	@test -n "$(NAME)" || (echo "uso: make stack-new NAME=slug CARD=CM-12" && exit 1)
	@test -n "$(CARD)" || (echo "uso: make stack-new NAME=slug CARD=CM-12" && exit 1)
	$(PY_BOOT) scripts/ci/open_pr.py --stack --name "$(NAME)" --card "$(CARD)" --base "$(or $(BASE),main)"

linear-status: ## Mostra o card ativo no Linear
	$(PY_BOOT) scripts/linear.py issues --project "$$LINEAR_PROJECT_ID"

clean: ## Remove .venv, caches e artefatos
	$(PY_BOOT) -c "import shutil,pathlib; [shutil.rmtree(p, ignore_errors=True) for p in ['.venv','.pytest_cache','.ruff_cache','build','dist']]; [p.unlink() for p in pathlib.Path('.').rglob('*.egg-info') if p.is_file()]" || true
	$(PY_BOOT) -c "import shutil,pathlib; [shutil.rmtree(p, ignore_errors=True) for p in pathlib.Path('.').rglob('__pycache__')]"
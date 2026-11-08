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
        clean hooks pr stack-new linear-status install tui drive dataset evaluate \
        evaluate-live layering summarize \
        datagen-setup datagen-plan datagen-generate datagen-build \
        evaluate-live-128k \
        evaluate-replay-stub evaluate-replay-pilot evaluate-replay-live

help: ## Mostra os alvos disponíveis
	@printf "caio-code\n\n"
	@awk 'BEGIN {FS = ":.*## "} /^[a-zA-Z0-9_-]+:.*## / {printf "  %-22s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

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
	$(RUFF) check src tests scripts datagen/scripts

format: ## ruff format
	$(RUFF) format src tests scripts datagen/scripts
	$(RUFF) check --fix src tests scripts datagen/scripts

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

tui: ## Abre a TUI (provedor stub por padrão; PROVIDER=openai_compatible para modelo real)
	CAIO_CODE_PROVIDER=$(or $(PROVIDER),stub) $(PY) -m caio_code tui --root $(or $(ROOT),.)

drive: ## Roda todos os cenários do driver headless da TUI em .reports/tui
	$(PY) -m caio_code.presentation.tui.driver --scenario all --reports-dir .reports/tui --json .reports/tui/report.json --markdown .reports/tui/report.md

dataset: ## Regenera o dataset de avaliação e prova o determinismo (sha256)
	$(PY) evals/generate_dataset.py
	$(PY) evals/generate_dataset.py --out .reports/dataset/determinism-a
	$(PY) evals/generate_dataset.py --out .reports/dataset/determinism-b
	diff -r .reports/dataset/determinism-a .reports/dataset/determinism-b
	find .reports/dataset/determinism-a -name '*.json' | sort | xargs sha256sum
	@echo "dataset determinístico: mesmos bytes nas duas gerações"

evaluate: ## Roda o experimento (11 braços) com o provedor stub — offline
	CAIO_CODE_PROVIDER=stub $(PY) -m caio_code evaluate

# Condições do run autoritário (chapter4-main-v4). O timeout de 420 s não é
# cosmético: com o default de 120 s, 20 trials morrem em APITimeoutError e a
# falha cai desigualmente sobre os braços, o que invalida a comparação
# (ver .reports/evals/README.md, runs chapter4-main e chapter4-main-v3).
EVAL_TIMEOUT ?= 420
EVAL_RETRIES ?= 2  # 2 retries: o resumidor de 40k+ tokens pode estourar timeout
EVAL_CONCURRENCY ?= 5
EVAL_RUN_ID ?= chapter4-main-live

evaluate-live: ## Roda o experimento contra o provedor real (exige OPENAI_API_KEY; CUSTA DINHEIRO)
	@test -n "$$OPENAI_API_KEY" -o -f .env || (echo "evaluate-live exige OPENAI_API_KEY (ambiente ou .env)" && exit 1)
	@echo "AVISO: evaluate-live chama um endpoint real e gera custo em USD por trial."
	CAIO_CODE_PROVIDER=openai_compatible \
	CAIO_CODE_TIMEOUT_SECONDS=$(EVAL_TIMEOUT) \
	CAIO_CODE_MAX_RETRIES=$(EVAL_RETRIES) \
	CAIO_CODE_DECISION_TIMEOUT_SECONDS=180 \
	$(PY) -m caio_code evaluate --concurrency $(EVAL_CONCURRENCY) \
		--out .reports/evals --run-id $(EVAL_RUN_ID) $(EVAL_ARGS)

layering: ## Regra de dependência, determinismo e números só em config.py
	$(PYTEST) tests/test_layering.py

# ---------------------------------------------------------------------------
# Run do Capítulo 4 com o dataset de 128k e janela declarada de 32k.
#
# O timeout sobe de 420 s para 900 s de propósito: o `baseline_full_history`
# agora envia ~129k proxy tokens (~186k reais) por chamada, e um timeout curto
# demais mata trials desigualmente entre os braços — exatamente a falha que
# invalidou `chapter4-main` e `chapter4-main-v3` (ver .reports/evals/README.md).
# Latência correlaciona com tokens de SAÍDA (r=+0.86 no v4), não de entrada
# (r=-0.10), então a margem extra é seguro barato, não ajuste fino.
# ---------------------------------------------------------------------------
EVAL_DATASET_128K ?= evals/datasets/long_histories_128k
EVAL_WINDOW_128K ?= 32000
EVAL_TIMEOUT_128K ?= 900
EVAL_RUN_ID_128K ?= chapter4-32k-128k

evaluate-live-128k: ## Experimento live: dataset 128k, janela 32k (CUSTA ~US$ 21)
	@test -d $(EVAL_DATASET_128K) || (echo "dataset ausente: $(EVAL_DATASET_128K) (rode make datagen-build)" && exit 1)
	@test -n "$$OPENAI_API_KEY" -o -f .env || (echo "evaluate-live-128k exige OPENAI_API_KEY (ambiente ou .env)" && exit 1)
	@echo "AVISO: 165 trials contra endpoint real; custo estimado ~US$$ 21 (US$$ 26 no pior caso)."
	CAIO_CODE_PROVIDER=openai_compatible \
	CAIO_CODE_EVAL_DATASET=$(EVAL_DATASET_128K) \
	CAIO_CODE_TIMEOUT_SECONDS=$(EVAL_TIMEOUT_128K) \
	CAIO_CODE_MAX_RETRIES=$(EVAL_RETRIES) \
	CAIO_CODE_DECISION_TIMEOUT_SECONDS=300 \
	$(PY) -m caio_code evaluate --window-tokens $(EVAL_WINDOW_128K) \
		--concurrency $(EVAL_CONCURRENCY) \
		--out .reports/evals --run-id $(EVAL_RUN_ID_128K) $(EVAL_ARGS)

# ---------------------------------------------------------------------------
# Chat-replay evaluation (Chapter 4, v5): seed -> shape once -> probe in-band
# -> LLM judge. Matrix: 5 arms x 5 cases x 2 variants (full/spill) x 1 rep =
# 50 trials (temperature 0.0; no pass^k claim). Declared window 40k, below the
# smallest case in BOTH variants (spill min 41.6k, full min 114k proxy tokens),
# so the seeded history always overflows and the shaping step always fires.
# Cache hit is NOT measured in replay; the report omits the column on purpose.
# ---------------------------------------------------------------------------
REPLAY_DATASET ?= evals/datasets/long_histories_128k
REPLAY_WINDOW ?= 40000
REPLAY_TIMEOUT ?= 900
REPLAY_VARIANTS ?= full,spill
REPLAY_ARMS ?= baseline_full_history,sliding_window,message_selection,anchored_compaction,message_selection_decision
REPLAY_RUN_ID ?= chapter4-main-v5

evaluate-replay-stub: ## Chat-replay com o provedor stub — offline (compactação não valida; ver evals/AGENTS.md)
	CAIO_CODE_PROVIDER=stub $(PY) -m caio_code evaluate --variants $(REPLAY_VARIANTS)

evaluate-replay-pilot: ## Piloto live do chat-replay: 1 caso x 5 braços x 2 variantes x 1 rep (~US$$ 5)
	@test -d $(REPLAY_DATASET) || (echo "dataset ausente: $(REPLAY_DATASET) (rode make datagen-build)" && exit 1)
	@test -n "$$OPENAI_API_KEY" -o -f .env || (echo "evaluate-replay-pilot exige OPENAI_API_KEY (ambiente ou .env)" && exit 1)
	@echo "AVISO: 10 trials contra endpoint real; custo estimado ~US$$ 5."
	CAIO_CODE_PROVIDER=openai_compatible \
	CAIO_CODE_EVAL_DATASET=$(REPLAY_DATASET) \
	CAIO_CODE_TIMEOUT_SECONDS=$(REPLAY_TIMEOUT) \
	CAIO_CODE_MAX_RETRIES=$(EVAL_RETRIES) \
	CAIO_CODE_DECISION_TIMEOUT_SECONDS=300 \
	$(PY) -m caio_code evaluate --window-tokens $(REPLAY_WINDOW) \
		--variants $(REPLAY_VARIANTS) --arms $(REPLAY_ARMS) \
		--cases 1 --repetitions 1 --concurrency $(EVAL_CONCURRENCY) \
		--out .reports/evals --run-id $(REPLAY_RUN_ID)-pilot $(EVAL_ARGS)

evaluate-replay-live: ## Chat-replay live: 50 trials, dataset 128k, janela 40k (CUSTA ~US$$ 15-30)
	@test -d $(REPLAY_DATASET) || (echo "dataset ausente: $(REPLAY_DATASET) (rode make datagen-build)" && exit 1)
	@test -n "$$OPENAI_API_KEY" -o -f .env || (echo "evaluate-replay-live exige OPENAI_API_KEY (ambiente ou .env)" && exit 1)
	@echo "AVISO: 50 trials contra endpoint real; custo estimado US$$ 15-30. Rode o piloto antes."
	CAIO_CODE_PROVIDER=openai_compatible \
	CAIO_CODE_EVAL_DATASET=$(REPLAY_DATASET) \
	CAIO_CODE_TIMEOUT_SECONDS=$(REPLAY_TIMEOUT) \
	CAIO_CODE_MAX_RETRIES=$(EVAL_RETRIES) \
	CAIO_CODE_DECISION_TIMEOUT_SECONDS=300 \
	$(PY) -m caio_code evaluate --window-tokens $(REPLAY_WINDOW) \
		--variants $(REPLAY_VARIANTS) --arms $(REPLAY_ARMS) \
		--repetitions 1 --concurrency $(EVAL_CONCURRENCY) \
		--out .reports/evals --run-id $(REPLAY_RUN_ID) $(EVAL_ARGS)

summarize: ## Imprime as tabelas do experimento mais recente (RUN=chapter4-main)
	$(PY) scripts/summarize_experiment.py $(if $(RUN),--run $(RUN),)

# ---------------------------------------------------------------------------
# datagen/ — dataset sintético gerado com NeMo Data Designer (venv isolado).
# O dataset congelado antigo (evals/datasets/long_histories) continua sendo
# regenerado por `make dataset`; estes alvos produzem long_histories_128k.
# ---------------------------------------------------------------------------

DATAGEN_PY := datagen/.venv/bin/python
DATAGEN_CFG := datagen/configs/long_histories_128k.json
DATASET_128K := evals/datasets/long_histories_128k

datagen-setup: ## Cria o venv isolado do datagen e registra provider/modelos
	@test -n "$$OPENAI_API_KEY" -a -n "$$OPENAI_BASE_URL" || \
		(echo "datagen-setup exige OPENAI_API_KEY e OPENAI_BASE_URL (set -a && . ../../.env && set +a)" && exit 1)
	@test -d datagen/.venv || (cd datagen && $(PY_BOOT) -m venv .venv && \
		.venv/bin/python -m pip install --upgrade pip && \
		.venv/bin/python -m pip install data-designer)
	cd datagen && .venv/bin/python scripts/setup_models.py

datagen-plan: ## Mostra o plano de geração e o custo estimado (não gasta nada)
	$(DATAGEN_PY) datagen/scripts/generate.py --config $(DATAGEN_CFG) --dry-run

datagen-generate: ## Gera os blocos com Data Designer (CUSTA DINHEIRO; use CASE= para um caso)
	@test -n "$$OPENAI_API_KEY" -a -n "$$OPENAI_BASE_URL" || \
		(echo "datagen-generate exige OPENAI_API_KEY e OPENAI_BASE_URL" && exit 1)
	@echo "AVISO: datagen-generate chama um endpoint real para cada bloco gerado."
	$(DATAGEN_PY) datagen/scripts/generate.py --config $(DATAGEN_CFG) $(if $(CASE),--case $(CASE),) $(if $(SET),--set $(SET),) $(if $(SCALE),--scale $(SCALE),)

datagen-build: ## Converte os blocos em dataset e aplica o portão de qualidade
	$(DATAGEN_PY) datagen/scripts/convert.py --config $(DATAGEN_CFG) $(if $(CASE),--case $(CASE),)
	$(DATAGEN_PY) datagen/scripts/validate.py --config $(DATAGEN_CFG) --dataset-dir $(DATASET_128K)

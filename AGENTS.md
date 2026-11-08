# CLAUDE.md — caio-code

> **Regra zero — este arquivo é a memória do repositório.** Toda sessão nova começa lendo
> isto. Se ele ficar desatualizado, a próxima sessão refaz trabalho ou desfaz uma decisão
> deliberada. Ao terminar qualquer tarefa, atualize a seção afetada **antes** de considerar a
> tarefa concluída.
>
> `AGENTS.md` é o arquivo canônico; `CLAUDE.md` é um **symlink** para ele. Edite sempre
> `AGENTS.md`; nunca substitua o symlink por uma cópia. A mesma regra vale em cada subpasta.

`caio-code` é o agente de codificação desenvolvido na Parte III do TCC *Context Is All You
Need*. Ele vive dentro de `~/tcc/` por conveniência, mas é um **repositório git independente**,
ignorado pelo repositório da monografia. Nada aqui é versionado pelo TCC, e o texto do TCC não
é editado a partir daqui.

---

## 1. O que este repositório é

O produto é um agente de codificação autônomo em Python (pacote `caio_code`) construído sobre
**deepagents/LangChain** (ADR 0002) e organizado em camadas **DDD** (ADR 0003). Ele integra
técnicas de engenharia de contexto para tarefas longas em repositórios grandes. A tese que o
agente encarna:

> A gestão explícita do contexto — janela, seleção e compactação — é o que permite a um agente
> de longa duração continuar coerente quando o histórico não cabe mais na janela do modelo.

O agente é o protótipo descrito no Capítulo 3 e é **medido por um experimento** de onze braços
(§7) cujos números alimentam o Capítulo 4. Ele **não** é uma biblioteca genérica, um framework
para terceiros, nem um produto comercial. Escopo vale mais que generalidade.

### Camadas e regra de dependência

```
presentation ──▶ application ──▶ domain ◀── infrastructure
```

- `domain` não importa nada do pacote (exceção única: `caio_code.config`, onde vivem os
  números). É dados e funções puras: políticas de contexto, mensagens, resumo ancorado,
  eventos, erros tipados, contabilidade de uso, avaliação.
- `application` contém os casos de uso (runner do agente, compactação, experimento, todos,
  guardrail, seleção, ledger) e importa `domain`.
- `infrastructure` implementa as portas de `domain/ports` (LLM, tokens, tools, persistência,
  datasets, observabilidade, mappers LangChain, middleware) e importa `domain` — mais
  `application` somente onde um caso de uso é orquestrado.
- `presentation` (CLI e TUI) importa `application` + `domain`; `infrastructure` só aparece na
  raiz de composição do CLI (`presentation/cli/composition.py`) e, de forma delimitada, no
  runner e no driver da TUI (relógios).

O loop agêntico em si pertence ao deepagents; o objeto de estudo da tese são as **políticas de
contexto que o middleware aplica** a cada chamada de modelo (ADR 0002). Decisões são aplicadas
**por índice** sobre as mensagens originais do provedor, preservando identidade de objeto para
o prompt caching (ADR 0003). A direção dos imports é verificada por AST em `tests/test_layering.py`: cruzou a regra, o CI
falha. O mesmo teste proíbe relógio de parede e aleatoriedade fora de
`infrastructure/observability/clocks.py`, e impede que um limite medido no Capítulo 4 apareça
inline em vez de vir de `config.py`.

---

## 2. Skills e o roteador `/tcc`

O entrypoint de trabalho é a skill `tcc`. Um `/tcc <pedido>` lê o pedido, escolhe a skill
adequada e a carrega. O roteador não executa trabalho por conta própria.

| Skill | Carrega quando |
|---|---|
| `.claude/skills/tcc/SKILL.md` | sempre — é o roteador |
| `.claude/skills/tcc-foundations/SKILL.md` | escrever/revisar código do agente, decidir camada, config ou teste |
| `.claude/skills/tcc-bug-investigation/SKILL.md` | bug, teste falhando, comportamento estranho, regressão |
| `.claude/skills/tcc-research-writing/SKILL.md` | pesquisa, evidência, capítulo do TCC, citação, redação |
| `.claude/skills/tcc-pr-review/SKILL.md` | abrir PR, revisar diff, decidir merge |

Atalhos: `/tcc rules`, `/tcc bug`, `/tcc pr <n>`, `/tcc cap <n>`, `/tcc status`.

---

## 3. Estrutura (profundidade máxima)

```
caio-code/
├── AGENTS.md                        # este arquivo (CLAUDE.md é symlink)
├── FEATURE_TREE.md                  # árvore de funcionalidades + diagramas de fluxo
├── Makefile                         # ÚNICO ponto de entrada para setup, teste, lint, PR
├── README.md                        # quick start e mapa da documentação
├── pyproject.toml                   # empacotamento, dependências, ruff, pytest
├── .env.example                     # nomes das variáveis (valores nunca versionados)
├── .claude/
│   ├── AGENTS.md                    # invariantes das skills e dos hooks
│   ├── settings.json                # hooks SessionEnd e permissões
│   ├── agents/                      # tcc-{researcher,verifier,writer,editor,reviewer}.md
│   ├── commands/                    # tcc.md, tcc-status.md
│   ├── hooks/                       # session-end.sh, worker.py (headless)
│   └── skills/                      # tcc (roteador), tcc-foundations, tcc-bug-investigation,
│                                    # tcc-research-writing, tcc-pr-review
├── .githooks/pre-push               # branch atualizada + proibição de push direto na main
├── .github/workflows/               # pr-tests.yml, main-tests.yml, smoke.yml
├── docs/
│   ├── AGENTS.md                    # regras de documentação e formato de ADR
│   ├── linear-workflow.md           # cards, subtarefas, stack de PRs
│   └── adr/
│       ├── 0001-estrutura-em-camadas.md        # (superado por 0002/0003)
│       ├── 0002-deepagents-como-loop.md        # adoção do deepagents/LangChain
│       ├── 0003-camadas-ddd.md                 # DDD e a regra de dependência
│       ├── 0004-medicoes-do-experimento.md     # cauda verbatim, structure repair, cache/custo
│       └── 0005-modelo-de-decisao-typesafe.md  # Jev atrás da porta de decisão
├── evals/
│   ├── AGENTS.md                    # contrato de determinismo do dataset
│   ├── generate_dataset.py          # gerador determinístico dos cinco casos
│   ├── prompts/
│   │   └── judge_v1.md              # prompt do juiz LLM, versionado (revisão = novo arquivo)
│   └── datasets/long_histories/     # dataset CONGELADO e versionado
│       ├── dataset.json             # manifesto (name, seed, generator, cases)
│       └── case-0{1..5}-*.json      # cinco históricos longos com fatos e sondas
├── datagen/                         # dataset sintético via NeMo Data Designer (venv isolado)
│   ├── AGENTS.md                    # divisão conteúdo/estrutura e o contrato hash-pinned
│   ├── configs/providers.yaml       # provider + model aliases (nome da env, nunca o valor)
│   ├── configs/long_histories_128k.json  # o build config: casos, alvos, prompts, limites
│   ├── scripts/setup_models.py      # registra provider/aliases (idempotente)
│   ├── scripts/generate.py          # data-designer create por (caso, conjunto); --dry-run estima custo
│   ├── scripts/convert.py           # blocos -> HistoryCase: impõe TODA a estrutura, deterministicamente
│   ├── scripts/validate.py          # portão de qualidade + BUILDINFO.json (sha256, procedência)
│   └── output/                      # artefatos brutos (gitignored)
├── scripts/
│   ├── AGENTS.md
│   ├── ci/changed_tests.py          # diff → testes das pastas alteradas
│   ├── ci/pr_size.py                # 5–20 arquivos por PR
│   ├── ci/open_pr.py                # branch empilhada / abertura de PR
│   ├── install_hooks.py             # core.hooksPath = .githooks
│   ├── linear.py                    # cliente GraphQL do Linear (stdlib)
│   └── smoke.py                     # smoke test offline, multiplataforma
├── src/caio_code/
│   ├── __init__.py                  # __version__ do pacote
│   ├── __main__.py                  # python -m caio_code → presentation.cli.main
│   ├── config.py                    # TODAS as dataclasses de configuração, PRICE_SHEET,
│   │                                # load_settings()/load_endpoints(); nada de número mágico
│   ├── domain/                      # núcleo puro: sem SDK, sem I/O, sem relógio
│   │   ├── errors.py                # erros tipados (CaioCodeError e subclasses)
│   │   ├── events.py                # DomainEvent, EventBus, InMemoryEventBus
│   │   ├── conversation/
│   │   │   ├── budget.py            # TokenBudget, ContextLimit, WindowPressure
│   │   │   ├── messages.py          # Role, ToolCall, Message, Transcript (imutáveis)
│   │   │   ├── rendering.py         # transcript → texto indexado para o summarizer
│   │   │   └── summary.py           # resumo ancorado: 5 seções, template, parse tolerante
│   │   ├── evaluation/
│   │   │   ├── cases.py             # CriticalFact, Probe, HistoryCase (variant, SpillFile), EvalDataset
│   │   │   ├── scoring.py           # TrialResult (variant, replay), pass^k, ArmAggregate, ExperimentReport
│   │   │   └── spill.py             # derivação pura da variante `spill` (truncagem -> arquivo)
│   │   ├── policy/
│   │   │   ├── base.py              # ContextPolicy, PolicyRequest/Decision, PolicyPipeline
│   │   │   ├── compaction.py        # CompactionPlanner, tail_boundary (ADR 0004a)
│   │   │   ├── full_history.py      # baseline: mantém tudo, reporta o estouro
│   │   │   ├── message_selection.py # retenção por relevância (scores injetados)
│   │   │   ├── sliding_window.py    # sufixo mais recente que cabe no budget
│   │   │   ├── structure_repair.py  # re-pareia tool calls/resultados órfãos (ADR 0004b)
│   │   │   └── tool_output.py       # truncate_text: teto de linhas/bytes, head+tail
│   │   ├── ports/                   # contratos que infrastructure implementa
│   │   │   ├── gateway.py           # ModelGateway, ModelReply
│   │   │   ├── scorer.py            # RelevanceScorer, ScoredMessage
│   │   │   ├── storage.py           # TranscriptStore, ResultStore, ResultRecord
│   │   │   ├── summarizer.py        # Summarizer, SummaryResult
│   │   │   ├── time.py              # Clock, IdentifierFactory (injetados, sempre)
│   │   │   └── tokenizer.py         # TokenCounter (a única contagem de tokens)
│   │   ├── todo/items.py            # TodoStatus, TodoItem, TodoBoard (1 in_progress máx.)
│   │   └── usage/accounting.py      # TokenUsage, CacheStats, Cost (Decimal), PriceSheet,
│   │                                # RunAccounting, UsageLedger
│   ├── application/                 # casos de uso; importa domain (+ infrastructure no runner)
│   │   ├── agent/
│   │   │   ├── bridges.py           # portas estruturais + fallbacks offline dos colaboradores
│   │   │   ├── facade.py            # AgentSessionFacade → protocolo AgentFacade da TUI
│   │   │   ├── prompt.py            # build_system_prompt (papel, tools, todos, contexto)
│   │   │   ├── runner.py            # AgentDependencies + AgentRunner (grafo deepagents, stream)
│   │   │   ├── session.py           # ContextSnapshot, AgentRunResult (as_record())
│   │   │   └── stub_model.py        # StubChatModel: BaseChatModel roteirizado e offline
│   │   ├── compaction/service.py    # CompactionService: plan → summarize → replace → account
│   │   ├── evaluation/              # chat-replay do Capítulo 4 (v5)
│   │   │   ├── judge.py             # LlmJudge: nota binária + portão de calibração (>=90%)
│   │   │   ├── replay.py            # ChatReplayRunner: seed → molda 1x → sondas in-band → juiz
│   │   │   ├── replay_report.py     # results.json + report.md (coluna variant, SEM cache) + comparison
│   │   │   └── replay_tools.py      # servidor de tools do replay: gravadas + spill + miss tipado
│   │   ├── experiment/
│   │   │   ├── arms.py              # os 11 braços (ArmSpec, default_arms, select_arms)
│   │   │   ├── report.py            # results.json + report.md por run
│   │   │   └── runner.py            # ExperimentRunner: arms × cases × repetitions
│   │   ├── guardrails/repeated_tool_call.py  # RepeatedToolCallGuard (loop de tool idêntica)
│   │   ├── metrics/ledger.py        # RunLedger: usage/custo via eventos do bus
│   │   ├── selection/service.py     # SelectionService: task → scores por mensagem
│   │   └── todos/service.py         # TodoTracker: write_todos → TodoBoard validado
│   ├── infrastructure/              # adaptadores das portas do domínio
│   │   ├── datasets/
│   │   │   ├── codec.py             # JSON dos casos de avaliação (DatasetError)
│   │   │   └── loader.py            # load_dataset, describe (tabela do Capítulo 4)
│   │   ├── decision/                # modelo de decisão TypeSafe Jev (ADR 0005)
│   │   │   ├── factory.py           # build_decision_model/build_decision_scorer
│   │   │   ├── risk.py              # DecisionRiskAdvisor (consultivo, nunca bloqueia)
│   │   │   ├── scorer.py            # DecisionRelevanceScorer (um Noul por mensagem)
│   │   │   ├── stub.py              # StubDecisionModel (hash estável, offline)
│   │   │   └── typesafe.py          # TypeSafeDecisionModel sobre TypeSafeClassifier
│   │   ├── llm/
│   │   │   ├── factory.py           # build_gateway/build_summarizer/build_scorer
│   │   │   ├── openai_compatible.py # gateway/summarizer/scorer via SDK openai
│   │   │   └── stub.py              # StubGateway/StubSummarizer/StubScorer (testes e CI)
│   │   ├── mappers/langchain.py     # Message ↔ BaseMessage; apply_decision POR ÍNDICE
│   │   ├── middleware/context_policy.py  # ContextPolicyMiddleware: pipeline a cada model call
│   │   ├── observability/
│   │   │   ├── bus.py               # EventRecorder, to_record, JsonlEventHandler
│   │   │   ├── clocks.py            # SystemClock (raiz de composição), FixedClock,
│   │   │   │                        # SequentialIdentifiers
│   │   │   └── langsmith.py         # tracing opt-in; chave nunca impressa
│   │   ├── persistence/
│   │   │   ├── codec.py             # envelope JSON versionado de transcripts
│   │   │   └── jsonl.py             # JsonlResultStore (fsync), JsonTranscriptStore (atômico)
│   │   ├── pricing/sheet.py         # pricing_for/cost_of/accounting_for (números em config)
│   │   ├── tokens/counter.py        # CharProxyTokenCounter (padrão/CI), TiktokenCounter
│   │   └── tools/
│   │       ├── _guard.py            # ToolError → texto estruturado para o modelo
│   │       ├── deepagents_backend.py# FilesystemBackend (raiz real) | StateBackend (eval)
│   │       ├── filesystem.py        # FilesystemToolset: read/write/edit/list/glob
│   │       ├── sandbox.py           # Sandbox: confinamento de caminho (SandboxEscapeError)
│   │       ├── search.py            # SearchToolset: grep/find só com stdlib
│   │       └── shell.py             # ShellToolset: argv via subprocess.run, nunca shell=True
│   └── presentation/
│       ├── cli/
│       │   ├── main.py              # argparse; único leitor de sys.argv / stdout / exit code
│       │   ├── composition.py       # raiz de composição: Settings → AgentDependencies → runner
│       │   ├── formatting.py        # formatação pura (métricas, JSON)
│       │   └── commands/            # run.py, tui.py, compact.py, evaluate.py, doctor.py
│       └── tui/
│           ├── app.py               # CaioCodeApp: eventos → widgets; keybindings
│           ├── ports.py             # protocolo AgentFacade (único canal UI ↔ agente)
│           ├── scripted.py          # ScriptedFacade: fachada offline para testes/driver/demo
│           ├── theme.py             # cores, tamanhos, CSS (nenhum literal visual em widget)
│           ├── widgets/             # message_list.py, composer.py, todo_sidebar.py,
│           │                        # usage_footer.py, tool_panel.py
│           └── driver/              # driver headless (Pilot do Textual)
│               ├── __main__.py      # python -m caio_code.presentation.tui.driver
│               ├── cli.py           # parsing de flags, exit codes (0/1/2)
│               ├── pilot_driver.py  # TuiDriver: passos → run_test(headless=True)
│               ├── scenarios.py     # SCENARIOS: smoke, todo_sidebar, compaction, interrupt, demo
│               ├── steps.py         # passos tipados + parser de script texto
│               ├── report.py        # DriverReport, StepRecord, JSON/Markdown
│               ├── text.py          # screen_text/widget_text para asserções
│               └── errors.py        # DriverError e subclasses tipadas
├── tests/                           # espelha src/ (mesmos caminhos); offline por contrato
│   ├── test_repo_layout.py          # convenções: AGENTS.md + symlink, skills, FEATURE_TREE.md
│   ├── application/
│   │   ├── agent/                   # test_{facade,prompt,runner,session,stub_model}.py
│   │   ├── evaluation/              # test_{replay,replay_tools,judge}.py (chat-replay offline)
│   │   └── {compaction,experiment,guardrails,metrics,selection,todos}/
│   ├── domain/
│   │   ├── conversation/            # test_rendering_and_summary.py
│   │   ├── evaluation/              # test_spill.py (derivação da variante spill)
│   │   └── policy/                  # test_compaction.py, test_pipeline_and_policies.py,
│   │                                # test_structure_repair.py
│   ├── evals/                       # test_generate_dataset.py (determinismo do gerador)
│   ├── infrastructure/
│   │   ├── datasets/                # test_dataset_{codec,loader}.py, test_committed_dataset.py
│   │   ├── decision/                # test_{factory,risk,scorer,stub,typesafe}.py
│   │   ├── llm/                     # test_{factory,openai_compatible,stub}.py
│   │   ├── mappers/                 # test_langchain.py
│   │   ├── middleware/              # ContextPolicyMiddleware (pasta criada, sem testes ainda)
│   │   ├── observability/           # test_{bus,clocks,langsmith}.py
│   │   ├── persistence/             # test_{codec,jsonl}.py
│   │   ├── pricing/                 # test_sheet.py
│   │   └── tools/                   # test_{sandbox,filesystem,shell,search,deepagents_backend}.py
│   └── presentation/
│       ├── cli/                     # test_{main,run,tui,compact,evaluate,doctor}.py
│       └── tui/                     # test_{app,ports,scripted,composer,message_list,
│                                    # todo_sidebar,usage_footer}.py + driver/test_*.py
└── .reports/                        # artefatos versionados, sem segredos
    ├── evals/<run_id>/              # results.json + report.md do experimento
    ├── bugs/                        # relatórios de investigação
    └── session-end/                 # logs dos hooks (efêmeros, gitignored exceto .gitkeep)
```

Os diretórios `tests/context`, `tests/harness`, `tests/providers`, `tests/state`,
`tests/tools` e `tests/scripts` são resíduo do layout antigo (contêm só `__init__.py`);
a remoção é pendência (§11).

Cada pasta de módulo tem o seu próprio `AGENTS.md` e `CLAUDE.md` (symlink). Eles descrevem
invariantes locais e são atualizados no mesmo PR que muda a pasta. `tests/test_repo_layout.py`
verifica a convenção; quebrá-la falha o CI.

---

## 4. Regras que valem para todo o código

1. **Determinismo.** `time.time()`, `datetime.now()`, `random` sem seed e `uuid4()` estão
   banidos do caminho do agente. Tempo e identidade entram por injeção: `Clock` e
   `IdentifierFactory` (`domain/ports/time.py`); implementações em
   `infrastructure/observability/clocks.py` (`FixedClock`/`SequentialIdentifiers` nos testes,
   `SystemClock` só na raiz de composição).
2. **Um contador de tokens.** Só implementações de `TokenCounter` (`domain/ports/tokenizer.py`)
   contam tokens; os adaptadores vivem em `infrastructure/tokens/counter.py`. O proxy de
   caracteres `C = Σ_m ceil(|m| / chars_per_token)` (`CHARS_PER_TOKEN = 4`) é o padrão e o que
   o CI usa; `TiktokenCounter` é opt-in e nunca roda no CI (baixa encoding).
3. **Sem números mágicos.** Todo limite, budget, timeout e preço vive em `config.py`
   (dataclasses frozen, validadas no `__post_init__`) ou em constante nomeada de módulo.
4. **Só erros tipados.** `CaioCodeError` e subclasses (`domain/errors.py`); `except: pass` é
   proibido. `ContextOverflowError` no braço baseline é *resultado*, não bug.
5. **Tools confinadas a uma raiz.** Todo caminho resolve contra `SandboxConfig.root`; fuga é
   `SandboxEscapeError`. Shell só com argv (`subprocess.run`), nunca `shell=True`. Saída de
   tool passa por `truncate_text` com marcador visível.
6. **Testes espelham `src/` e são offline.** Provedor `stub`, `FixedClock`, `tmp_path`.
   Qualquer coisa que precise de endpoint real leva `@pytest.mark.integration` e não roda no CI.
7. **`AGENTS.md` + symlink `CLAUDE.md` por diretório**, atualizados no mesmo PR que muda a pasta.
8. **Makefile é o único ponto de entrada.** Falta um alvo? Adicione ao Makefile, não invente
   comando paralelo.
9. **Linear card + PR pequeno** (§5, §6) para toda alteração.

Detalhes e rationale: `.claude/skills/tcc-foundations/SKILL.md`.

---

## 5. Como rodar

```bash
make setup          # venv + dependências + git hooks
make test           # suíte completa (offline, stub)
make test-changed   # só os módulos alterados (mesma seleção do CI de PR)
make lint           # ruff check src tests scripts
make smoke          # verificação ponta a ponta offline
make check          # lint + test

make tui                        # TUI com o provedor stub (PROVIDER=openai_compatible p/ real)
make drive                      # todos os cenários do driver headless → .reports/tui
make dataset                    # regenera o dataset e prova determinismo (sha256sum)
make evaluate                   # experimento completo com stub — offline
make evaluate-live              # experimento contra endpoint real (exige OPENAI_API_KEY; custa $)
make evaluate-replay-stub       # chat-replay (v5) com stub — offline
make evaluate-replay-pilot      # piloto live do chat-replay: 10 trials (CUSTA ~US$ 5)
make evaluate-replay-live       # chat-replay completo: 50 trials, 128k, janela 40k (CUSTA US$ 15-30)
make layering                   # regra de dependência + determinismo (tests/test_layering.py)

# datagen/ — dataset sintético via NeMo Data Designer (venv isolado em datagen/.venv)
make datagen-setup              # cria o venv e registra provider/aliases (idempotente)
make datagen-plan               # plano de geração + custo estimado (não gasta nada)
make datagen-generate           # gera os blocos (CUSTA $; CASE=case-01-... SET=facts SCALE=0.05)
make datagen-build              # convert.py + validate.py -> evals/datasets/long_histories_128k
```

O dataset do experimento é selecionado por `CAIO_CODE_EVAL_DATASET`; o padrão é
`evals/datasets/long_histories` (regenerável byte a byte). O dataset maior
`long_histories_128k` vem de `datagen/` e é *hash-pinned*, não regenerável —
ver `evals/AGENTS.md` e `datagen/AGENTS.md`.

CLI (sempre `--provider stub` por padrão):

```bash
python -m caio_code run --task "read README.md and summarize it" --root . --policy sliding_window
python -m caio_code tui [--demo]
python -m caio_code compact --transcript caminho/do/envelope.json [--keep-tokens N]
python -m caio_code evaluate [--arms a,b] [--cases N] [--repetitions N] [--out DIR]
                             [--run-id NOME] [--concurrency N] [--window-tokens N] [--model M]
                             [--variants full,spill]   # com --variants, roda o chat-replay (v5)
python -m caio_code classify --state "..." --noul id=pergunta? [--provider stub|typesafe]
python -m caio_code doctor [--json]        # nomes de env, NUNCA valores
```

Driver headless da TUI (como um agente de IA dirige a interface sem terminal):

```bash
python -m caio_code.presentation.tui.driver --scenario all --reports-dir .reports/tui
python -m caio_code.presentation.tui.driver --script passos.txt
```

Dataset e experimento:

```bash
python evals/generate_dataset.py [--out DIR] [--seed N] [--dry-run]   # determinístico
```

Os relatórios do experimento caem em `.reports/evals/<run_id>/` com `results.json` (evidência
que o Capítulo 4 cita) e `report.md` (tabela comparativa dos braços).

---

## 6. Linear, versionamento, CI e hooks

### Linear — obrigatório

Workspace `Caio Medeiros`, time `CM`. Autenticação em `LINEAR_API_KEY` (nunca versionada).

1. **Toda feature e toda alteração tem card.** O card é criado antes do código, não depois.
2. **Todo avanço é um comentário isolado no card** — um comentário por avanço: decisão, teste
   que passou, métrica observada, falha encontrada. Não editar comentário antigo para
   acrescentar novidade, não acumular dois avanços num comentário.
3. **Feature maior = projeto (ou card pai) + subtarefas.** PRs pequenos (5–20 arquivos) são
   dependentes lineares uns dos outros e empilhados. O comentário de progresso vai na
   subtarefa correspondente.
4. **`Done` significa "merged na main e documentado".** Trabalho pronto mas não integrado
   permanece `In Progress`.
5. O escopo do PR deve corresponder ao card. Mudança fora de escopo pede card novo ou divisão
   do PR.

Automação: `python scripts/linear.py …`. O hook de fim de sessão consolida o progresso.

### Versionamento

- **Qualquer alteração nesta pasta exige pull request.** Push direto em `main` é bloqueado
  pelo `.githooks/pre-push` e, no servidor, por branch protection.
- O PR é pequeno: **entre 5 e 20 arquivos** alterados. `scripts/ci/pr_size.py` falha acima de
  20 e avisa abaixo de 5.
- Branch: `<tipo>/<card>-<slug>`, por exemplo `feat/CM-31-window-policy`.
- **Antes do push**, a branch precisa estar atualizada com a base do PR (`origin/main` ou a
  branch empilhada anterior). O pre-push verifica e falha com instruções.
- Commits em inglês, imperativos, com o ID do card: `CM-31: add sliding-window policy`.
- Rebase, não merge, para atualizar a branch.
- **Stack de PRs**: features maiores são quebradas em PRs linearmente dependentes; cada PR
  compila e passa os próprios testes sozinho; o merge é de baixo para cima, com rebase dos de
  cima. `make stack-new NAME=<slug> CARD=<CM-nn>` cria a branch empilhada.

### CI

| Workflow | Gatilho | O que roda |
|---|---|---|
| `pr-tests.yml` | `pull_request` | testes **apenas das pastas modificadas** (`scripts/ci/changed_tests.py`) + `pr_size.py` |
| `main-tests.yml` | `push` em `main` | `make test` — suíte completa |
| `smoke.yml` | `pull_request` + `push` em `main` | `scripts/smoke.py` em **ubuntu, macos e windows** |

Nenhum CI usa rede nem chave de API: o provedor `stub` é o padrão dos testes. Teste que exige
LLM real é marcado `@pytest.mark.integration` e não roda no CI.

### Hooks de fim de sessão

Dois hooks `SessionEnd` em `.claude/settings.json`, cada um disparando um `claude -p` headless
em segundo plano:

1. **Aprendizado**: lê o transcript, extrai no máximo três lições acionáveis e, se houver
   mudança real, abre PR tocando **somente** `.claude/skills/**`, `CLAUDE.md` ou `AGENTS.md`.
2. **Linear**: registra o progresso no card ativo via `scripts/linear.py`.

Regras: best-effort, nunca falham a sessão; logs em `.reports/session-end/`;
`TCC_SKIP_SESSION_HOOKS=1` desliga os dois; sessões filhas não disparam hooks de novo.

---

## 7. Os onze braços do experimento

Definidos em `application/experiment/arms.py` (`default_arms`). Todos compartilham dataset,
modelo e sondas; a única diferença é a política de contexto. Todo pipeline de retenção termina
com `structure_repair` (ADR 0004b).

| Braço | O que isola |
|---|---|
| `baseline_full_history` | Sem gestão: envia tudo e mede o estouro contra a janela declarada (custo real visível) |
| `baseline_capped` | Sem gestão com janela imposta: trial que não cabe é recusado e registrado como `ContextOverflowError` |
| `sliding_window` | Retenção de sufixo: a cauda contígua mais recente que cabe no budget |
| `message_selection` | Retenção não contígua por relevância: scorer lexical vê a task e todas as mensagens |
| `message_selection_decision` | Mesma política, mas a relevância é julgada pelo modelo de decisão TypeSafe/Jev (uma pergunta `Noul` por mensagem); o braço mede o que o julgamento custa |
| `message_selection_decision_plus_truncation` | Truncagem das saídas de ferramenta antes do julgamento por modelo de decisão |
| `anchored_compaction` | Cabeça dobrada em resumo ancorado (5 seções fixas); cauda verbatim sobrevive |
| `tool_truncation_only` | Só o teto de linhas/bytes das saídas de ferramenta; nenhuma mensagem cai |
| `sliding_window_plus_truncation` | Truncagem primeiro, depois sufixo mais recente |
| `message_selection_plus_truncation` | Truncagem primeiro, depois subconjunto por relevância |
| `anchored_compaction_plus_truncation` | Truncagem primeiro, depois compactação ancorada — **a configuração que o protótipo embarca** |

Métricas por trial (`domain/evaluation/scoring.py`): retention por posição de fato
(early/middle/late), pass^k sobre as repetições, cache hit ratio (`cached_tokens` do próprio
provedor), custo em USD pela `PRICE_SHEET` do domínio, overflow, erros e latência (ADR 0004c).

Os tokens são separados em duas colunas porque misturá-los falseia a comparação:

- `probe_usage` — o que o modelo agente recebeu de fato (contexto moldado + sondas). É a
  coluna `prompt tok` dos relatórios e a base da comparação entre braços.
- `aux_usage` — o que o braço gastou para moldar esse contexto: chamadas do resumidor e do
  modelo de decisão. Aparece como `aux tok` e entra no custo total do trial.
- `usage` — a soma das duas, mantida por compatibilidade com os artefatos anteriores.

Um braço cujo julgamento custa mais tokens do que ele economiza não é vitória, e esconder
essa conta em nota de rodapé tornaria a comparação desonesta (ADR 0005).

### O run v5 (chat-replay)

O run atual do Capítulo 4 é o **chat-replay** (`application/evaluation/`): o histórico
transbordante é semeado, a política do braço molda o contexto **uma vez**, e as sondas são
perguntadas in-band ao mesmo agente, que pode chamar até 3 tools servidas pelo
`ReplayToolServer`. A nota é binária, dada por um juiz LLM (`evals/prompts/judge_v1.md`,
calibrado contra respostas rotuladas às cegas por dois subagentes independentes — não pelo
autor, o que fica registrado como ameaça à validade; concordância 29/30 = 97%, portão de 90%)
que nunca vê o contexto.
Cinco braços (`REPLAY_ARMS`), duas variantes de caso (`full`/`spill` — a truncagem de saídas
de tool para arquivo é fator de caso, não braço), matriz 5 × 5 × 2 × 1 = 50 trials
(`chapter4-main-v5`, janela declarada de 40k — abaixo do menor caso nas DUAS variantes:
spill mínimo 41,6k, full mínimo 114k tokens proxy; a 96k a variante spill nunca
transbordaria e a comparação perderia o ponto de observação comum). Sem pass^k:
temperatura 0.0 e uma repetição — a retenção média é a métrica de consistência. **Cache hit não é medido no replay** e não
aparece no relatório; a ameaça à validade fica no texto do capítulo. O resumo ancorado entra
no transcript como mensagem `Role.ASSISTANT` (metodologia do Capítulo 4).

---

## 8. Segredos e ambiente

- `.env` vive na **raiz do repositório** (é lido do diretório de trabalho do processo por
  `load_endpoints`); é gitignored e **nunca versionado**. `.env.example` documenta os nomes.
- Nenhum valor de segredo pode ser impresso em log, PR, comentário do Linear, transcript ou
  saída de comando. `doctor` reporta nomes de variáveis, nunca valores.
- Variáveis lidas por `config.py` (`load_settings`/`load_endpoints`):

| Variável | Significado | Default |
|---|---|---|
| `OPENAI_API_KEY` | chave do endpoint OpenAI-compatible (Aliyun) | vazio |
| `OPENAI_BASE_URL` | base URL do endpoint OpenAI-compatible | vazio |
| `TYPESAFE_API_KEY` | chave do modelo de decisão TypeSafe (Jev); exigida só por ele | vazio |
| `LANGSMITH_API_KEY` | ativa o tracing quando presente | vazio (tracing off) |
| `LANGSMITH_PROJECT` | projeto LangSmith | `caio-code` |
| `CAIO_CODE_PROVIDER` | `stub` \| `openai_compatible` (chat; Jev NÃO é chat — ADR 0005) | `stub` |
| `CAIO_CODE_AUX_PROVIDER` | provedor das chamadas auxiliares (summarizer/scorer) | igual ao provider |
| `CAIO_CODE_MODEL` | modelo do loop do agente | `qwen3.8-max` |
| `CAIO_CODE_AUX_MODEL` | modelo auxiliar | `qwen3.8-flash` |
| `CAIO_CODE_TEMPERATURE` | temperatura das chamadas | `0.0` |
| `CAIO_CODE_MAX_OUTPUT_TOKENS` | teto de saída (vira `reserved_output_tokens`) | `4096` |
| `CAIO_CODE_TIMEOUT_SECONDS` | timeout do provedor | `120` |
| `CAIO_CODE_MAX_RETRIES` | retries do provedor | `2` |
| `CAIO_CODE_WINDOW_TOKENS` | janela declarada (variável independente do experimento) | `8000` |
| `CAIO_CODE_CONTEXT_LIMIT` | o que o provedor realmente aceita | `128000` |
| `CAIO_CODE_WINDOW_BUFFER` | buffer do gatilho de auto-compactação | `20000` |
| `CAIO_CODE_ROOT` | raiz do sandbox das tools | cwd |
| `CAIO_CODE_SYSTEM_PROMPT` | arquivo de prompt alternativo | none (prompt built-in) |
| `CAIO_CODE_TOKEN_COUNTER` | `char_proxy` \| `tiktoken` | `char_proxy` |
| `CAIO_CODE_ENFORCE_WINDOW` | baseline recusa estouro em vez de enviar | `false` |
| `CAIO_CODE_COMPACTION_KEEP_TOKENS` | cauda verbatim da compactação | `8000` |
| `CAIO_CODE_SUMMARY_MAX_TOKENS` | teto do texto do resumo | `4096` |
| `CAIO_CODE_TOOL_RESULT_CHAR_CAP` | teto de chars de tool result no rendering do summarizer | `2000` |
| `CAIO_CODE_SUMMARIZER_MODEL` | modelo do summarizer | none (usa aux) |
| `CAIO_CODE_AUTO_COMPACT` | compactação automática ligada | `true` |
| `CAIO_CODE_TOOL_MAX_LINES` | teto de linhas por saída de tool | `2000` |
| `CAIO_CODE_TOOL_MAX_BYTES` | teto de bytes por saída de tool | `51200` |
| `CAIO_CODE_ALLOW_EXECUTE` | permite a tool de shell | `true` |
| `CAIO_CODE_EVAL_DATASET` | diretório do dataset | `evals/datasets/long_histories` |
| `CAIO_CODE_EVAL_REPORTS` | diretório dos relatórios | `.reports/evals` |
| `CAIO_CODE_EVAL_REPETITIONS` | repetições por caso (pass^k) | `3` |
| `CAIO_CODE_EVAL_MAX_CASES` | casos por run | `5` |
| `CAIO_CODE_PROBE_TOOL_CALL_CAP` | teto de tool calls por rodada de sondas do replay | `3` |
| `CAIO_CODE_JUDGE_PROMPT` | arquivo do prompt do juiz (versionado) | `evals/prompts/judge_v1.md` |
| `CAIO_CODE_JUDGE_MIN_AGREEMENT` | concordância mínima do juiz na calibração | `0.90` |
| `CAIO_CODE_LANGSMITH_UPLOAD` | upload de traces do experimento | `false` |
| `TYPESAFE_BASE_URL` | base URL do modelo de decisão (opcional) | `https://api.typesafe.ai` |
| `CAIO_CODE_DECISION_PROVIDER` | `stub` \| `typesafe` (modelo de decisão, ADR 0005) | `typesafe` se `TYPESAFE_API_KEY` existe, senão `stub` |
| `CAIO_CODE_DECISION_MODEL` | modelo de decisão | `jev-latest` |
| `CAIO_CODE_DECISION_BASE_URL` | override da base URL do modelo de decisão | `TYPESAFE_BASE_URL` |
| `CAIO_CODE_DECISION_TIMEOUT_SECONDS` | timeout do modelo de decisão | `60` |
| `CAIO_CODE_DECISION_STATE_CHAR_CAP` | teto de chars por mensagem no estado classificado | `600` |
| `CAIO_CODE_DECISION_QUESTIONS_PER_REQUEST` | perguntas por requisição (o estado é reenviado por batch) | `40` |
| `CAIO_CODE_DECISION_RELEVANCE_THRESHOLD` | limiar de relevância da seleção por decisão | `0.5` |
| `CAIO_CODE_DECISION_RISK_THRESHOLD` | limiar de risco do advisor de tool calls | `0.5` |

Fora do pacote: `LINEAR_API_KEY`, `LINEAR_TEAM_ID`, `LINEAR_PROJECT_ID` (scripts/Linear) e
`TCC_SKIP_SESSION_HOOKS` (hooks de sessão).

---

## 9. Documentação

| Arquivo | Conteúdo |
|---|---|
| `FEATURE_TREE.md` | árvore de funcionalidades do agente + diagramas de fluxo |
| `README.md` | quick start e conexão com a tese |
| `docs/adr/` | decisões de arquitetura (0001–0005) |
| `docs/linear-workflow.md` | cards, subtarefas, stack de PRs |
| `*/AGENTS.md` | invariantes locais de cada pasta |
| `.reports/evals/<run_id>/` | `results.json` + `report.md` do experimento |

---

## 10. Decisões registradas (ADRs)

| ADR | Decisão |
|---|---|
| 0001 | Estrutura em camadas `cli → harness → folhas` (**superado** por 0002/0003) |
| 0002 | deepagents/LangChain como loop do agente; a tese mede as políticas do middleware |
| 0003 | Camadas DDD e a regra de dependência; decisões aplicadas por índice |
| 0004 | Medições do Capítulo 4: cauda verbatim sobre o custo real, structure repair obrigatório, cache/custo do provedor |
| 0005 | Jev (TypeSafe) é modelo de decisão atrás de porta própria: seleção de mensagens por Noul, advisor de risco consultivo, custo atribuído ao braço |

ADR é imutável: decisão superada ganha outro ADR, nunca edição do anterior.

---

## 11. Pendências conhecidas

- [x] `tests/test_layering.py`: verificação por AST da regra de dependência (ADR 0003).
- [ ] Remover os diretórios vazios do layout antigo em `tests/` (`context`, `harness`,
      `providers`, `state`, `tools`, `scripts`).
- [ ] `scripts/smoke.py` ainda procura `src/caio_code/cli.py` (layout antigo) e pula a
      verificação do CLI; apontar para `presentation/cli/main.py`.
- [ ] Preencher `LINEAR_PROJECT_ID` do projeto do agente em `.env`.
- [ ] Habilitar branch protection em `main` (PR obrigatório, CI verde, branch atualizada).
- [x] Piloto do chat-replay (`chapter4-main-v5-pilot`, 10 trials, US$ 1.41) e calibração do
      juiz: 30 respostas rotuladas às cegas (dois subagentes independentes, unânimes; NÃO o
      autor — registrado como ameaça à validade), concordância 29/30 = 97% (portão ≥ 90%).
      `calibration-report.json` em `.reports/evals/chapter4-main-v5-pilot/`.
- [x] Run completo `chapter4-main-v5` (`make evaluate-replay-live`, 50 trials, 2026-11-08,
      US$ 7.4246, zero erros; janela 40k, uma repetição, 5 braços x 5 casos x 2 variantes).
      Artefatos em `evidencias/experimento/cap-04/v5/`.
- [x] Rodar o experimento live para os números finais do Capítulo 4: `chapter4-main-v4`
      (11 braços x 5 casos x 3 repetições = 165 trials, $7.55, zero falha de provedor;
      `make evaluate-live EVAL_RUN_ID=...` reproduz as mesmas condições).

# FEATURE_TREE.md — árvore de funcionalidades do caio-code

Cada folha anota o caminho do módulo que a implementa (`src/caio_code/` implícito).
Os diagramas FLOW no fim mostram os caminhos de execução ponta a ponta.

```
caio-code (agente de codificação de longa duração — protótipo do TCC)
│
├── AGENT LOOP  (loop agêntico)
│   ├── grafo deepagents (create_deep_agent, stream astream_events v2)
│   │       application/agent/runner.py
│   ├── dependências explícitas e injetadas (AgentDependencies)
│   │       application/agent/runner.py
│   ├── system prompt montado (papel, tools, todos, contrato de contexto)
│   │       application/agent/prompt.py
│   ├── middleware do grafo
│   │   ├── TodoListMiddleware (built-in do LangChain)      runner.build_agent
│   │   ├── _ToolEventMiddleware (eventos de tool + guard)  application/agent/runner.py
│   │   └── ContextPolicyMiddleware (pipeline a cada model call)
│   │           infrastructure/middleware/context_policy.py
│   ├── modelo stub roteirizado (BaseChatModel offline)
│   │       application/agent/stub_model.py
│   ├── tools (todas confinadas ao sandbox)
│   │   ├── filesystem: read/write/edit/list/glob           infrastructure/tools/filesystem.py
│   │   ├── search: grep/find (stdlib)                      infrastructure/tools/search.py
│   │   ├── shell: argv via subprocess.run                  infrastructure/tools/shell.py
│   │   ├── sandbox: confinamento de caminho                infrastructure/tools/sandbox.py
│   │   └── seleção de backend (Filesystem|State)           infrastructure/tools/deepagents_backend.py
│   ├── guardrails
│   │   └── tool idêntica repetida → advisory ao modelo     application/guardrails/repeated_tool_call.py
│   ├── interrupção de turno (interrupt → status "interrupted")
│   │       application/agent/runner.py
│   └── resultado do run (AgentRunResult.as_record)         application/agent/session.py
│
├── CONTEXT MANAGEMENT  (gestão de contexto — objeto de estudo da tese)
│   ├── contrato de política: planner puro → decisão        domain/policy/base.py
│   ├── aplicação de decisão POR ÍNDICE (identidade preservada p/ prompt cache)
│   │       domain/policy/base.py (result) + infrastructure/mappers/langchain.py (apply_decision)
│   ├── as cinco políticas
│   │   ├── baseline full history (mede o estouro)          domain/policy/full_history.py
│   │   ├── sliding window (sufixo que cabe)                domain/policy/sliding_window.py
│   │   ├── message selection (relevância não contígua)     domain/policy/message_selection.py
│   │   ├── anchored compaction (planner da compactação)    domain/policy/compaction.py
│   │   └── tool-output truncation (teto linhas/bytes)      domain/policy/tool_output.py
│   ├── structure repair (re-pareia tool calls órfãos — último passo de todo pipeline)
│   │       domain/policy/structure_repair.py
│   ├── composição em pipeline (truncation → retenção → repair)
│   │       domain/policy/base.py (PolicyPipeline)
│   ├── budget e pressão de janela                          domain/conversation/budget.py
│   └── contagem de tokens (porta + adaptadores)
│       ├── porta TokenCounter                              domain/ports/tokenizer.py
│       ├── char proxy ceil(chars/4) (padrão, CI)           infrastructure/tokens/counter.py
│       └── tiktoken (opt-in, nunca no CI)                  infrastructure/tokens/counter.py
│
├── COMPACTION  (compactação ancorada, estrutura do opencode)
│   ├── planner: head → summary, cauda verbatim             domain/policy/compaction.py (CompactionPlanner, tail_boundary)
│   ├── rendering do head para o summarizer (tool results com cap)
│   │       domain/conversation/rendering.py
│   ├── prompt do summarizer (novo | merge com prévio)      domain/conversation/summary.py (summarizer_prompt)
│   ├── seções ancoradas: Objective, Important Details, Work State
│   │   (Completed/Active/Blocked), Next Move, Relevant Files
│   │       domain/conversation/summary.py (SECTION_HEADINGS, SUMMARY_TEMPLATE)
│   ├── parse tolerante do resumo                           domain/conversation/summary.py (parse_summary)
│   ├── serviço: summarize → replace placeholder → re-measure → eventos
│   │       application/compaction/service.py (CompactionService)
│   └── execução dentro do loop                             infrastructure/middleware/context_policy.py (_run_compaction)
│
├── TODO TRACKING
│   ├── board de domínio (1 in_progress máx., ids únicos)   domain/todo/items.py
│   ├── tracker: write_todos → board validado               application/todos/service.py
│   └── evento TodoBoardUpdated (publicado pelo runner)     application/agent/runner.py
│
├── ACCOUNTING  (tokens, cache, custo)
│   ├── TokenUsage/CacheStats (cached_tokens do provedor)   domain/usage/accounting.py
│   ├── Cost em Decimal + PriceSheet (USD/milhão, config)   domain/usage/accounting.py + config.py (PRICE_SHEET)
│   ├── ledger do run via eventos do bus                    application/metrics/ledger.py (RunLedger)
│   └── ponte de pricing                                    infrastructure/pricing/sheet.py
│
├── PROVIDERS
│   ├── portas: ModelGateway, Summarizer, RelevanceScorer   domain/ports/{gateway,summarizer,scorer}.py
│   ├── stub (único permitido em testes/CI)                 infrastructure/llm/stub.py
│   ├── openai-compatible (SDK openai, retries limitados)   infrastructure/llm/openai_compatible.py
│   ├── factory da raiz de composição                       infrastructure/llm/factory.py
│   └── modelo de decisão (Jev; porta DecisionModel, ADR 0005)
│       ├── TypeSafe Jev / stub offline                     infrastructure/decision/{typesafe,stub}.py
│       ├── scorer de relevância (um Noul por mensagem)     infrastructure/decision/scorer.py
│       ├── advisor de risco de tool (consultivo)           infrastructure/decision/risk.py
│       └── factory + CLI classify                          infrastructure/decision/factory.py, presentation/cli/commands/classify.py
│
├── TUI  (interface terminal, Textual)
│   ├── transcript rolante (bolhas por role, deltas de streaming)
│   │       presentation/tui/widgets/message_list.py
│   ├── composer (enter envia, ctrl+j/shift+enter newline, esc interrompe)
│   │       presentation/tui/widgets/composer.py
│   ├── todo sidebar (header "3/7 · 43%", um item por linha) presentation/tui/widgets/todo_sidebar.py
│   ├── usage footer (modelo · política · ctx · tokens · cache · custo · status)
│   │       presentation/tui/widgets/usage_footer.py
│   ├── tool panel (argumentos, resultado colapsável)       presentation/tui/widgets/tool_panel.py
│   ├── context inspector (modal, ctrl+u)                   presentation/tui/app.py
│   ├── keybindings (ctrl+q, ctrl+c, ctrl+t, ctrl+u, pgup/pgdn)
│   │       presentation/tui/app.py
│   ├── fachada injetada (protocolo AgentFacade)            presentation/tui/ports.py
│   ├── fachada offline para demo/testes                    presentation/tui/scripted.py
│   └── tema (cores/tamanhos/CSS centralizados)             presentation/tui/theme.py
│
├── TUI DRIVER  (headless, Pilot do Textual)
│   ├── cenários embutidos: smoke, todo_sidebar, compaction, interrupt, demo
│   │       presentation/tui/driver/scenarios.py
│   ├── passos tipados + script texto (send, key, wait, assert-text,
│   │   assert-todo, assert-footer, assert-widget, snapshot)
│   │       presentation/tui/driver/steps.py
│   ├── execução headless (App.run_test)                    presentation/tui/driver/pilot_driver.py
│   ├── snapshots SVG + txt por passo nomeado               presentation/tui/driver/pilot_driver.py
│   ├── relatório (DriverReport, JSON, Markdown)            presentation/tui/driver/report.py
│   ├── extração de texto p/ asserções                      presentation/tui/driver/text.py
│   └── CLI: python -m caio_code.presentation.tui.driver    presentation/tui/driver/cli.py
│
├── EVALUATION  (experimento do Capítulo 4)
│   ├── dataset congelado (5 casos, fatos early/middle/late) evals/generate_dataset.py + evals/datasets/long_histories/
│   ├── modelo do dataset (CriticalFact, Probe, HistoryCase) domain/evaluation/cases.py
│   ├── alias scoring (answer_matches, normalização)        domain/evaluation/cases.py
│   ├── os 11 braços (ArmSpec, pipelines com structure repair) application/experiment/arms.py
│   ├── trial: shape → probes → score → accounting          application/experiment/runner.py
│   ├── métricas: retention, pass^k, cache, custo, overflow  domain/evaluation/scoring.py
│   ├── relatório: results.json + report.md                 application/experiment/report.py
│   ├── chat-replay v5: seed → molda 1x → sondas in-band    application/evaluation/replay.py
│   ├── servidor de tools do replay (gravadas + spill)      application/evaluation/replay_tools.py
│   ├── variante spill (truncagem → arquivo, pura)          domain/evaluation/spill.py
│   ├── juiz LLM binário + portão de calibração             application/evaluation/judge.py
│   └── relatório do replay (coluna variant, sem cache)     application/evaluation/replay_report.py
│   ├── codec/loader do dataset                             infrastructure/datasets/{codec,loader}.py
│   └── scorer de relevância (lexical stub | modelo aux)    infrastructure/llm/{stub,openai_compatible}.py + application/selection/service.py
│
├── CLI
│   ├── run (headless + métricas + --json)                  presentation/cli/commands/run.py
│   ├── tui (real ou --demo)                                presentation/cli/commands/tui.py
│   ├── compact (uma compactação de transcript salvo)       presentation/cli/commands/compact.py
│   ├── evaluate (experiment runner; --variants → chat-replay) presentation/cli/commands/evaluate.py
│   ├── doctor (settings resolvidas; nomes de env, nunca valores)
│   │       presentation/cli/commands/doctor.py
│   ├── parser/despacho/exit codes                          presentation/cli/main.py
│   ├── raiz de composição (Settings → AgentDependencies)   presentation/cli/composition.py
│   └── formatação pura                                     presentation/cli/formatting.py
│
├── PERSISTENCE
│   ├── envelope JSON versionado de transcripts             infrastructure/persistence/codec.py
│   ├── TranscriptStore (escrita atômica)                   infrastructure/persistence/jsonl.py
│   └── ResultStore JSONL (fsync por append)                infrastructure/persistence/jsonl.py
│
└── OBSERVABILITY
    ├── eventos de domínio + bus síncrono                   domain/events.py
    ├── EventRecorder / to_record / JsonlEventHandler       infrastructure/observability/bus.py
    ├── relógios e identificadores injetáveis               infrastructure/observability/clocks.py
    └── tracing LangSmith opt-in (chave nunca impressa)     infrastructure/observability/langsmith.py
```

---

## FLOW 1 — um turno do agente, ponta a ponta

```
 usuário            presentation              application                    infrastructure
 ────────           ────────────              ───────────                    ──────────────
 digita no composer ─▶ CaioCodeApp ─▶ AgentFacade.send(text)
                          │              (facade.py) ─▶ AgentRunner.run(task)
                          │                                 │
                          │                    RunStarted + MessageAppended(user) no bus
                          │                                 │
                          │                    graph.astream_events (deepagents)
                          │                                 │
                          │              ContextPolicyMiddleware.awrap_model_call
                          │                                 │  to_domain(messages) ─▶ pipeline.plan
                          │                                 │  apply_pipeline POR ÍNDICE
                          │                                 │  ContextShaped ─▶ bus
                          │                                 ▼
                          │                             modelo (stub | endpoint real)
                          │                                 │ AIMessage (+ tool_calls?)
                          │                                 ▼
                          │              _ToolEventMiddleware.wrap_tool_call
                          │                 ToolCallIssued ─▶ bus
                          │                 guard.inspect(tool,args) ─▶ fired? advisory como ToolMessage
                          │                 não fired ─▶ tool roda no sandbox ─▶ ToolCallCompleted ─▶ bus
                          │                 write_todos ─▶ TodoTracker ─▶ TodoBoardUpdated ─▶ bus
                          │                                 │
                          │              on_chat_model_end ─▶ UsageRecorded ─▶ RunLedger
                          ▼                                 ▼
   widgets atualizam ◀── DomainEventArrived (post_message) ◀── RunFinished
   (transcript, sidebar, footer, tool panel)      AgentRunResult devolvido à fachada
```

## FLOW 2 — compactação

```
 middleware: pipeline.plan(...) com CompactionPlanner
      │
      ▼
 tail_boundary(costs, keep_tokens)          ← mede o custo das mensagens REAIS,
      │                                       não o rendering truncado (ADR 0004a)
      ├── head  = mensagens [0, boundary)
      └── tail  = mensagens [boundary, n)   ← sobrevive verbatim
      │
      ▼
 render_indexed(head, tool_result_char_cap) → texto p/ summarizer
 summarizer_prompt(conversation, previous_summary?) → prompt ancorado
      │
      ▼
 PolicyDecision: removals(head) + injected(summary placeholder "[summary pending]")
      │  ContextShaped ─▶ bus
      ▼
 CompactionService.compact
      ├── CompactionStarted ─▶ bus
      ├── summarizer.asummarize(prompt, max_tokens)     ← única chamada de modelo do fluxo
      ├── parse_summary(texto) → AnchoredSummary (5 seções; well_formed?)
      ├── summary_message_from(decision, summary) → mensagem pinned substitui o placeholder
      ├── re-measure: counter.count_transcript(shaped com resumo real)
      └── CompactionEnded(summary_chars, sections, well_formed, usage, cost) ─▶ bus
      │
      ▼
 middleware troca o placeholder pela mensagem real ─▶ modelo vê [Anchored summary...] + tail
```

## FLOW 3 — o experimento (um trial)

```
 evals/datasets/long_histories/case-NN.json
      │ load_dataset (infrastructure/datasets/loader.py)
      ▼
 HistoryCase (messages, facts, probes)
      │
      ▼
 arm.pipeline(settings)            ← um dos 11 braços (application/experiment/arms.py)
      │  (truncation → retenção → structure_repair)
      │  needs_scores? ─▶ SelectionService.with_scores (scorer lexical ou modelo aux)
      ▼
 pipeline.plan(PolicyRequest) ─▶ PipelineDecision ─▶ shaped transcript
      │  placeholder de summary? ─▶ CompactionService (usage/custo somados ao trial)
      │  enforce_window && overflowed? ─▶ trial falha com erro de overflow
      ▼
 probes anexadas como última mensagem pinned ─▶ gateway.acomplete(PROBE_SYSTEM_PROMPT)
      ▼
 parse_answers(reply) ─▶ score_answers por alias match ─▶ ProbeScore[]
      ▼
 TrialResult (retention, usage, cache=cached_tokens do provedor, cost=PriceSheet USD,
      │        tokens before/after policy, overflow, compactions, latency)
      ▼
 ArmAggregate por braço (mean_retention, pass^k, cache_hit_ratio, mean_cost, overflow_rate)
      ▼
 ExperimentReport ─▶ write_report ─▶ .reports/evals/<run_id>/{results.json, report.md}
```

## FLOW 4 — ordem do pipeline de políticas

```
 transcript original (LangChain messages)
      │
      ▼
 [1] tool_output_truncation        muda o CONTEÚDO: tool results acima do teto de
      │                            linhas/bytes viram head+tail com marcador
      │                            ("... output truncated; X of Y lines ... omitted ...")
      ▼
 [2] política de retenção          muda o CONJUNTO: sliding_window (sufixo),
      │                            message_selection (top-score) ou anchored_compaction
      │                            (head → placeholder de resumo); pinned nunca cai
      ▼
 [3] structure_repair              muda os PARES: derruba tool results órfãos e
      │                            remove tool_calls sem resultado do assistant
      │                            (sem isto, o endpoint responde 400 — ADR 0004b)
      ▼
 apply_pipeline: decisões aplicadas POR ÍNDICE sobre a lista original
 (mensagens mantidas = mesmos objetos → prompt cache do provedor continua valendo)
```

## FLOW 5 — driver headless da TUI

```
 --scenario NAME | --script FILE | --stdin          (presentation/tui/driver/cli.py)
      │
      ▼
 Scenario (passos tipados) + app factory ─▶ ScriptedFacade + FixedClock + bus
      │                                       (cenários embutidos em scenarios.py)
      ▼
 TuiDriver.run_scenario ─▶ App.run_test(headless=True) ─▶ Pilot
      │
      │  para cada passo: type/key/wait/send/assert-*/snapshot
      │     ├── asserção falha ─▶ DriverAssertionError (índice, esperado, real)
      │     │        --continue-on-error? acumula em report.failures
      │     └── snapshot ─▶ NNN-<nome>.svg + NNN-<nome>.txt em reports_dir/<cenário>/
      │  StepRecord: status, elapsed_ms (relógio injetado), screen_text
      ▼
 DriverReport ─▶ report.json / report.md ─▶ .reports/tui/<cenário>/
 exit code: 0 tudo passou · 1 asserção falhou · 2 uso inválido
```

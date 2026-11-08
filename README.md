# caio-code

Agente de codificação para tarefas longas em repositórios grandes, desenvolvido como protótipo
da Parte III do TCC *Context Is All You Need*. O agente é descrito no Capítulo 3 e medido por
um experimento de onze braços no Capítulo 4; este repositório é o artefato dos dois. É um
repositório git independente, mantido dentro de `~/tcc/` por conveniência — o repositório da
monografia o ignora.

A tese que o agente encarna: a gestão explícita do contexto — janela, seleção e compactação —
é o que permite a um agente de longa duração continuar coerente quando o histórico não cabe
mais na janela do modelo. O loop agêntico é do deepagents/LangChain (ADR 0002); o que a tese
mede são as políticas de contexto que o middleware aplica a cada chamada de modelo.

## Começo rápido

```bash
make setup          # cria .venv, instala dependências e os git hooks
make test           # suíte completa (offline, provedor stub)
make lint           # ruff check
make smoke          # verificação ponta a ponta sem rede
make help           # todos os alvos
```

## Uso

```bash
# uma execução headless com métricas (stub, offline)
python -m caio_code run --task "read README.md and summarize it" --root . --policy sliding_window

# a interface terminal (stub usa a fachada roteirizada; --demo força o replay)
make tui
python -m caio_code tui [--demo]

# driver headless da TUI: cenários tipados via Pilot, com snapshots e relatório
make drive
python -m caio_code.presentation.tui.driver --scenario all --reports-dir .reports/tui

# uma compactação de um transcript salvo
python -m caio_code compact --transcript caminho/do/envelope.json

# diagnóstico de configuração (nomes de variáveis de ambiente, nunca valores)
python -m caio_code doctor
```

Para modelo real: `.env` na raiz com `OPENAI_API_KEY`/`OPENAI_BASE_URL` (ou `TYPESAFE_*`) e
`--provider openai_compatible`. Veja a tabela completa de ambiente em `AGENTS.md` §8.

## O experimento

```bash
make dataset          # regenera o dataset congelado e prova determinismo (sha256)
make evaluate         # os 11 braços com o provedor stub — offline
make evaluate-live    # contra o endpoint real (exige OPENAI_API_KEY; CUSTA DINHEIRO)
make evaluate-replay-stub   # chat-replay do Capítulo 4 (v5), offline
make evaluate-replay-pilot  # piloto live: 10 trials (~US$ 5)
make evaluate-replay-live   # run completo: 50 trials, janela 40k (~US$ 15-30)
```

Os relatórios caem em `.reports/evals/<run_id>/` com `results.json` (a evidência que o
Capítulo 4 cita) e `report.md` (tabela comparativa: retention por posição de fato, pass^k,
tokens de prompt, cache hit, custo em USD, overflow e latência por braço).

## Arquitetura em um diagrama

```
presentation ──▶ application ──▶ domain ◀── infrastructure
   cli/  tui/      agent/ compaction/     llm/ tokens/ tools/ middleware/
   (argparse,      experiment/ todos/     persistence/ datasets/ mappers/
    Textual)       guardrails/ selection/ observability/ pricing/
                   metrics/
```

- `domain/`: políticas de contexto como planners puros (decisões aplicadas **por índice**,
  preservando a identidade das mensagens para o prompt cache), transcript imutável, resumo
  ancorado de cinco seções, eventos, erros tipados, contabilidade de tokens/cache/custo e as
  portas (`TokenCounter`, `ModelGateway`, `Summarizer`, `Clock`, ...). Não importa nada do
  pacote além de `config.py`.
- `application/`: casos de uso — o runner do grafo deepagents, a compactação, o experimento de
  onze braços, todos, guardrail de loop, seleção por relevância e o ledger de custo.
- `infrastructure/`: adaptadores — provedores de chat (stub/openai-compatible), o modelo de
  decisão TypeSafe Jev (`infrastructure/decision/`, ADR 0005), contadores de
  tokens, tools confinadas a um sandbox, o middleware que aplica o pipeline de políticas a cada
  model call, persistência, datasets de avaliação, relógios e tracing.
- `presentation/`: CLI (única porta de processo) e TUI Textual com driver headless.

## Documentação

| Arquivo | Conteúdo |
|---|---|
| `AGENTS.md` (`CLAUDE.md` é symlink) | regras do repositório, árvore completa, ambiente, braços do experimento |
| `FEATURE_TREE.md` | árvore de funcionalidades com o módulo de cada folha + 5 diagramas de fluxo |
| `docs/adr/` | decisões de arquitetura (0001–0004) |
| `docs/linear-workflow.md` | cards, subtarefas e stack de PRs |
| `evals/AGENTS.md` | contrato de determinismo do dataset congelado |
| `*/AGENTS.md` | invariantes locais de cada pasta |
| `.claude/skills/tcc/SKILL.md` | roteador `/tcc` para as demais skills |

## Conexão com a tese

- **Capítulo 3 (método proposto):** o desenho do agente — as cinco políticas de contexto
  (baseline, sliding window, message selection, anchored compaction, tool-output truncation),
  o structure repair, o resumo ancorado e a composição em pipelines.
- **Capítulo 4 (resultados):** o experimento — cinco históricos longos congelados com fatos
  críticos em posições conhecidas, onze braços, sondas pontuadas por alias match, e as
  métricas de retention, pass^k, tokens, cache e custo. A evidência bruta vive em
  `.reports/evals/`.

## Licença

Uso acadêmico. Sem licença de distribuição.

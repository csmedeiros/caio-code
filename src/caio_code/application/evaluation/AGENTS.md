# src/caio_code/application/evaluation/

A avaliação por **chat-replay** do Capítulo 4 (v5): seed do histórico
transbordante → a política do braço molda o contexto **uma vez** → as sondas
são perguntadas in-band, como turnos de usuário normais, ao mesmo agente → um
juiz LLM que nunca vê o contexto pontua cada resposta binário.

## Módulos

| Módulo | Conteúdo |
|---|---|
| `replay.py` | `ReplayDependencies`, `ChatReplayRunner.run/run_trial`, `build_replay_dependencies`, `resolve_variants`, `run_replay_experiment`, `main`; `REPLAY_ARMS` (os cinco braços do run v5) |
| `replay_tools.py` | `ReplayToolServer`: índice de interações gravadas do caso, loja dos arquivos de spill, miss tipado visível (`ToolUnavailableInReplay`), contagem de chamadas |
| `replay_report.py` | `write_replay_report`: `results.json` + `report.md` (coluna variant, **sem coluna de cache**) + `report-comparison.md` (full vs spill por braço) |
| `judge.py` | `LlmJudge` (uma chamada por rodada de sondas), `parse_verdicts` tolerante, `CalibrationReport` e o portão de concordância (`judge_min_agreement`) |

O prompt do juiz é versionado em `evals/prompts/judge_vN.md`; revisão é um
arquivo novo, nunca edição.

## Invariantes

- **Uma moldagem por trial.** As sondas rodam imediatamente após o primeiro
  contexto moldado; não existe fase de continuação.
- **Garantia de estouro.** `_assert_overflow` roda antes de qualquer gasto:
  todo (caso, variante) deve exceder a janela declarada de todo braço, senão o
  run aborta com `EvaluationError`.
- **Teto de tool calls** na rodada de sondas: `settings.evaluation.probe_tool_call_cap`
  (padrão 3). Passou do teto, nenhuma tool é oferecida e o modelo recebe um
  miss visível; um `max_turns` duro impede loop infinito.
- **Contabilidade separada.** `probe_usage` = chamadas do modelo agente na
  rodada de sondas (contexto moldado + turnos de tool). `aux_usage` =
  summarizer + scorer de decisão + juiz. Nunca somados na coluna de prompt.
- **Cache hit não é medido no replay** e não aparece no relatório; a ameaça à
  validade está no texto do capítulo.
- Variantes (`full`/`spill`) derivam em runtime do caso commitado
  (`domain/evaluation/spill.py`): o dataset hash-pinned não é tocado. Um
  agregado por (braço, variante) — o fator truncagem nunca é tirado pela média.
- Erros (shaping, provedor, juiz) viram `TrialResult.error`, nunca exceção
  engolida; o trial falho conta como retenção 0 e custo do que já gastou.
- Determinismo: `Clock`/`IdentifierFactory` injetados; o `ReplayToolServer` não
  toca filesystem nem relógio — o texto de spill vive no próprio caso.

## Testes

`tests/application/evaluation/`, offline: `StubGateway` (com
`keyword_tool_calls` para o cenário "modelo lê o arquivo de spill e acerta a
sonda"), `StubJudgeGateway`, `StubSummarizer`, `FixedClock`, relatórios em
`tmp_path`.

# src/caio_code/domain/policy/

As políticas de contexto — o objeto de estudo da tese. Todas são planners puros: recebem
`PolicyRequest` (transcript, budget, counter, fixed_tokens, task, scores opcionais) e devolvem
`PolicyDecision`/`PipelineDecision`. Nenhuma faz I/O nem chama modelo.

## Módulos

| Módulo | Política | O que decide |
|---|---|---|
| `base.py` | contrato | `ContextPolicy` (Protocol), `PolicyRequest`, `Removal`/`Substitution`, `PolicyDecision` (kept_indices, injected, insert_at, tokens_before/after, `result()`, `as_record()`), `PolicyPipeline`, `PipelineDecision` |
| `full_history.py` | `baseline_full_history` | mantém tudo e reporta o estouro; abortar ou não é decisão do chamador (`BaselineConfig.enforce_window`) |
| `sliding_window.py` | `sliding_window` | sufixo contíguo mais recente que cabe, caminhada cumulativa para trás; pinned + `keep_recent_messages` sempre ficam |
| `message_selection.py` | `message_selection` | subconjunto não contíguo por score (greedy: score desc, índice asc); sem scores degrada para recência, com nota |
| `compaction.py` | `anchored_compaction` | `CompactionPlanner`: head → placeholder de resumo (prompt no metadata), cauda verbatim; `tail_boundary` mede o custo das mensagens reais (ADR 0004a) |
| `tool_output.py` | `tool_output_truncation` | reescreve tool results acima do teto de linhas/bytes (head+tail+marcador); não remove mensagens |
| `structure_repair.py` | `structure_repair` | re-pareia tool calls e resultados após retenção: derruba órfãos, remove calls sem resultado; último passo de todo pipeline (ADR 0004b) |

## Invariantes

- Decisão por índice: `kept_indices`/`substitutions.index`/`insert_at` referem-se ao transcript
  de entrada; quem aplica é o chamador (`PolicyDecision.result()` ou
  `infrastructure/mappers/langchain.apply_decision`), preservando identidade dos objetos.
- Toda decisão reporta o próprio estouro (`overflow_tokens`, `notes`): nada trunca depois da
  medição para esconder.
- `tokens_before`/`tokens_after` incluem `fixed_tokens` (system prompt + schemas de tools).
- Pipeline: cada passo indexa a saída do passo anterior; `PipelineDecision.steps` guarda os
  números de cada política para o relatório atribuir contribuições.
- Política não conhece LangChain nem provedor: fala `Message`/`Transcript`.
- Parâmetros numéricos vêm de `config.py` pelo chamador (defaults nos construtores existem só
  para testes do domínio).

## Testes

`tests/domain/policy/`: `test_pipeline_and_policies.py` (contrato, pipeline, janela, seleção,
truncagem), `test_compaction.py` (tail_boundary, placeholder, prompt, posição do resumo),
`test_structure_repair.py` (órfãos, calls sem resultado, assistant só com calls).

# tests/domain/policy/

Testes das políticas de contexto (`src/caio_code/domain/policy/`).

| Arquivo | Cobre |
|---|---|
| `test_pipeline_and_policies.py` | contrato `ContextPolicy`, composição `PolicyPipeline`, full_history (baseline reporta estouro), sliding_window (sufixo + pinned + keep_recent), message_selection (greedy por score, degradação para recência), tool_output (teto de linhas/bytes, marcador) |
| `test_compaction.py` | `tail_boundary` sobre o custo das mensagens reais (ADR 0004a), placeholder injetado pinned com prompt no metadata, posição do resumo entre pinned head e cauda, prompt com as cinco seções e merge com resumo prévio |
| `test_structure_repair.py` | tool results órfãos removidos, assistant com calls sem resultado (substituição/remoção), transcript íntegro intocado (ADR 0004b) |

## Invariantes

- Custos de fixture são exatos sob o char proxy (`ceil(chars/4)`): um teste de budget que
  depende de arredondamento implícito está errado.
- Decisões são assertadas pelos índices (`kept_indices`, `removals`, `insert_at`), não só
  pelos totais de tokens.

# src/caio_code/domain/conversation/

O modelo de conversa independente de provedor sobre o qual as políticas operam.

## Módulos

| Módulo | Conteúdo |
|---|---|
| `messages.py` | `Role`, `ToolCall`, `Message` (com `pinned` e cache `tokens`), `Transcript` imutável, `require_fits_budget` |
| `budget.py` | `TokenBudget`, `ContextLimit`, `WindowPressure`; `minus()` reserva custo fixo com piso de 1 |
| `rendering.py` | transcript → texto para o summarizer: `render_message`, `render_indexed` (mantém o índice do transcript), `split_indexed`/`split_head_and_recent` |
| `summary.py` | o resumo ancorado: `SECTION_HEADINGS` (Objective, Important Details, Work State + Completed/Active/Blocked, Next Move, Relevant Files), `SUMMARY_TEMPLATE`, `summarizer_prompt` (novo/merge), `parse_summary` tolerante, `AnchoredSummary.is_well_formed` |

## Invariantes

- `Message` e `Transcript` são frozen; edição produz cópia (`with_text` registra o marcador em
  `metadata["edits"]`).
- `pinned=True` é contrato com as políticas: mensagem pinned nunca é removida por retenção.
- `tokens` é cache e não é serializado; só o `TokenCounter` o preenche.
- O rendering trunca tool result por `tool_result_char_cap` — é texto para o summarizer, não
  é a base de orçamento (a cauda verbatim é orçada no custo real; ADR 0004a).
- `render_indexed` devolve `(índice do transcript, texto)`; mensagens sem conteúdo caem, mas o
  índice permanece traduzível.
- A estrutura do resumo é a do opencode, de propósito: cinco seções em ordem fixa, mantidas
  mesmo vazias (`(none)`).

## Testes

`tests/domain/conversation/` (`test_rendering_and_summary.py`): rendering, split, template,
parse tolerante (ordem preservada, headings desconhecidos mantidos, seções faltantes
reportadas por `missing_sections`).

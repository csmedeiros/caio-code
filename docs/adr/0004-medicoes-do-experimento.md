# ADR 0004 — Decisões de medição do experimento (Capítulo 4)

- **Status:** aceito
- **Data:** 2026-11-01

## Contexto

Um leitor do Capítulo 4 precisa saber três coisas sobre como os números foram medidos, porque
as três mudam a interpretação dos resultados e duas delas nasceram de bugs reais observados
durante o desenvolvimento do harness. Este ADR registra as decisões; o código que as implementa
está indicado em cada uma.

## Decisão

### (a) A cauda verbatim da compactação é orçada no custo das mensagens realmente enviadas

`tail_boundary` (`domain/policy/compaction.py`) decide quais mensagens sobrevivem verbatim
medindo o custo (`TokenCounter.count_message`) das **mensagens que vão para o modelo**, não o
texto renderizado e truncado que é entregue ao summarizer.

O bug que motivou a decisão: na primeira implementação, a fronteira era calculada sobre o
rendering do head/tail, onde cada tool result já vem cortado por `tool_result_char_cap`
(2.000 chars). O rendering é muito menor que as mensagens reais, então a "cauda de 8k tokens"
media 8k no rendering enquanto as mensagens enviadas custavam várias vezes mais — observou-se
um contexto supostamente "compactado" de **41k tokens contra uma janela de 8k**. A compactação
declarava caber e não cabia; o número do capítulo mediria estouro em vez de compactação. A
medição passou a ser sobre os custos reais, e o teste do planner cobre o caso.

### (b) Todo pipeline termina com a política de structure repair

Um política de retenção que corta a cabeça do histórico produz, no meio do transcript:

1. tool results cujo `tool_call_id` não tem mais o `tool_calls` correspondente (órfãos);
2. mensagens de assistant com `tool_calls` cujos resultados foram removidos.

Um endpoint OpenAI-compatible rejeita essa estrutura com **HTTP 400** — a requisição inteira
falha, não só a mensagem. Por isso `StructureRepairPolicy`
(`domain/policy/structure_repair.py`) é o último passo de **todo** pipeline dos braços
(`application/experiment/arms.py`, helpers `_single`/`_combined`): derruba resultados órfãos e
remove chamadas sem resultado (mantendo o texto do assistant quando existe).

O repair é **parte do braço medido**, não um conserto escondido do harness: seus efeitos
entram no `PipelineDecision` (removals/substitutions/notes) e portanto no `results.json` de
cada trial. O baseline `full_history` também passa por ele, mas como não remove nada o repair
é identidade — a comparação entre braços permanece justa.

### (c) Cache e custo vêm do provedor e da price sheet do domínio

- **Cache:** a métrica de cache é o `cached_tokens` que o próprio provedor reporta
  (`prompt_tokens_details.cached_tokens` / `input_token_details.cache_read`), mapeado em
  `TokenUsage.cached_input_tokens` (`domain/usage/accounting.py`; mapeamento defensivo no
  runner e em `infrastructure/llm/openai_compatible.py`). O harness nunca estima cache por
  conta própria; `CacheStats.hit_ratio = cached_input_tokens / input_tokens`.
- **Custo:** em USD, `Decimal`, precificado pela `PRICE_SHEET` do domínio
  (`config.py` → `PriceSheet.cost_of`), com preço por milhão de tokens separado para input,
  input com cache hit e output; modelo desconhecido cai no `FALLBACK_PRICE` (estimativa
  conservadora, nunca crash nem custo zero). "Mais barato" no relatório significa dólares,
  não tokens.

## Consequências

- Os braços de compactação medem o que realmente cabe na janela; um estouro residual aparece
  como `overflow_tokens` no trial, não como texto "compactado" que não compactou.
- Nenhum braço gerenciado falha com 400 por estrutura de mensagens; falhas de estrutura que
  restarem são erro do harness, não ruído do experimento.
- A preservação de identidade nas mensagens mantidas (ADR 0003, aplicação por índice) é o que
  permite ao `cached_tokens` do provedor subir nos turnos seguintes — cache medido e cache
  possível são a mesma coisa.

## Alternativas descartadas

- **(a) Orçar a cauda no rendering truncado.** Foi o bug; produz "compactação" que estoura a
  janela em ~5x.
- **(b) Consertar a estrutura no mapper LangChain, fora da medição.** Esconderia do relatório
  um efeito real da política (mensagens removidas) e faria o número do capítulo omitir parte
  do que o braço faz.
- **(c) Estimar cache localmente (prefixo comum entre turnos).** Divergiria do que o provedor
  cobra; a tese reporta o desconto que existe na fatura, não um modelo dele.

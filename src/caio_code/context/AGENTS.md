# src/caio_code/context/

Políticas de contexto. É a contribuição da tese em código: o que é mantido, descartado ou
resumido quando o histórico não cabe no orçamento.

## Invariantes

- **Uma única fórmula de token**, em `tokens.py`. Nenhum outro arquivo divide `len()` por 4.
- Toda política é uma função pura `(messages, budget, chars_per_token) -> messages`: não muta a
  entrada, não faz I/O, não chama modelo.
- Mensagem `pinned` (sistema e tarefa) nunca é descartada. Se o custo fixo estourar o
  orçamento, a política devolve as fixadas e **reporta o estouro** — não trunca escondido.
- Ordem cronológica preservada na saída.
- Empate resolvido por recência, nunca por ordem de hash.

## Políticas

| Arquivo | Política | Propriedade |
|---|---|---|
| `window.py` | janela deslizante | cauda contígua |
| `selection.py` | seleção por relevância lexical | subconjunto não contíguo |
| `compaction.py` | compactação por regra | resumo determinístico + cauda |

`compaction.py` tem um piso: o resumo também custa tokens, então orçamentos muito pequenos não
são alcançáveis. Isso é medido, não escondido.

## O que não entra aqui

Chamada de provedor, leitura de arquivo, configuração global, logging.
# src/caio_code/infrastructure/tokens/

Os adaptadores da porta `TokenCounter` (`domain/ports/tokenizer.py`). Existe **uma** contagem
de tokens no sistema; ela mora aqui.

## Módulos

`counter.py`:

| Classe | Quando |
|---|---|
| `CharProxyTokenCounter` | padrão e CI: o proxy da tese `C = Σ_m ceil(|m| / chars_per_token)` (divisor 4, `config.CHARS_PER_TOKEN`), somado por mensagem; determinístico e offline |
| `TiktokenCounter` | contagem BPE real (`o200k_base` por default), para reportar ao lado dos números do provedor; baixa encoding na primeira vez — **nunca** no CI |
| `build_counter(name, ...)` | o switch da raiz de composição (`char_proxy` \| `tiktoken`) |

## Invariantes

- Nenhum outro módulo divide `len(text)` por 4 por conta própria: se a fórmula muda, os
  números do experimento mudam em todo lugar de uma vez.
- `count_message` inclui o texto dos `tool_calls` (via `Message.char_count()`), não só o
  `text`.
- Budget é comparado com `C`, nunca com número de mensagens.
- Nome inválido de contador → `ConfigurationError`.

## Testes

Ainda não há diretório próprio (`tests/infrastructure/tokens/` — pendência); o contador é o
padrão da suíte inteira e a fórmula é exercitada indiretamente pelos testes de políticas,
datasets, mappers e compactação, que injetam `CharProxyTokenCounter`/`build_counter`.

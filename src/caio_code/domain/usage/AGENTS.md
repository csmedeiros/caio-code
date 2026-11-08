# src/caio_code/domain/usage/

Contabilidade de tokens, cache e custo como value objects. O Capítulo 4 reporta esses três
números por braço; a aritmética vive aqui para que todos os braços sejam medidos com a mesma
conta, em vez de cada script fazer a sua.

## Módulos

`accounting.py`:

| Tipo | Papel |
|---|---|
| `TokenUsage` | tokens de uma chamada como o provedor reportou; `cached_input_tokens ≤ input_tokens` validado |
| `CacheStats` | agregado de chamadas; `hit_ratio = cached/input` (o `cached_tokens` do provedor é a métrica — ADR 0004c) |
| `Cost` | USD em `Decimal` (float acumula visivelmente em 100 runs); `rounded` a 6 casas |
| `PriceSheet` | model → `ModelPrice` (USD por milhão, input/cached/output); modelo desconhecido cai no `FALLBACK_PRICE`, nunca crash |
| `RunAccounting` | usage + cache + custo + `proxy_input_tokens` (para medir o erro do proxy contra o provedor) |
| `UsageLedger` | acumulador mutável entre chamadas de um run |

## Invariantes

- Nenhum preço novo nasce aqui: os números vêm de `config.PRICE_SHEET`/`FALLBACK_PRICE`
  (import de `config` permitido pelo ADR 0003).
- `TokenUsage` é imutável; soma produz instância nova.
- Custo negativo é `PricingError`, não clamp silencioso.
- Contagem de tokens NÃO acontece aqui: `TokenUsage` registra o que o provedor disse; o proxy
  de caracteres é `infrastructure/tokens/counter.py` sob a porta `TokenCounter`.

## Testes

Os testes ficam em `tests/application/metrics/` (ledger) e
`tests/infrastructure/pricing/test_sheet.py` (ponte); os agregados são exercitados pelo
harness de avaliação (`domain/evaluation/scoring.py`).

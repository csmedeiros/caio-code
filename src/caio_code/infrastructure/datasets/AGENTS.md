# infrastructure/datasets/

Adaptadores do **dataset congelado de avaliação**: o codec JSON dos casos e o
carregador que produz as estatísticas que o Capítulo 4 reporta.

Os arquivos de dados ficam em `evals/datasets/long_histories/` e são gerados por
`evals/generate_dataset.py`. Nada aqui gera caso novo: este pacote só lê, valida
e descreve.

## Módulos

| Módulo | Papel |
|---|---|
| `codec.py` | `case_to_dict` / `case_from_dict`, `dataset_to_dict` / `dataset_from_dict` (+ peças menores: mensagem, tool call, fato, sonda) |
| `loader.py` | `load_dataset(directory, *, limit=None)`, `describe(dataset) -> DatasetStats` e `format_stats` (a tabela em texto) |

## O schema (contrato público — outro agente carrega estes arquivos)

Chaves de um caso (`case-NN-<slug>.json`):

```json
{
  "id": "case-01-...",
  "description": "<str>",
  "task": "<str>",
  "source": "synthetic",
  "metadata": {"generator": "...", "seed": 20261031, "...": "..."},
  "messages": [{"id", "role", "text", "tool_calls": [{"id", "name", "arguments"}],
                "tool_call_id", "name", "pinned", "metadata"}],
  "facts":    [{"id", "statement", "answer", "aliases", "position", "message_index"}],
  "probes":   [{"id", "fact_id", "question", "expected", "aliases"}]
}
```

Manifesto `dataset.json`: `{"name", "seed", "generator", "cases": [<id>, ...]}`.

`role` é o valor de `domain.conversation.messages.Role` (`system|user|assistant|tool`).
`position` é um de `early|middle|late` (`domain.evaluation.cases.POSITIONS`).
`Message.tokens` é cache e **não** é serializado. Tuplas dentro de `metadata`
viram listas JSON; os campos que são tupla no dataclass voltam como tupla.

## Por que não reusar `infrastructure/persistence`

Decisão deliberada: `persistence.codec` serializa uma sessão viva dentro de um
envelope versionado e levanta `StorageError`. Aqui o artefato é um benchmark
congelado e auditável, e o erro é `DatasetError`. Juntar os dois acoplaria o
formato do benchmark ao formato de persistência — uma mudança num invalidaria em
silêncio os arquivos já commitados do outro. **Não importe `persistence` aqui.**

## Invariantes

- Todo `DatasetError` nomeia o valor ofensivo: arquivo, índice da mensagem e
  campo (`case-01-..., messages[12]: field 'role' has an unknown value 'bot'`).
- `load_dataset` falha se o diretório não existe, se não há `case-*.json`, ou se
  o manifesto discorda dos arquivos presentes (caso renomeado/apagado).
- Ordem dos casos = ordem alfabética dos arquivos; o manifesto só confirma.
- `describe` conta tokens com `CharProxyTokenCounter`, o mesmo contador das
  políticas. Nenhum número de token é calculado por fora dele.
- `window_tokens` vem de `config.WindowConfig` por padrão; nada de `8000` inline.
- `describe` não escreve nada e não faz rede: é leitura pura.

## Testes

`tests/infrastructure/datasets/`: round trip do codec (inclusive `pinned` e
`metadata`), arquivo malformado nomeando o campo, diretório ausente/vazio,
`limit`, e as invariantes do dataset commitado (fatos nas três posições, sondas
que apontam para fatos existentes, resposta encontrável por `answer_matches`,
saídas de ferramenta acima dos tetos de truncagem, histórico que estoura a
janela com folga).

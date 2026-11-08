# tests/infrastructure/datasets/

Espelho de `src/caio_code/infrastructure/datasets/`. Cobre o codec JSON dos
casos, o loader/estatísticas e **as invariantes do dataset commitado**.

| Arquivo | Cobre |
|---|---|
| `test_dataset_codec.py` | `codec.py`: round trip, schema, manifesto, campos malformados |
| `test_dataset_loader.py` | `loader.py`: `load_dataset`, `limit`, `describe`, `format_stats` |
| `test_committed_dataset.py` | os JSON versionados em `evals/datasets/long_histories/` (e `long_histories_128k/`, quando presente) + a derivação da variante `spill` (`derive_spill_case`/`variant_case`) |

## Por que os nomes não são `test_codec.py` / `test_loader.py`

`tests/infrastructure/persistence/test_codec.py` já existe e o pytest importa os
testes por nome de módulo sem `__init__.py`: dois `test_codec.py` colidem na
coleta. Os nomes aqui são únicos de propósito. Não renomeie sem resolver a
colisão (pacotes com `__init__.py` em `tests/` seria a alternativa).

## Invariantes destes testes

- `test_committed_dataset.py` **não** importa o gerador: ele lê os arquivos
  versionados. Se alguém regenerar o dataset com um gerador quebrado, é aqui que
  falha — e a correção é no gerador, nunca neste teste.
- Os limites do desenho (60-140 mensagens, 60k-200k caracteres, 6-8 fatos,
  3-5 sondas, 2 fatos por posição) são constantes nomeadas no topo do arquivo;
  os tetos de truncagem e a janela vêm de `config.py`.
- Propriedade central: a resposta de cada fato é encontrável por `answer_matches`
  na mensagem que o declara (`message_index`), o `expected` de cada sonda é
  encontrável na mesma mensagem, e a resposta aparece **uma única vez** no
  histórico inteiro (texto + argumentos de tool call, que é o que o modelo vê).
  Sem isso a sonda mede sorte, não retenção.
- O teste de truncagem exige que o fato escondido numa saída grande **morra**
  com `truncate_text` e não exista em nenhuma outra mensagem; e que as saídas
  pequenas sobrevivam intactas (o contraste entre os braços).
- A variante `spill` é derivada em runtime do caso commitado: o dataset no disco não muda.
  O guard exige que todo caso derive pelo menos um arquivo de spill (bytes acima do teto de
  `ToolOutputConfig.max_bytes`) e que papéis/`tool_call_id`/`tool_calls` sejam preservados.
- Offline e determinístico: nenhum teste chama modelo, rede ou relógio.

## Como rodar

```bash
.venv/bin/python -m pytest tests/infrastructure/datasets -q
```

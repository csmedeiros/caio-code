# tests/datagen/

Testes de `datagen/scripts/convert.py` — a metade **determinística** da geração
sintética. O Data Designer fornece conteúdo; `convert.py` impõe estrutura, e é a
estrutura que estes testes protegem.

| Arquivo | Cobre |
|---|---|
| `test_convert.py` | ids sequenciais e primeira mensagem pinned, pareamento `tool_calls` ↔ `tool_call_id`, expansão acima dos **dois** tetos de truncagem, seleção de fatos por unicidade medida, recusa de respostas ambíguas ou reveladas pelo contrato, mensagem de contrato no último quinto fora dos índices reservados, fato embutido na mensagem que o referencia |

## Invariantes

- Offline por contrato: nenhum teste chama modelo nem rede. Os pools de blocos
  são sintéticos e pequenos; só a lógica de montagem é exercitada.
- `convert.py` é script, não módulo do pacote: é carregado com
  `importlib.util.spec_from_file_location`, como `tests/evals/` faz com
  `generate_dataset.py`.
- O que falha aqui é o que corromperia o Capítulo 4 **em silêncio**: um fato
  cuja resposta aparece em outra mensagem permite acertar a sonda sem ter
  retido o original, e uma saída de ferramenta abaixo dos tetos torna os braços
  de truncagem indistinguíveis do baseline.
- Helpers de candidato usam varargs (`_candidate(answer, *aliases)`):
  `("x")` é string, não tupla, e iterar uma string produz aliases de uma letra
  que casam com qualquer mensagem por subcadena.

## O que não entra aqui

Validação do dataset **pronto** — essa é `datagen/scripts/validate.py`, rodada
sobre os arquivos versionados, e não um teste unitário.

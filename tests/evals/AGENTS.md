# tests/evals/

Testes do **gerador** do dataset (`evals/generate_dataset.py`). As invariantes
dos arquivos já versionados ficam em `tests/infrastructure/datasets/
test_committed_dataset.py`; aqui o alvo é o gerador: se ele deixar de ser
determinístico ou de validar o desenho, é este diretório que falha.

| Arquivo | Cobre |
|---|---|
| `test_generate_dataset.py` | determinismo, ids, aritmética das posições, builders de saída, validações do gerador e a CLI |

## Invariantes destes testes

- O gerador é um script, não um módulo do pacote: ele é carregado por caminho de
  arquivo com `importlib` e registrado em `sys.modules` **antes** de executar
  (`dataclasses` com `slots=True` precisa resolver o módulo das anotações).
- Determinismo é medido em bytes: `build_dataset(seed)` duas vezes ⇒ JSON
  idêntico; `seed + 1` ⇒ conteúdo diferente com os mesmos ids de caso.
- O que está commitado é reproduzível: `test_committed_files_are_the_generators_output`
  compara o texto de cada arquivo versionado com uma geração nova no seed
  padrão. Se falhar, alguém editou JSON à mão ou esqueceu de regenerar.
- `test_the_generator_source_has_no_nondeterminism` lê o fonte do gerador e
  proíbe `time`, `uuid`, `datetime` e qualquer chamada aos globais `random.*`.
- As validações do gerador são testadas **quebrando o spec** (resposta que não
  aparece no histórico, posição ausente, sonda sem pergunta, contagem de
  mensagens fora da faixa): um gerador que aceita um dataset fora do desenho é o
  bug, não o teste.
- Offline: nada de rede, modelo ou relógio. Cada teste que constrói o dataset
  inteiro leva frações de segundo.

## Como rodar

```bash
.venv/bin/python -m pytest tests/evals -q
```

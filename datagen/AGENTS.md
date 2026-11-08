# datagen/

Geração de datasets sintéticos de avaliação com **NeMo Data Designer** (NVIDIA,
`data-designer` no PyPI, Apache-2.0). Pasta dedicada: aqui vive a *receita* de geração
(config JSON + scripts), não o dataset final.

O dataset final é **congelado e versionado** em `evals/datasets/<nome>/`, como o contrato
de `evals/AGENTS.md` exige.

## Layout

| Caminho | Papel |
|---|---|
| `configs/providers.yaml` | registro declarativo de provider + model aliases do Data Designer |
| `configs/long_histories_128k.json` | **o build config**: casos, alvos de tamanho, seeds e os schemas de coluna |
| `scripts/setup_models.py` | instala `providers.yaml` em `~/.data-designer/` (idempotente) |
| `scripts/generate.py` | roda `data-designer create` por caso (blocos de conteúdo + fatos críticos) |
| `scripts/convert.py` | monta o `HistoryCase` JSON a partir da saída bruta, via `infrastructure/datasets/codec.py` |
| `scripts/validate.py` | aplica o contrato de desenho e escreve o manifesto de hashes |
| `output/` | artefatos brutos do Data Designer (gitignored, regeneráveis) |
| `.venv/` | venv **isolado** do Data Designer (gitignored) |

O venv é isolado de propósito: o Data Designer puxa `pandas`, `pyarrow`,
`huggingface-hub`, `typer` e OpenTelemetry. Nada disso pode entrar nas dependências
pinadas do agente.

## Divisão de responsabilidade (invariante central)

O Data Designer gera **conteúdo**; o conversor impõe **estrutura**.

- **Data Designer** produz blocos realistas e variados: turnos de usuário, turnos de
  assistente, saídas de ferramenta, trechos de código, logs, diffs — mais um pool de
  fatos críticos com `statement`/`answer`/`aliases`.
- **`convert.py`** determina tudo que o experimento precisa ser exato: ordem e
  alternância de papéis, pareamento `tool_calls` ↔ `tool_call_id`, ids de mensagem
  (`<case>-mNNN`), posição dos fatos (early/middle/late), sondas, mensagem de contrato,
  `pinned` da primeira mensagem e o `metadata` do caso.

Nenhum invariante estrutural do dataset é delegado a um modelo. Se um fato precisa estar
no índice N com aliases conhecidos para a pontuação ser exata, quem coloca lá é o
conversor, deterministicamente.

## Determinismo: o que muda e por quê

`evals/generate_dataset.py` é regenerável byte a byte (`random.Random(seed)`, sem relógio,
sem uuid) e `tests/evals/test_generate_dataset.py` prova que os arquivos versionados **são**
a saída do gerador.

Um gerador dirigido por LLM não tem essa propriedade: mesma seed e mesma config **não**
reproduzem os mesmos bytes, porque o provedor não é determinístico. Portanto, para os
datasets gerados aqui o contrato passa a ser:

> O artefato versionado **é** a fonte de verdade. A reprodutibilidade é por **hash fixado**,
> não por regeneração.

Consequências obrigatórias:

1. `validate.py` escreve `BUILDINFO.json` com o sha256 de cada arquivo do dataset, a
   versão do Data Designer, o alias/modelo do provedor, o fingerprint da config e a seed
   usada. Sem isso o dataset não pode virar número de capítulo.
2. O dataset antigo em `evals/datasets/long_histories/` **não é tocado**. Ele continua
   regenerável e os testes antigos continuam valendo para ele.
3. Um dataset gerado aqui nunca sobrescreve o antigo no mesmo diretório.

## Como rodar

```bash
cd datagen
python3 -m venv .venv && .venv/bin/python -m pip install data-designer   # uma vez

set -a && . ../../.env && set +a           # OPENAI_API_KEY / OPENAI_BASE_URL (o .env vive na raiz do TCC)
.venv/bin/python scripts/setup_models.py   # registra provider + aliases
.venv/bin/python scripts/generate.py --config configs/long_histories_128k.json --case case-01 --dry-run
.venv/bin/python scripts/generate.py --config configs/long_histories_128k.json
.venv/bin/python scripts/convert.py  --config configs/long_histories_128k.json
.venv/bin/python scripts/validate.py --config configs/long_histories_128k.json
```

`generate.py` **custa dinheiro**: cada bloco é uma chamada de modelo. Use `--dry-run`
para ver a contagem de chamadas e o custo estimado antes de rodar, e `--case` para
gerar um caso por vez.

## Regras

- Nada aqui é importado por `src/caio_code/`. A dependência é de mão única: `convert.py`
  importa o codec do agente, o agente nunca importa `datagen/`.
- Segredos só por variável de ambiente. `providers.yaml` guarda o **nome** da variável
  (`OPENAI_API_KEY`), nunca o valor — é assim que o Data Designer modela provider.
- Número mágico não entra em script: alvos de tamanho, seeds e contagens vivem no build
  config JSON.
- `output/` é descartável; `evals/datasets/<nome>/` é o artefato.

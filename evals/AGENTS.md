# evals/

O experimento do Capítulo 4 e o **dataset congelado** que ele mede. Nada aqui é
gerado em tempo de execução por um modelo: o dataset é sintético e versionado.

## Conteúdo

| Caminho | Papel |
|---|---|
| `generate_dataset.py` | Gerador determinístico dos cinco casos. CLI: `--out DIR`, `--seed N`, `--dry-run` |
| `prompts/judge_v1.md` | Prompt do juiz LLM do chat-replay (nota binária, nunca vê o contexto). **Versionado: revisão é `judge_v2.md`, nunca edição do v1** |
| `datasets/long_histories/case-NN-<slug>.json` | Os cinco históricos longos, **commitados** |
| `datasets/long_histories/dataset.json` | Manifesto: `name`, `seed`, `generator`, `cases` |
| `datasets/long_histories_128k/` | Dataset maior (~128k proxy tokens/caso), gerado por `datagen/` |

```bash
.venv/bin/python evals/generate_dataset.py                 # regenera no lugar
.venv/bin/python evals/generate_dataset.py --dry-run       # valida e imprime a tabela
.venv/bin/python evals/generate_dataset.py --out /tmp/x --seed 7
```

## Duas classes de dataset, dois contratos de reprodutibilidade

| | `long_histories` | `long_histories_128k` |
|---|---|---|
| Gerador | `evals/generate_dataset.py` | `datagen/` (NeMo Data Designer + `convert.py`) |
| Conteúdo | templates determinísticos | blocos escritos por LLM |
| Reprodutível byte a byte? | **sim** (`random.Random(seed)`) | **não** — provedor não é determinístico |
| Contrato | regeneração prova identidade | **hash fixado** em `BUILDINFO.json` |
| Teste | `tests/evals/`, `tests/infrastructure/datasets/` | `datagen/scripts/validate.py` |

O contrato abaixo ("Contrato de determinismo" e "O desenho experimental") vale
para `long_histories`. Para `long_histories_128k` o artefato versionado **é** a
fonte de verdade: ele não é regenerável, é *hash-pinned*. Detalhes e rationale em
`datagen/AGENTS.md`.

O que **não** muda entre as duas classes: o schema dos arquivos, o desenho
early/middle/late, a regra de resposta única e a exigência de saídas de
ferramenta acima dos tetos de truncagem. `convert.py` impõe tudo isso
deterministicamente — o modelo só fornece conteúdo, nunca estrutura.

Selecione o dataset com `CAIO_CODE_EVAL_DATASET=evals/datasets/long_histories_128k`.

## Contrato de determinismo

- Só `random.Random(seed)`; nunca os globais `random.*`, nunca relógio, nunca
  `uuid`. O seed vem de `config.EvalConfig.seed` (padrão `20261031`); o stream de
  cada caso é `seed + index`, para um caso não mudar quando outro é reordenado.
- Ids seguem o índice final: mensagem `{case_id}-m{index:03d}`, tool call
  `{case_id}-tc{index:03d}`, fato `{case_id}-f{NN}`, sonda `{case_id}-p{NN}`.
- Serialização: `sort_keys=True`, indent 2, `ensure_ascii=False`, newline final.
  Mesmo seed ⇒ mesmos bytes (testado em `tests/evals/`).
- Todo número que molda os dados é constante nomeada no topo do módulo ou vem de
  `config.py`. Nada de literal inline.

## O desenho experimental (o que o gerador valida antes de escrever)

- 60-140 mensagens e 60k-200k caracteres por caso ⇒ 4x-6x a janela de
  `WindowConfig.tokens` (8k) na proxy `ceil(chars/4)`.
- Mensagem 0 = tarefa do usuário, `pinned=True`. Um único `contract` fixado no
  último quinto, e ele **não** pode repetir a resposta de nenhum fato (senão uma
  política que só preserva mensagens fixadas acertaria a sonda).
- 6-8 `CriticalFact` por caso, com ≥2 em cada posição (`early`/`middle`/`late` =
  primeiro/último 20% do histórico), cada um com `message_index` e 1-3 aliases.
- A resposta de cada fato aparece **literalmente** na mensagem que o declara
  (`answer_matches`), e a resposta esperada de cada sonda também.
- **Uma vez só.** A resposta de um fato (ou qualquer alias) não pode aparecer em
  nenhuma outra mensagem — nem no filler, nem no alvo de uma ferramenta, nem
  numa decisão duplicada. O que o modelo vê inclui os argumentos da tool call.
  Se a resposta aparece duas vezes, uma política que preserve a outra mensagem
  acerta a sonda sem ter retido o original, e o número do capítulo não significa
  nada. Por isso as respostas são frases ("the defect that double-charges
  pending payments is in src/payments/reconciler.py"), e a forma curta vai no
  `expected`/`aliases` da **sonda**, que é comparada contra a resposta do modelo.
  A verificação roda duas vezes: no spec (nomeia a string ofensora antes de tecer
  o histórico) e no caso pronto.
- 3-5 `Probe` por caso, cada uma sobre um fato diferente, cobrindo ≥2 posições.
- ≥4 resultados de ferramenta por caso, ≥2 acima de um teto de truncagem
  (`ToolOutputConfig.max_lines` / `max_bytes`), e ≥1 fato que **só** existe
  dentro de uma saída grande: `truncate_text` precisa destruí-lo e nenhuma outra
  mensagem pode repeti-lo. É esse contraste que a tese reporta.
- Distratores: ≥1 decisão superseded (o valor antigo vem antes e não contém a
  resposta corrigida), ≥2 mensagens quase duplicadas (nunca cópia da mensagem que
  declara um fato) e ≥1 tool call repetida `GuardrailConfig.max_repeats` vezes
  com argumentos idênticos — o padrão que o guardrail de loop existe para pegar.
- 2-4 chamadas `write_todos` cujo board evolui (no máximo um `in_progress`, e o
  número de `completed` só cresce).

Falhar qualquer uma dessas invariantes levanta `DatasetError` e **nada é
escrito**: um dataset fora do desenho não pode virar número de capítulo.

## Regras

- Sem rede, sem chamada de modelo: o dataset é sintético.
- **`make evaluate` (stub) não valida os braços de compactação.** O
  `StubSummarizer` ignora `max_tokens` de propósito — o comentário no próprio
  stub diz que truncar o resumo quebraria a invariantes de boa formação que
  todo chamador usa. Num histórico de 128k tokens ele devolve um resumo maior
  que a cabeça que o originou, então `anchored_compaction*` aparece com
  `overflow=100%` **offline** mesmo com o budget correto. O
  `OpenAICompatibleSummarizer` repassa `max_tokens` ao provedor, portanto o
  teto de resumo só existe de verdade no run live. Offline vale para os braços
  de janela/seleção/truncagem; compactação, só live.
- Não edite os JSON à mão. Mudou o desenho ⇒ mude o gerador ⇒ regenere ⇒
  commite os arquivos junto.
- O schema dos arquivos está documentado em
  `src/caio_code/infrastructure/datasets/AGENTS.md`; quem carrega é
  `load_dataset`. O gerador escreve com `case_to_dict`/`dataset_to_dict`, então
  gerador e leitor não podem divergir.
- `generate_dataset.py` é script, não módulo do pacote: ele insere `src/` no
  `sys.path` e importa `caio_code` normalmente.

## Testes

`tests/evals/test_generate_dataset.py` (determinismo, ids, aritmética das
posições, validações que recusam um spec quebrado, CLI) e
`tests/infrastructure/datasets/test_committed_dataset.py` (as invariantes acima,
lidas dos arquivos versionados, sem passar pelo gerador).

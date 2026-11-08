# src/caio_code/infrastructure/

Adaptadores: implementam as portas de `domain/ports/` e traduzem entre o domínio e o mundo
externo (SDKs, arquivos, relógio real, LangChain).

## Subpacotes

| Pacote | Adapta |
|---|---|
| `llm/` | `ModelGateway`, `Summarizer`, `RelevanceScorer` → stub, endpoint OpenAI-compatible + factory |
| `decision/` | `DecisionModel` (porta de decisão, ADR 0005) → TypeSafe Jev, stub offline, scorer de relevância, advisor de risco + factory |
| `tokens/` | `TokenCounter` → char proxy (padrão/CI) e tiktoken (opt-in) |
| `tools/` | as SWE tools confinadas ao sandbox + seleção de backend do deepagents |
| `middleware/` | `ContextPolicyMiddleware`: aplica o pipeline de políticas a cada model call do grafo |
| `mappers/` | `Message` ↔ `BaseMessage` (round trip sem perda) e aplicação de decisão por índice |
| `persistence/` | `TranscriptStore`/`ResultStore` → JSON envelope e JSONL com fsync |
| `datasets/` | codec/loader do dataset congelado de avaliação |
| `observability/` | `Clock`/`IdentifierFactory` reais e determinísticos, registro de eventos, LangSmith |
| `pricing/` | ponte entre `config.PRICE_SHEET` e os objetos de `domain/usage/` |

## Invariantes

- Importa `domain` (e `config`); importa `application` só onde um caso de uso é orquestrado
  (ADR 0003). `presentation` nunca.
- Nenhum SDK vaza: LangChain/openai/deepagents/textual só aparecem aqui (e nos pontos de
  orquestração nomeados no ADR 0003). O domínio nunca importa LangChain; `mappers/` é a única
  ponte de mensagens.
- `SystemClock`/`datetime.now` só na raiz de composição (`llm/factory.py`,
  `presentation/cli/composition.py`); o resto recebe `Clock` injetado.
- Credencial ausente → `ConfigurationError` nomeando a variável; valor de segredo nunca é
  impresso nem interpolado em mensagem de erro.

## Testes

`tests/infrastructure/<pacote>/`, sempre offline: stubs, `FixedClock`, `tmp_path`.

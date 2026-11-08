# infrastructure/llm/

Adaptadores das portas de modelo (`ModelGateway`, `Summarizer`, `RelevanceScorer`).

## O que vive aqui

| Módulo | Conteúdo |
|---|---|
| `stub.py` | `StubGateway` (com `keyword_tool_calls` roteirizado), `StubSummarizer`, `StubScorer`, `StubJudgeGateway` (juiz offline por substring de gold/aliases): doubles determinísticos, os únicos que testes e CI usam |
| `openai_compatible.py` | `OpenAICompatibleGateway` (SDK `openai` direto, sem LangChain), `OpenAICompatibleSummarizer`, `ModelRelevanceScorer` |
| `factory.py` | `build_gateway`/`build_summarizer`/`build_scorer`: o switch `provider`/`aux_provider` da raiz de composição |

## Invariantes

- Determinismo: nenhum módulo aqui chama `time.time()`, `datetime.now()`, `random` ou
  `uuid4`. Latência vem do `Clock` injetado; o atraso de retry é fixo e o `sleep` é injetável.
- Erros tipados: credencial ausente → `ConfigurationError` nomeando a variável de ambiente;
  falha de transporte/auth → `ProviderError` após no máximo `ProviderConfig.max_retries`
  tentativas; resumo vazio → `SummarizerError`. A chave de API nunca aparece em mensagem.
- `ModelRelevanceScorer` nunca propaga falha de parse/transporte: degrada para o
  `fallback` injetado.
- `StubSummarizer` sempre devolve resumo ancorado bem formado
  (`parse_summary(text).is_well_formed`), com as cinco seções e as três subseções de
  Work State.
- TypeSafe não entra aqui: Jev é modelo de decisão, não de chat (ADR 0005); vive em
  `infrastructure/decision/`. Pedir `typesafe` à factory levanta `ConfigurationError` explicativo.
- Números vêm de `config.py` ou de constantes nomeadas do módulo (`RETRY_DELAY_SECONDS`,
  `SCORER_MESSAGE_CHAR_CAP`).

## O que nunca entra aqui

- LangChain (o mapeamento de mensagens é do `infrastructure/mappers/`).
- Política de contexto, loop agêntico, leitura direta de `os.environ` (config vem pronta
  da raiz de composição).

## Como é testado

`tests/infrastructure/llm/`, offline: o gateway real é exercitado com clientes `openai`
falsos injetados; nada de rede. Teste que exige endpoint real leva
`@pytest.mark.integration` e não roda no CI.

# infrastructure/decision/

Adaptadores da porta de decisão (`domain/ports/decision.py`). O modelo Jev da TypeSafe
responde perguntas tipadas (Noul/Choice/Score) com probabilidades — ele **não** é um modelo
de chat, não resume e não gera código, portanto nunca aparece atrás das portas
`ModelGateway`/`Summarizer` (ADR 0005).

## O que vive aqui

| Módulo | Conteúdo |
|---|---|
| `typesafe.py` | `TypeSafeDecisionModel`: porta `DecisionModel` sobre `TypeSafeClassifier` (SDK `langchain_typesafe`); mapeia perguntas/respostas/usage entre domínio e SDK |
| `stub.py` | `StubDecisionModel`: determinístico e offline; probabilidades derivadas de SHA-256 do id da pergunta + texto do estado (derivação documentada no módulo) |
| `scorer.py` | `DecisionRelevanceScorer`: um Noul por mensagem ("o agente vai precisar disto depois?"), probabilidade de yes como score de relevância; batching e teto de chars via `DecisionConfig` |
| `risk.py` | `DecisionRiskAdvisor`: advisor de risco para tool calls, comparável ao `AutoModeMiddleware` do LangChain; consultivo — nunca executa nem bloqueia nada |
| `factory.py` | `build_decision_model`/`build_decision_scorer`: switch `DecisionConfig.provider` da raiz de composição |

## Invariantes

- **Nenhum módulo aqui lê o ambiente.** O construtor do adaptador recebe as peças resolvidas
  (`api_key`, `model`, `base_url`, `timeout_seconds`, `clock`); só a factory lê `Settings`.
- Chave ausente → `ConfigurationError` nomeando `TYPESAFE_API_KEY`. Falha de SDK/transporte →
  `ProviderError` que mantém o status HTTP e o request id, e **nunca** a chave nem o estado
  classificado.
- Determinismo: latência só pelo `Clock` injetado; o stub é reproduzível entre processos
  (SHA-256, nunca `hash()`).
- Números vêm de `DecisionConfig` (`state_message_char_cap`, `questions_per_request`,
  `relevance_threshold`, `risk_threshold`) ou de constantes nomeadas do módulo
  (`MAX_RECENT_MESSAGES`, `HASH_BYTES`).
- `DecisionRelevanceScorer` nunca levanta erro para dentro do loop do agente: qualquer
  `CaioCodeError` ou resposta ausente degrada para o `fallback` injetado, com nota em
  `last_note`.
- Uso de tokens é atribuído ao braço que o scorer/advisor serviu via
  `UsageReporting.drain_usage()` — um scorer que custa mais do que economiza não é vitória,
  e o relatório precisa mostrar isso.

## O que nunca entra aqui

- LangChain como loop de agente (o mapeamento de mensagens é do `infrastructure/mappers/`),
  política de contexto, leitura direta de `os.environ`, impressão de segredo.

## Como é testado

`tests/infrastructure/decision/`, offline: o adaptador real é exercitado com clientes
`httpx2` fake (MockTransport) ou classifiers falsos injetados; nada abre socket. Teste que
exigisse a API real levaria `@pytest.mark.integration`.

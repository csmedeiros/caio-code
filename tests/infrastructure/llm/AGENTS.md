# tests/infrastructure/llm/

Testes dos adaptadores de modelo, todos offline.

| Arquivo | Cobre |
|---|---|
| `test_stub.py` | `StubGateway` (round-robin/keywords, usage via char proxy, `FixedClock`), `StubSummarizer` (sempre bem formado), `StubScorer` (overlap lexical, desempate por recência) |
| `test_openai_compatible.py` | mapeamento defensivo de usage (`prompt_tokens_details.cached_tokens` ausente/presente), retries limitados com sleep injetado, `ProviderError`/`ConfigurationError`, chave nunca aparece na mensagem |
| `test_factory.py` | switch `provider`/`aux_provider`; provedor real sem credencial → `ConfigurationError` nomeando a variável; pedido do provider de chat `typesafe` → `ConfigurationError` explicando que Jev é modelo de decisão (`infrastructure/decision/`, ADR 0005); `scorer="decision"` → `DecisionRelevanceScorer` |

Invariantes: nenhum teste abre socket; o cliente openai é substituído por transport fake ou
monkeypatch. Teste que exigisse endpoint real levaria `@pytest.mark.integration` (não há).

# tests/infrastructure/decision/

Testes dos adaptadores da porta de decisão, todos offline (nenhum socket, nenhuma chave).

| Arquivo | Cobre |
|---|---|
| `test_stub.py` | `StubDecisionModel`: determinismo, conformidade com o porto `DecisionModel`, probabilidades em [0, 1], usage determinístico via char proxy |
| `test_typesafe.py` | `TypeSafeDecisionModel` com clientes `httpx2` fake (MockTransport) injetados: mapeamento dos três tipos de pergunta e dos três tipos de resposta, usage → `TokenUsage`; chave ausente → `ConfigurationError` nomeando `TYPESAFE_API_KEY`; HTTP 401/429/500 → `ProviderError` com o status e sem a chave |
| `test_scorer.py` | `DecisionRelevanceScorer`: um score por mensagem em ordem, teto de chars do estado, batching em `questions_per_request` (90 mensagens → 3 requests), uso acumulado por batch, `drain_usage()` esvazia o buffer, degradação para o fallback com `last_note` não vazio |
| `test_risk.py` | `DecisionRiskAdvisor`: risky acima/abaixo do `risk_threshold`, usage reportado |
| `test_factory.py` | `build_decision_model`/`build_decision_scorer`: stub default, typesafe sem chave → `ConfigurationError`, typesafe com chave constrói o adaptador |

Invariantes: o adaptador real nunca é exercitado contra a rede — o transport é sempre fake.
Teste que exigisse a API real levaria `@pytest.mark.integration` (não há).

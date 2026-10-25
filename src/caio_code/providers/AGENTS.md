# src/caio_code/providers/

Adaptadores de modelo. O resto do código depende do protocolo, nunca de um SDK.

## Invariantes

- `base.py` define o contrato (`complete(messages) -> str` ou equivalente) e as exceções
  tipadas (`ProviderError`, `ProviderTimeout`).
- **Nenhum `import anthropic` fora desta pasta.** É a regra que mantém o harness testável.
- `stub.py` é determinístico, offline e o default em testes e no CI.
- Erro de rede vira exceção tipada com retry limitado e explícito — nunca loop infinito.
- Nenhum provedor imprime, loga ou persiste chave de API.

## Implementações

| Arquivo | Uso |
|---|---|
| `stub.py` | testes, CI, smoke test multiplataforma |
| `anthropic.py` | execução real; só roda com `ANTHROPIC_API_KEY` |

Teste que usa modelo real leva `@pytest.mark.integration` e fica fora do CI.

## O que não entra aqui

Decisão de orçamento de contexto, parsing de ação do agente, política de retry de ferramenta.
# tests/application/evaluation/

Testes offline da avaliação por chat-replay (`src/caio_code/application/evaluation/`).

| Arquivo | Cobre |
|---|---|
| `test_replay_tools.py` | índice de interações gravadas, reads de spill, miss tipado, teto e contagem |
| `test_judge.py` | render do prompt, parse tolerante de veredictos, veredito ausente = erro, calibração e portão de concordância |
| `test_replay.py` | ciclo completo seed → molda → sonda → juiz; garantia de estouro; variante spill ponta a ponta com modelo roteirizado que lê o arquivo de spill; agregados por (braço, variante); relatórios em `tmp_path` |

## Invariantes

- Tudo offline: `StubGateway`/`StubJudgeGateway`/`StubSummarizer`/`StubScorer`,
  `FixedClock`, `SequentialIdentifiers`, `tmp_path`. Nenhum teste chama endpoint
  real (isso exigiria `@pytest.mark.integration` e não roda no CI).
- Dataset pequeno construído no teste (mensagens sintéticas que transbordam a
  janela declarada), nunca o dataset de 128k.
- O cenário "modelo lê o spill e acerta a sonda" usa `keyword_tool_calls` do
  `StubGateway`: prova que a recuperabilidade é mensurável sem provedor real.

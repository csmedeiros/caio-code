# Como reproduzir `chapter4-main-v4`

Run autoritário do Capítulo 4: 11 braços x 5 casos x 3 repetições = 165 trials,
`qwen3.8-max`, janela declarada 8.000 tokens, custo total $7.5541.

```bash
cd caio-code
set -a && . ../.env && set +a        # OPENAI_API_KEY, OPENAI_BASE_URL, TYPESAFE_API_KEY
make evaluate-live EVAL_RUN_ID=chapter4-main-v4
```

O alvo expande para:

```bash
CAIO_CODE_PROVIDER=openai_compatible \
CAIO_CODE_TIMEOUT_SECONDS=420 \
CAIO_CODE_MAX_RETRIES=1 \
CAIO_CODE_DECISION_TIMEOUT_SECONDS=180 \
.venv/bin/python -m caio_code evaluate --concurrency 5 \
    --out .reports/evals --run-id chapter4-main-v4
```

Condições que não podem mudar sem invalidar a comparação:

| Parâmetro | Valor | Por quê |
|---|---|---|
| `CAIO_CODE_TIMEOUT_SECONDS` | 420 | com o default de 120 s, 20 trials morrem em `APITimeoutError` distribuídos por 7 braços (run `chapter4-main-v3`); a assimetria invalida a comparação |
| `CAIO_CODE_MAX_RETRIES` | 1 | igual a `chapter4-main-v2`; mais retries escondem latência real do endpoint |
| `--concurrency` | 5 | mesma pressão no endpoint compartilhado dos runs anteriores |
| dataset | `evals/datasets/long_histories` congelado, seed 20261031 | determinismo verificado por `make dataset` |
| `TYPESAFE_API_KEY` | presente | sem ela os braços `*_decision` caem no `StubDecisionModel` e deixam de medir o Jev |

Leitura dos resultados:

```bash
python scripts/summarize_experiment.py --run chapter4-main-v4   # também gravado em summary.txt
```

# Calibração do juiz — reconferência do run `chapter4-main-v5-pilot`

Data: 2026-11-08.

O `calibration-report.json` registra **29/30 (96,7%)** de concordância. Ao
reconferir o relatório contra os artefatos, pareando `calibration-labels.json`
com `calibration-sample.json` na mesma ordem de `calibration-items.jsonl`,
o resultado correto é **28/30 (93,3%)**.

## Divergências

| Item (n) | Probe | Label | Juiz | Observação |
|---|---|---|---|---|
| 16 | `case-01-api-service-debug-p06` | correto | incorreto | Já listado em `calibration-report.json`. A resposta contém o caminho gold, mas em seguida o desmente ("that path appears in no tool output and is unverified"). Pela regra de alias, o label "correto" é defensável; o juiz errou. É a discordância genuína do conjunto. |
| 30 | `case-01-api-service-debug-p05` | correto | incorreto | **Não** listado no relatório. A resposta diz que a variável pedida "is not present" e lista outras; não menciona `PAYMENTS_DB_POOL_LIMIT`. O label "correto" é erro de rotulagem; o juiz acertou. |

## Número adotado

Com os labels como estão gravados: **28/30 = 93,3%**. Corrigindo o label do item
30 para "incorreto", a concordância sobe para **29/30 = 96,7%** — o número que o
`calibration-report.json` já registrava, ainda que sem a entrada de divergência
correspondente. Os dois números passam o portão de 90%; o capítulo cita o
conservador, **28/30**, e explica a diferença. O `calibration-report.json`
original é preservado sem edição, e esta nota é a reconciliação.

O item 30 não muda a conclusão (o portão passa em ambos os números), mas muda o
número citado: a partir desta reconferência, 28/30, não 29/30.
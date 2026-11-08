# tests/application/selection/

Testes do `SelectionService`: scores na ordem do transcript, `with_scores` preserva os campos
do `PolicyRequest`, scorer com contagem errada ou índices duplicados degrada
(`degraded=True`, nota, request original devolvido), `top_indices` por (-score, índice).

Invariantes: só scorers stub (lexical e um quebrado de propósito); nenhum modelo real.

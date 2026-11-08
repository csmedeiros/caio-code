# src/caio_code/application/selection/

O caso de uso de scoring de relevância — a costura entre a política pura e quem produz scores.

## Módulos

`service.py`: `SelectionService(scorer)` com `score/ascore(task, transcript) ->
ScoringOutcome` e `with_scores(request, task)` (cópia do `PolicyRequest` com scores prontos
para a `MessageSelectionPolicy`).

## Invariantes

- A política de seleção (domínio) é pura e recebe scores; produzi-los é infraestrutura
  (`StubScorer` lexical offline, `ModelRelevanceScorer` via endpoint auxiliar).
- Scorer que devolve contagem errada ou índices duplicados **degrada** para "sem scores"
  (`ScoringOutcome.degraded`, com nota) — a política responde com recência. Nunca levanta
  erro para dentro do loop do agente.
- `with_scores` preserva os demais campos do request (budget, fixed_tokens,
  previous_summary, cap).
- Ordem determinística: `top_indices` por (-score, índice).

## Testes

`tests/application/selection/`, com scorers stub e um scorer quebrado de propósito para o
caminho de degradação.

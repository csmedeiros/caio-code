# tests/domain/evaluation/

Testes do núcleo puro de avaliação (`src/caio_code/domain/evaluation/`):
`cases.py` (variantes, `SpillFile`) e `spill.py` (derivação da variante
`spill`).

## Invariantes

- Domínio é puro: nada de I/O, relógio ou rede nestes testes; casos sintéticos
  construídos em memória.
- `derive_spill_case` é função pura e determinística: mesmas entradas ⇒ mesmo
  caso derivado; mensagens não truncadas sobrevivem por identidade de objeto.
- A variante `full` nunca carrega `spill_files`; um caso `spill` sem arquivos é
  erro (`DatasetError`).

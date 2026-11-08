# tests/domain/

Testes do núcleo puro. Espelham `src/caio_code/domain/`.

## Invariantes

- Teste do domínio não usa fixture de I/O: sem arquivo, rede, relógio ou bus real. Se precisa,
  o código testado está na camada errada.
- Transcripts de teste são construídos à mão com `Message`/`Transcript.of`, com custos
  previsíveis sob o char proxy (`ceil(chars/4)`).
- Orçamento, estouro e pinned são asserções de contrato: toda decisão reporta os próprios
  números.

## Subdiretórios

| Diretório | Cobre |
|---|---|
| `conversation/` | rendering indexado, split head/recent, template e parse do resumo ancorado |
| `evaluation/` | `test_spill.py`: derivação pura da variante `spill` (ponteiros, identidade, `DatasetError`) |
| `policy/` | `test_pipeline_and_policies.py`, `test_compaction.py`, `test_structure_repair.py` |

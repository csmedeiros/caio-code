# tests/application/compaction/

Testes do `CompactionService` (`test_service.py`): prompt lido do metadata da decisão,
eventos `CompactionStarted`/`CompactionEnded` na ordem, placeholder substituído pela mensagem
ancorada, re-medida de `tokens_after`, custo e usage do summarizer no outcome, resumo
malformado → `well_formed=False` sem destruir o head, `compact_sync` dentro de loop ativo →
`SummarizerError`.

Invariantes: `StubSummarizer`, `FixedClock`, bus em memória com `EventRecorder`; nada de rede.

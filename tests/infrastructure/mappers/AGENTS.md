# tests/infrastructure/mappers/

Testes de `infrastructure/mappers/langchain.py` (`test_langchain.py`): round trip sem perda
`to_domain(to_langchain(m)) == m` para as quatro roles (id, `pinned`, `tool_calls` com
arguments originais, `tool_call_id`, `name`, metadata via `additional_kwargs["caio_code"]`),
`apply_decision` preservando a **identidade de objeto** das mensagens mantidas (prompt cache),
substituições no lugar, injetadas em `insert_at`, `apply_pipeline` encadeando índices por
passo, tipo LangChain desconhecido → `ValueError`.

Invariantes: mensagens de fixture mínimas; identidade é assertada com `is`, não `==`.

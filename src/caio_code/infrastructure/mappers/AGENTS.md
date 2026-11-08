# infrastructure/mappers/

Tradutores entre o modelo de conversa do domínio e os tipos de mensagem dos provedores.

## O que vive aqui

`langchain.py`: `to_langchain(Message) -> BaseMessage`, `to_domain(BaseMessage) -> Message`,
`apply_decision(messages, PolicyDecision) -> list[BaseMessage]` e
`apply_pipeline(messages, PipelineDecision) -> list[BaseMessage]`.

## Invariantes

- **Round trip sem perda.** Id, `pinned`, `tool_calls` (com `arguments` originais),
  `tool_call_id`, `name`, `tokens` e o `metadata` do domínio viajam em
  `additional_kwargs["caio_code"]`; `to_domain(to_langchain(m)) == m` para toda mensagem.
- **Identidade preservada.** `apply_decision` mantém os MESMOS objetos `BaseMessage` para
  índices conservados — o prompt caching do provedor depende disso. Substituições entram no
  lugar, injetadas são convertidas do domínio e `insert_at` é respeitado exatamente como em
  `PolicyDecision.result`.
- Decisões são aplicadas **por índice** sobre a lista original; nada aqui recria a lista
  inteira do zero.
- `apply_pipeline` encadeia os passos: os índices de cada passo referem-se à saída do passo
  anterior, como na `PolicyPipeline` do domínio.
- Mensagem de tipo desconhecido levanta `ValueError` nomeando o tipo; nunca retorna lixo.

## O que nunca entra aqui

- Política de contexto (quem decide é `domain/policy/`; aqui só se aplica).
- Import de domínio em LangChain ou vice-versa fora deste módulo: o domínio nunca conhece
  `BaseMessage`.

## Como é testado

`tests/infrastructure/mappers/`, offline: round trip por papel (system/human/ai com
tool_calls/tool), preservação de identidade objeto a objeto, `insert_at` honrado,
substituição no lugar e pipeline de dois passos.

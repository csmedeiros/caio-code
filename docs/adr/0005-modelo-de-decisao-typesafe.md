# ADR 0005 — O modelo de decisão TypeSafe (Jev) atrás de uma porta própria

- **Status:** aceito
- **Data:** 2026-11-01

## Contexto

A TypeSafe oferece o Jev (`langchain-typesafe`), que o material do provedor descreve como um
**modelo de decisão**, não um modelo de linguagem: ele recebe um estado (texto, JSON ou
mensagens) e um conjunto de perguntas tipadas — `Noul` (probabilidade de yes), `Choice`
(distribuição sobre rótulos) e `Score` (posição esperada numa rubrica ordenada) — e devolve
probabilidades, confianças e uso de tokens. O Jev **não** resume, **não** gera código e
**não** continua uma conversa.

A primeira integração no repositório estava errada: um adaptador
`infrastructure/llm/typesafe.py` tratava o endpoint TypeSafe como um provedor de chat
OpenAI-compatible (gateway/summarizer). Esse adaptador foi removido; pedir `typesafe` como
provedor de chat agora é um `ConfigurationError` explicativo.

O agente precisa de dois julgamentos calibrados que um modelo de chat produz mal e caro: a
relevância de cada mensagem para a seleção de contexto, e o risco de uma tool call. O
orçamento do experimento exige que qualquer scorer custe menos do que os tokens que
economiza (ADR 0004c).

## Decisão

1. **Porta própria, nunca o gateway.** O Jev fica atrás da porta `DecisionModel`
   (`domain/ports/decision.py`: `aclassify/classify(State, questions) -> DecisionAnswers`) e
   dos adaptadores em `infrastructure/decision/` (`typesafe.py`, `stub.py`, `factory.py`).
   Ele nunca aparece atrás de `ModelGateway` ou `Summarizer`: quem pede um resumo ou uma
   resposta textual não pode receber uma probabilidade.
2. **Uso original: seleção de mensagens.** `DecisionRelevanceScorer`
   (`infrastructure/decision/scorer.py`) faz **um `Noul` por mensagem** — "o agente vai
   precisar da informação desta mensagem mais tarde para completar a tarefa?" — e usa a
   probabilidade de yes como score de relevância da política de seleção
   (`SelectionConfig.scorer = "decision"`). O segundo uso é consultivo:
   `DecisionRiskAdvisor` (`risk.py`) julga o risco de tool calls, comparável ao
   `AutoModeMiddleware` do próprio SDK, mas sem bloquear nada por conta própria — o guard
   determinístico `RepeatedToolCallGuard` continua sendo o que dispara no loop.
3. **Tetos de custo explícitos.** O estado é reenviado a cada requisição, portanto cada
   mensagem entra no estado com no máximo `DecisionConfig.state_message_char_cap` (600)
   caracteres, e no máximo `DecisionConfig.questions_per_request` (40) perguntas vão por
   requisição. Um scorer que custa mais tokens do que economiza não é vitória; o uso de cada
   batch é registrado.
4. **Uso atribuído ao braço.** Scorer e advisor implementam `UsageReporting.drain_usage()`;
   o experimento soma os tokens do modelo de decisão ao braço que ele serviu, precificados
   pela `PriceSheet` do domínio.
5. **Preço é estimativa.** O preço por token da TypeSafe **não é publicado** no material que
   temos; `jev-latest` cai no `FALLBACK_PRICE` conservador de `config.PRICE_SHEET` e o
   relatório do Capítulo 4 deve sinalizar esse custo como estimativa, não como fatura.
6. **Erros e segredos.** Chave ausente → `ConfigurationError` nomeando `TYPESAFE_API_KEY`.
   Falha de SDK/transporte → `ProviderError` que mantém o status HTTP e o request id e nunca
   contém a chave nem o estado classificado. No scorer, qualquer falha degrada para o scorer
   de fallback (lexical) com nota em `last_note`, sem levantar erro para o loop do agente.
   Testes dirigem o adaptador real com clientes `httpx2` fake injetados; nada de rede.

## Consequências

- O braço `message_selection` pode rodar com scorer lexical (grátis, offline), modelo de chat
  (JSON gerado) ou modelo de decisão (probabilidade calibrada) trocando só configuração — a
  política vê números nos três casos.
- A dependência `langchain-typesafe[experimental]` entra no runtime, mas o SDK só é importado
  pelo pacote `infrastructure/decision/`; o caminho de chat permanece independente.
- O custo do scorer de decisão aparece no relatório do braço; se ele não se pagar em tokens
  retidos, o número mostra. Para isso o trial separa duas contas: `probe_usage` (o que o
  modelo agente recebeu — a coluna comparável entre braços) e `aux_usage` (o que o braço
  gastou para moldar o contexto — resumidor e Jev). O custo total soma as duas; o
  `prompt tok` do relatório, não. Somar tudo numa coluna só faria o braço com julgamento
  parecer que envia mais contexto ao agente do que envia.
- `doctor` ganha uma seção de decisão (nomes, nunca valores) e `classify` é o menor cheque
  vivo de que o Jev responde.

## Alternativas descartadas

- **Jev como provedor de chat (o adaptador removido).** O endpoint `/v1/systemone` não fala
  `chat/completions`; mesmo que falasse, gerar texto não é o que o modelo faz. A integração
  original era um erro de categoria.
- **Jev atrás da porta `Summarizer`/`ModelGateway`.** Quebraria o contrato das portas
  (resposta textual) e escondia que a saída é probabilística.
- **Score de relevância por `Score` (rubrica 0–5) em vez de `Noul`.** A política precisa de
  um número comparável entre mensagens; a probabilidade de yes é diretamente esse número,
  com uma pergunta por mensagem e custo menor.
- **Advisor de risco que bloqueia tools (como o `AutoModeMiddleware`).** Bloqueio é decisão
  do runner; no protótipo o guard determinístico é o único que age, e o Jev apenas aconselha,
  mantendo o custo e o efeito mensuráveis no experimento.

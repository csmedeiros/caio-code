# ADR 0002 — deepagents/LangChain como loop do agente

- **Status:** aceito (supersede a alternativa "sem framework externo" do ADR 0001)
- **Data:** 2026-10-31

## Contexto

O ADR 0001 descartou frameworks externos porque o loop agêntico era, então, tratado como parte
do objeto de estudo. A revisão do desenho experimental mudou isso: o que o Capítulo 4 compara
entre os nove braços são as **políticas de contexto** aplicadas sobre um mesmo loop, um mesmo
modelo e um mesmo dataset. O loop deixou de ser a variável e passou a ser parte do aparato de
medição — desde que seja idêntico para todos os braços, o que ele é por construção.

Escrever e manter um loop próprio (streaming, tool calls paralelas, todo middleware,
checkpointing, tracing) consumiria o tempo do semestre que pertence ao experimento.

## Decisão

Adotar `deepagents` (sobre LangChain/LangGraph) como o loop do agente:

- O grafo é criado uma vez por run em `application/agent/runner.py`
  (`create_deep_agent(model, tools, system_prompt, middleware, backend, checkpointer)`).
- As políticas de contexto da tese entram como **middleware**
  (`infrastructure/middleware/context_policy.py`): a cada chamada de modelo, o pipeline do
  domínio planeja e a decisão é aplicada por índice às mensagens do provedor.
- O guard de tool repetida e os eventos de tool entram como um segundo middleware
  (`_ToolEventMiddleware` no runner); o todo tracking usa o `TodoListMiddleware` do LangChain,
  com o board de domínio alimentado pelo `write_todos` interceptado.
- O backend de ferramentas é o do deepagents (`FilesystemBackend` com `virtual_mode=True`
  sobre a raiz do sandbox, `StateBackend` no eval), e as tools próprias continuam confinadas
  pela `Sandbox` do pacote.
- Versões fixadas como piso no `pyproject.toml`: `deepagents>=0.7.32`, `langchain>=1.4`,
  `langchain-core>=1.7`, `langchain-openai>=1.7`, `langgraph>=1.2`, `langsmith>=0.14`.

## Consequências

- **Honestidade experimental:** o loop não é mais nosso. A tese mede as políticas que o
  envolvem (o middleware), não o loop em si — e o texto do Capítulo 3 diz isso explicitamente.
  Qualquer comportamento do deepagents (ordem de tool calls, formatação de mensagens) é
  constante entre os braços, portanto não contamina a comparação.
- O modelo `stub` do grafo é um `BaseChatModel` LangChain
  (`application/agent/stub_model.py`), roteirizado e offline; testes e CI continuam sem rede.
- Ferramentas que o framework dá de graça e que teriam custo real de manutenção: tool suite de
  filesystem, `TodoListMiddleware`, checkpointing via LangGraph e tracing via LangSmith
  (opt-in, `infrastructure/observability/langsmith.py`).
- Custo: dependência de APIs que mudam entre versões (mitigado pelos pinos de versão mínimos)
  e mensagens no formato LangChain — por isso o mapeamento de domínio é sem perda e aplicado
  por índice (`infrastructure/mappers/langchain.py`).
- O domínio continua sem importar LangChain: a única ponte são os mappers e o middleware.

## Alternativas descartadas

- **Loop próprio (posição do ADR 0001).** Máximo controle, mas semanas de trabalho em
  streaming, tool calls e todo state que não são objeto de estudo da tese.
- **AutoGen/CrewAI.** Mesma categoria, com menos controle sobre o ponto exato em que o
  contexto é montado antes de cada chamada de modelo — que é onde a tese precisa intervir.
- **Loop fino próprio + LangChain só como cliente de modelo.** Meio-termo que paga os dois
  custos: mantém a responsabilidade pelo loop e ainda depende do ecossistema.

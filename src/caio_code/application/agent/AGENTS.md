# src/caio_code/application/agent/

O caso de uso central: o loop agêntico sobre um grafo deepagents, instrumentado
com os eventos de domínio.

## Módulos

| Módulo | Papel |
|---|---|
| `prompt.py` | `build_system_prompt(...)`: papel, ferramentas, disciplina de todos, regra de precisão e o bloco de contexto resumido ("Next Move"/"Relevant Files" autoritativos) |
| `session.py` | `ContextSnapshot` e `AgentRunResult`, ambos com `as_record()` serializável |
| `bridges.py` | Pontes **lazy** para os módulos escritos em paralelo (`CompactionService`, `RunLedger`, `TodoTracker`, `RepeatedToolCallGuard`, `ContextPolicyMiddleware`) + fallbacks offline determinísticos que implementam o mesmo contrato |
| `stub_model.py` | `StubChatModel(BaseChatModel)`: modelo do provedor `stub`, roteirizado, sem rede, reproduzível byte a byte |
| `runner.py` | `AgentDependencies` + `AgentRunner`: constrói o grafo (`build_agent`), streama (`run`), publica os eventos, roda o guard antes de cada tool e cancela via `interrupt()` |
| `facade.py` | `AgentSessionFacade`: adapta o runner ao protocolo `AgentFacade` da TUI |

## Invariantes

- Nada é criado implicitamente: relógio, identificadores, bus, ledger, tracker,
  guard e toolsets chegam prontos em `AgentDependencies`.
- `RunStarted` é o primeiro evento e `RunFinished` o último de todo run; deltas
  de uma mesma mensagem do assistente repetem o mesmo `message_id` (convenção
  de `presentation/tui/ports.py`).
- O guard roda **antes** da execução da tool; quando dispara, o advisory
  substitui o resultado como `ToolMessage` e chega ao modelo.
- `TodoBoardUpdated` é publicado pelo runner (não pelo tracker) exatamente uma
  vez por `write_todos`.
- Imports dos colaboradores concorrentes são sempre lazy dentro de função; na
  ausência deles, os fallbacks de `bridges.py` assumem.
- Sem `time.time()`/`datetime.now()`/`random`/`uuid4`; latência e ids vêm do
  `Clock`/`IdentifierFactory` injetados.

## O que nunca importar aqui

`presentation/**`. A aplicação publica eventos; quem os renderiza é a TUI.

## Testes

Espelhados em `tests/application/agent/`, offline (provedor stub, `FixedClock`,
`SequentialIdentifiers`, workspace em `tmp_path`).

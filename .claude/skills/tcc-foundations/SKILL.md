---
name: tcc-foundations
description: Regras fundamentais de código do agente caio-code. Use ao escrever, alterar ou revisar qualquer módulo em src/ ou tests/ — define camadas e direção de imports, determinismo, configuração sem números mágicos, contabilidade de tokens, sandbox de ferramentas, protocolo de provedores, tratamento de erros e o que um teste precisa cobrir.
---

# Fundamentos do `caio-code`

Estas são as regras que o código do agente precisa respeitar. Elas existem porque o agente é
**objeto de medição**: um harness imprevisível mede o modelo, não a técnica.

Se uma regra abaixo impedir o trabalho, ela é o assunto — abra um card e discuta a exceção. Não
a ignore em silêncio.

## 1. Camadas e direção dos imports

```
presentation ──▶ application ──▶ domain ◀── infrastructure
```

- `domain` não importa nada do pacote (exceção única: `caio_code.config`, onde vivem os
  números) e nenhum SDK de terceiros: políticas são planners puros, portas em `domain/ports/`.
- `application` contém os casos de uso e importa `domain`. O runner do agente
  (`application/agent/runner.py`) importa peças de `infrastructure` (mappers, backend,
  middleware) porque orquestra o grafo — exceção delimitada no ADR 0003.
- `infrastructure` implementa as portas e importa `domain` (+ `application` só onde um caso
  de uso é orquestrado).
- `presentation` importa `application` + `domain`; `infrastructure` só na raiz de composição
  do CLI (`cli/composition.py`) e nos relógios do driver da TUI.
- O loop agêntico é do deepagents (ADR 0002); o código do pacote intervém nele como
  middleware (`infrastructure/middleware/context_policy.py`).
- `tests/test_layering.py` verifica isso por AST: regra de dependência (com a exceção
  `application -> infrastructure` nomeada), `domain` sem pacotes de terceiros, determinismo
  (relógio e aleatoriedade só em `infrastructure/observability/clocks.py`) e os limites medidos
  no Capítulo 4 vindos de `config.py`, nunca inline. Quebrou a regra, o teste falha.

Antes de criar um módulo, responda: *qual camada ele é?* Se a resposta for "as duas", o módulo
é dois.

## 2. Determinismo

O mesmo input produz o mesmo output, na mesma máquina e em outra.

- Proibido no caminho do agente: `time.time()`, `datetime.now()`, `random` sem seed,
  `uuid4()`, iteração sobre `set` sem ordenação explícita, `dict` dependente de hash.
- Tempo e aleatoriedade entram **por injeção**: `now: Callable[[], datetime]` ou um `Random`
  recebido no construtor.
- Toda ordenação é explícita e estável (`sorted(..., key=(score, index))`), nunca "a ordem que
  veio".
- Resultados de execução registram seed, modelo e versão no artefato.

Consequência prática: se um teste falha só às vezes, o bug é seu, não do pytest.

## 3. Configuração

- Nenhum número mágico no código: budget, limites, timeouts, tamanhos e nomes de modelo vivem
  em `config.py` (dataclasses) e chegam por argumento ou variável de ambiente.
- Valide na construção (`__post_init__`), não no meio do loop. Um budget negativo deve explodir
  antes de rodar, não na terceira chamada.
- O default é seguro e offline: `provider="stub"`, sem rede.

## 4. Contabilidade de tokens

- Existe **uma** porta de contagem (`domain/ports/tokenizer.py`, `TokenCounter`) e um único
  pacote de adaptadores (`infrastructure/tokens/counter.py`). Nenhum outro módulo divide
  `len(text)` por 4.
- A fórmula padrão é a da tese: `C = Σ_m ceil(|m| / chars_per_token)`
  (`CharProxyTokenCounter`, divisor 4 de `config.CHARS_PER_TOKEN`), somada por mensagem. É o
  que o CI usa; `TiktokenCounter` é opt-in e nunca roda no CI.
- Budget é comparado com `C`, nunca com número de mensagens.
- Se a política estourar o budget, o resultado diz isso explicitamente (`overflow_tokens`,
  `notes`). Não esconda o estouro truncando depois da medição.

## 5. Ferramentas (tools)

- Toda tool recebe uma **raiz** e resolve cada caminho contra ela.
- Caminho que escapa da raiz (`..`, absoluto, symlink para fora) é **erro**, não aviso. Resolva
  com `Path.resolve()` e compare com a raiz resolvida.
- Nada de `shell=True`. Nada de interpolar string em comando.
- Saída de tool tem teto de tamanho e é truncada com marcador visível (`…`), nunca cortada em
  silêncio.
- Tool que falha devolve erro estruturado; não levanta exceção para dentro do modelo.

## 6. Provedores

- As portas vivem em `domain/ports/` (`ModelGateway`, `Summarizer`, `RelevanceScorer`,
  `DecisionModel`). O resto do código depende **das portas**, nunca do SDK.
- Os adaptadores de chat vivem em `infrastructure/llm/`: `stub` (único permitido em testes e
  CI) e `openai_compatible` (SDK `openai`). A escolha é da factory
  (`build_gateway`/`build_summarizer`/`build_scorer`).
- TypeSafe **não é provedor de chat**: o Jev é um modelo de decisão que responde perguntas
  tipadas (Noul/Choice/Score) com probabilidades (ADR 0005). Vive em
  `infrastructure/decision/` atrás da porta `DecisionModel` (`build_decision_model`/
  `build_decision_scorer`); pedir `typesafe` como provedor de chat é `ConfigurationError`.
- Nenhum `import openai`/`langchain_openai` fora de `infrastructure/llm/` e do runner (que
  constrói o `ChatOpenAI` lazy para o grafo deepagents).
- Credencial ausente → `ConfigurationError` nomeando a variável de ambiente; falha de
  transporte/auth → `ProviderError` com retry limitado (`ProviderConfig.max_retries`, delay
  fixo e injetável). A chave nunca aparece em mensagem de erro, log ou relatório.
- O loop do agente em si é do deepagents (ADR 0002); as portas cobrem as chamadas que o
  domínio faz por conta própria (compactação, scoring, probes do experimento).

## 7. Erros

- Exceção específica (`ToolError`, `ProviderError`, `ContextBudgetError`), nunca `Exception`
  genérica.
- `except:` e `except Exception: pass` são proibidos. Engolir erro é como perder a evidência do
  experimento.
- Mensagem de erro diz o que falhou, com o valor: `budget must be positive, got 0`.

## 8. Testes

- Todo módulo novo tem `tests/<mesmo caminho>/test_<módulo>.py`.
- Teste unitário não usa rede, não lê credencial (`OPENAI_API_KEY`, `TYPESAFE_API_KEY`,
  `LANGSMITH_API_KEY`), não depende de ordem de execução.
- Teste que exige modelo real leva `@pytest.mark.integration` e não roda no CI.
- Cobrir: caminho feliz, fronteira (budget exato, lista vazia, uma mensagem) e o caso de erro.
- Bug corrigido ganha teste que falha sem a correção.
- Nome do teste descreve o comportamento: `test_window_drops_oldest_when_over_budget`, não
  `test_window_2`.

## 9. Estilo

- `make lint` e `make format` (ruff). Linha de até 100 colunas.
- Type hints em toda função pública; `from __future__ import annotations` no topo.
- Docstring só quando explica *por que*, não *o que* o nome já diz.
- Identificadores, commits e código em inglês; documentos e comentários explicativos em
  português.

## 10. Documentação viva

- Mudou a estrutura de uma pasta? Atualize o `AGENTS.md` dela no **mesmo** PR.
- Decisão de arquitetura que alguém pode querer reverter? Escreva um ADR em `docs/adr/`.
- Armadilha não óbvia ("parece errado, está certo")? Registre junto da regra que ela
  aparentemente contradiz, com o motivo.

## Checklist antes de pedir revisão

- [ ] O módulo está na camada certa e os imports respeitam §1.
- [ ] Nenhum valor mágico; configuração validada na construção.
- [ ] Caminhos de tool confinados à raiz.
- [ ] Testes novos cobrem fronteira e erro.
- [ ] `make check` passa.
- [ ] `AGENTS.md` da pasta atualizado, se a estrutura mudou.
- [ ] Card do Linear com um comentário de progresso.
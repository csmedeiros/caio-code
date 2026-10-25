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
cli ──▶ harness ──▶ context
                ├──▶ providers
                ├──▶ tools
                └──▶ state
```

- `context`, `providers`, `tools` e `state` são folhas: **não** importam `harness` nem `cli`.
- `harness` compõe as folhas. `cli` só traduz argumentos e imprime resultados.
- Duas folhas não se importam entre si. Se `tools` precisa de `context`, o que está errado é a
  fronteira, não o import.
- `tests/test_layering.py` (a criar junto com o primeiro módulo) verifica isso por AST.

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

- Existe **uma** função de contagem (`context/tokens.py`). Nenhum outro módulo divide
  `len(text)` por 4.
- A fórmula é a da tese: `C = Σ_m ceil(|m| / chars_per_token)`, somada por mensagem.
- Budget é comparado com `C`, nunca com número de mensagens.
- Se a política estourar o budget, o resultado diz isso explicitamente. Não esconda o estouro
  truncando depois da medição.

## 5. Ferramentas (tools)

- Toda tool recebe uma **raiz** e resolve cada caminho contra ela.
- Caminho que escapa da raiz (`..`, absoluto, symlink para fora) é **erro**, não aviso. Resolva
  com `Path.resolve()` e compare com a raiz resolvida.
- Nada de `shell=True`. Nada de interpolar string em comando.
- Saída de tool tem teto de tamanho e é truncada com marcador visível (`…`), nunca cortada em
  silêncio.
- Tool que falha devolve erro estruturado; não levanta exceção para dentro do modelo.

## 6. Provedores

- `providers/base.py` define o protocolo (`complete(messages) -> str` ou equivalente). O resto
  do código depende **do protocolo**, nunca do SDK.
- Nenhum `import anthropic` fora de `providers/`.
- O provedor `stub` é determinístico e é o default em testes e no CI.
- Erro de rede vira uma exceção tipada do provedor, com retry limitado e explícito.

## 7. Erros

- Exceção específica (`ToolError`, `ProviderError`, `ContextBudgetError`), nunca `Exception`
  genérica.
- `except:` e `except Exception: pass` são proibidos. Engolir erro é como perder a evidência do
  experimento.
- Mensagem de erro diz o que falhou, com o valor: `budget must be positive, got 0`.

## 8. Testes

- Todo módulo novo tem `tests/<mesmo caminho>/test_<módulo>.py`.
- Teste unitário não usa rede, não lê `ANTHROPIC_API_KEY`, não depende de ordem de execução.
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
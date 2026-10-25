---
name: tcc-bug-investigation
description: Protocolo de investigação de bugs no agente caio-code. Use quando um teste falha, o agente se comporta de forma estranha, um resultado muda entre execuções ou algo que funcionava parou de funcionar. Exige reprodução, teste que falha antes da correção e causa raiz identificada — não aceita remendo por tentativa.
---

# Investigação de bugs

O objetivo não é fazer o teste passar. É explicar por que ele falhava. Um patch que faz o
sintoma desaparecer sem causa raiz identificada é um bug adiado, e num experimento ele vira
resultado inválido.

## Quando usar

- teste vermelho, em qualquer condição;
- resultado que muda entre duas execuções com o mesmo input;
- agente que para no meio, entra em loop, estoura o budget ou escolhe a tool errada;
- "funcionava ontem".

Não use para: funcionalidade nova, refatoração sem falha, revisão de PR (isso é
`tcc-pr-review`).

## Protocolo

### 0. Congele o sintoma

Registre o comando exato, a saída e o ambiente antes de tocar em qualquer coisa.

```bash
python -m pytest tests/<caminho> -x -q 2>&1 | tee .reports/bugs/<data>-<slug>.log
```

Se não for reproduzível com um comando, o primeiro bug é esse.

### 1. Reduza

Encontre a menor entrada que ainda falha. Remova partes do cenário até que remover mais faça o
bug desaparecer. O caso mínimo é o que entra no teste.

Não pule esta etapa: um caso grande esconde três bugs e você corrige o errado.

### 2. Escreva o teste que falha

Antes da correção, um teste que reproduz o comportamento errado e falha pelo motivo certo.

```python
def test_window_keeps_pinned_message_over_budget():
    ...
```

Se o teste passa antes da correção, ele não reproduz o bug.

### 3. Localize

- `git log -S '<símbolo>'` e `git bisect` para achar quando entrou;
- leia o caminho completo do dado: entrada → transformação → saída;
- imprima os valores intermediários (temporariamente, e remova depois);
- verifique as fronteiras primeiro: lista vazia, budget exato, uma mensagem, caminho com `..`.

### 4. Formule uma hipótese única

Uma frase falsificável: *"a janela inclui a mensagem fixada duas vezes porque o custo dela é
somado no cálculo e depois ela entra de novo na varredura"*.

Se você tem duas hipóteses, teste uma por vez. Corrigir duas coisas juntas impede saber qual
funcionou.

### 5. Confirme antes de corrigir

Faça um experimento que **falharia se a hipótese estivesse errada**. Uma asserção, um print, um
teste menor. Hipótese confirmada por leitura de código não é confirmação.

### 6. Corrija a causa

- no ponto onde a invariante é violada, não onde o sintoma aparece;
- mínima: sem refatoração de carona, sem renomear, sem "aproveitar";
- se a causa é uma regra de `tcc-foundations`, corrija a regra no código e considere atualizar a
  skill.

### 7. Prove

```bash
python -m pytest tests/<caminho> -q     # o teste novo passa
make test-changed                        # a pasta inteira passa
make test                                # nada regrediu
```

Os três. O terceiro é o que pega o efeito colateral em outro módulo.

### 8. Registre

Arquivo `.reports/bugs/<data>-<slug>.md`:

```markdown
# <sintoma em uma linha>

- **Comando que reproduz**:
- **Caso mínimo**:
- **Causa raiz**: (uma frase)
- **Hipótese testada e como foi confirmada**:
- **Correção**: arquivo:linha
- **Teste que a cobre**:
- **O que quase enganou**:
```

E **um** comentário no card do Linear: causa, correção, teste. Não edite um comentário anterior
para acrescentar.

## Anti-padrões

| Anti-padrão | Por que é ruim |
|---|---|
| Alterar o teste para passar | O teste era a especificação; você acabou de apagá-la |
| `pytest -k` para sempre, ignorando o resto | Esconde a regressão que você criou |
| Retry em teste instável | Instabilidade é sinal de determinismo quebrado (§2 de fundamentos) |
| Silenciar log ou `except: pass` | Destrói a evidência que você vai precisar |
| Corrigir dois lugares de uma vez | Não se sabe qual funcionou; se voltar, não se sabe por quê |
| "Era o cache" sem provar | Cache é hipótese, não conclusão |

## Regra de parada

Se depois de duas hipóteses refutadas você não tem causa, **pare e reporte**. Abra um card com
o caso mínimo, os experimentos feitos e o que já foi descartado. Investigação sem direção custa
mais que o bug.
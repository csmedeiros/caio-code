# src/caio_code/harness/

O loop agêntico. Recebe uma tarefa, conversa com o provedor, executa ferramentas e devolve o
resultado com a contabilidade de contexto de cada passo.

## Invariantes

- **Não implementa política de contexto.** Recebe uma função de `context/` e a aplica; trocar de
  janela para compactação não muda uma linha do loop.
- **Não conhece SDK.** Fala com `providers/base.py`, nunca com `anthropic`.
- **Não sabe o que é um caminho.** Toda manipulação de arquivo passa por `tools/`.
- Determinismo: nenhum relógio, nenhum aleatório. O que varia entra por injeção.
- Todo passo registra: índice, tokens estimados do contexto enviado, ação escolhida, resultado.

## Contrato do loop

```
messages = [system, task]
for step in range(max_steps):
    view = policy(messages, budget)      # context/
    reply = provider.complete(view)      # providers/
    if reply is final: return
    result = tool(reply.action)          # tools/
    messages.append(result)
```

O relatório final inclui `steps`, `tokens_sent_peak`, `final_answer` e o motivo da parada.

## O que não entra aqui

Seleção de mensagens, sumarização, contagem de token avulsa, chamada de shell direta.
# ADR 0001 — Camadas e direção de dependência

- **Status:** aceito
- **Data:** 2026-10-25

## Contexto

O agente é objeto de medição do TCC. Se o loop, a política de contexto e o cliente do modelo
estiverem no mesmo módulo, trocar uma política muda o comportamento de tudo, e o experimento
deixa de isolar a variável que diz medir. O Capítulo 17 compara políticas de contexto entre
si; essa comparação só tem valor se a única diferença entre as execuções for a política.

## Decisão

Quatro folhas e uma camada de composição:

```
cli → harness → {context, providers, tools, state}
```

- `context`: funções puras `(messages, budget) -> messages`. Sem I/O, sem modelo.
- `providers`: protocolo + adaptadores. Nenhum SDK vaza para fora.
- `tools`: efeitos no sistema de arquivos, confinados a uma raiz.
- `state`: persistência serializável.
- `harness`: o loop; recebe a política como função.
- `cli`: tradução de argumentos e saída.

A direção é verificada por teste (`tests/test_layering.py`, a criar com o primeiro módulo da
camada de composição): import de folha para `harness`/`cli` falha o CI.

## Consequências

- Trocar política é trocar uma função; o loop não muda.
- O provedor `stub` permite testar o harness inteiro sem rede.
- Custa indireção: uma chamada de ferramenta atravessa `harness → tools`, não é um `open()`
  direto. Aceito, porque é o que torna o sandbox auditável.
- Se uma folha precisar de outra, a resposta é repensar a fronteira, não criar o import.

## Alternativas descartadas

- **Um módulo único (`agent.py`).** Mais rápido de escrever, impossível de medir por partes.
- **Framework externo (LangChain e similares).** Esconde o loop, que é justamente o objeto de
  estudo, e adiciona dependência que muda entre versões.
- **Injeção por plugin dinâmico.** Complexidade sem ganho: três políticas não justificam um
  sistema de plugins.
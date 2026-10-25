# src/caio_code/

O pacote do agente. A raiz de composição: `config.py`, `cli.py` e o loop em `harness/`.

## Mapa de módulos

| Módulo | Camada | Papel |
|---|---|---|
| `config.py` | raiz | dataclasses de configuração, validação, leitura de ambiente |
| `cli.py` | borda | argparse, formatação de saída, códigos de saída |
| `harness/` | composição | loop agêntico; orquestra tools, provedor e políticas |
| `context/` | folha | tokens, janela, seleção, compactação |
| `providers/` | folha | protocolo e implementações de modelo |
| `tools/` | folha | ferramentas de SWE, confinadas a uma raiz |
| `state/` | folha | persistência entre turnos |

## Invariantes

- `config.py` não importa nenhum outro módulo do pacote.
- `cli.py` é o único que lê `sys.argv`, imprime em stdout e chama `sys.exit`.
- `harness/` não contém política de contexto: recebe uma função de `context/`.

## O que não entra aqui

Código de experimento, notebooks de análise e dados de avaliação. Isso é do repositório de
pesquisa, não do produto.
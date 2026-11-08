# src/caio_code/presentation/

Camada de apresentação. Duas bordas do produto:

| Pacote | Papel |
|---|---|
| `cli/` | `python -m caio_code` / console script `caio-code`: argparse, composição, stdout, códigos de saída |
| `tui/` | App Textual, widgets, driver headless e o protocolo `AgentFacade` (outro agente é dono; somente leitura aqui) |

## Invariantes

- `cli/` é o ÚNICO lugar do pacote que lê `sys.argv`, imprime em stdout e chama
  `sys.exit`.
- Presentation importa application + domain; infrastructure só aparece na raiz
  de composição do CLI (`cli/composition.py`).
- Nenhum segredo chega à saída: `doctor` reporta nomes de variáveis de
  ambiente, nunca valores.

# tests/infrastructure/

Espelho de `src/caio_code/infrastructure/`: um subdiretório por subpacote
(`tools/`, `persistence/`, `llm/`, `decision/`, `pricing/`, `mappers/`, `observability/`), com
`test_<módulo>.py` para cada módulo.

## Invariantes

- Offline e determinístico: sem rede, sem chave de API, sem relógio real
  (timeouts usam `timeout_seconds` pequeno e `sys.executable`).
- Raiz de sandbox sempre em `tmp_path`; nada toca o repositório real.
- Nome de teste descreve comportamento
  (`test_dotdot_escape_raises_sandbox_escape_error`).

## O que não entra aqui

Teste de integração com modelo real, snapshot gigante, fixture binária pesada.

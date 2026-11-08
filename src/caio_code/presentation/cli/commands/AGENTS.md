# src/caio_code/presentation/cli/commands/

Um módulo por subcomando do CLI. Cada comando é uma função pura
`(args: Namespace) -> int`: constrói settings via `composition.load_cli_settings`,
executa e devolve o código de saída. Nenhum comando formata números por conta
própria — usa `presentation.cli.formatting`.

| Módulo | Verbo |
|---|---|
| `run.py` | `caio-code run --task ...` |
| `tui.py` | `caio-code tui [--demo]` |
| `compact.py` | `caio-code compact --transcript ...` |
| `evaluate.py` | `caio-code evaluate` (delega ao experiment runner, import lazy); `--variants full,spill` rota para o chat-replay (`application/evaluation/replay.py`) |
| `classify.py` | `caio-code classify --state ... --noul/--choice/--score` (menor cheque vivo do modelo de decisão; offline com `--provider stub`) |
| `doctor.py` | `caio-code doctor [--json]` (nomes de env, nunca valores; inclui a seção do modelo de decisão) |

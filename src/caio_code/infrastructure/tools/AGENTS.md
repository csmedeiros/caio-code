# infrastructure/tools/

Adaptadores de ferramentas: as SWE tools confinadas a uma raiz e a seleção de
backend do deepagents. Implementa a seção 5 ("Ferramentas") da skill
`tcc-foundations`.

## Módulos

| Módulo | Papel |
|---|---|
| `sandbox.py` | `Sandbox`: resolve todo caminho contra a raiz; `..`, caminho absoluto fora da raiz e symlink para fora são `SandboxEscapeError` |
| `filesystem.py` | `FilesystemToolset`: read/write/edit/list/glob; toda saída passa por `truncate_text` |
| `shell.py` | `ShellToolset` (argv via `subprocess.run`, nunca `shell=True`) e `shell_backend(settings)` |
| `search.py` | `SearchToolset`: grep e find só com stdlib (`re`, `pathlib`, `fnmatch`), sem ripgrep |
| `deepagents_backend.py` | `build_backend(settings)`: `FilesystemBackend` quando a raiz existe, senão `StateBackend` |
| `_guard.py` | privado: converte `ToolError` em texto estruturado nos wrappers LangChain |

## Por que `build_backend` escolhe entre dois backends

O harness de avaliação roda sobre um workspace temporário (às vezes nem existe
no disco no momento da composição); a TUI roda sobre o repositório real do
usuário. Raiz que é diretório de verdade ganha `FilesystemBackend(root_dir=...,
virtual_mode=True)` — caminhos virtuais sob a raiz, traversal é erro no próprio
deepagents. Raiz inexistente cai no `StateBackend` efêmero, para o eval nunca
tocar no host.

## Invariantes

- Nenhum caminho chega a disco sem passar por `Sandbox.resolve`.
- Nada de `shell=True`, nada de comando interpolado em string: só listas argv.
- Toda saída de tool passa por `truncate_text` com os tetos de
  `ToolOutputConfig`; truncamento tem marcador visível, nunca é silencioso.
- A API Python levanta erros tipados (`ToolError`); os wrappers
  `as_langchain_tools()` devolvem o erro como texto — exceção nunca entra no modelo.
- Sem `time.time()`, `datetime.now()`, `random` ou `uuid4`: timeouts vêm de config.
- Diretivas de docstring dos schemas pydantic são a descrição que o modelo vê.

## O que nunca importar aqui

`harness`, `cli`, `providers`, SDK de modelo. Esta camada é folha: importa só
`config`, `domain` e bibliotecas de tool (langchain-core, deepagents).

## Testes

Espelhados em `tests/infrastructure/tools/`, offline e determinísticos
(`sys.executable` para o shell, `tmp_path` para a raiz).

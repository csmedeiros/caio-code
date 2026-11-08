# tests/state/ — resíduo do layout antigo

Diretório remanescente da estrutura `cli → harness → folhas` (ADR 0001, superado por
ADR 0002/0003). Contém apenas `__init__.py`: **nenhum teste vive aqui**.

Não adicione testes a este diretório. O espelho correto é
`tests/{domain,application,infrastructure,presentation}/`. A remoção do diretório é pendência
registrada no `AGENTS.md` raiz (§11).

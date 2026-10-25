# src/caio_code/tools/

Ferramentas que o agente pode chamar. Toda ferramenta é confinada a uma raiz.

## Invariantes

- **Sandbox obrigatório.** Cada caminho é resolvido com `Path.resolve()` e comparado com a raiz
  resolvida. `..`, caminho absoluto e symlink para fora são **erro**, não aviso.
- Nada de `shell=True` e nada de interpolar string em comando.
- Saída truncada em `max_tool_output_chars`, com marcador visível (`…`).
- Falha devolve resultado estruturado (`ok: false`, mensagem), não exceção para dentro do
  modelo.
- Toda ferramenta declara nome, descrição e schema de argumentos de forma inspecionável.

## Ferramentas previstas

| Arquivo | Papel |
|---|---|
| `base.py` | interface, resultado, validação de caminho |
| `filesystem.py` | leitura, escrita e listagem sob a raiz |
| `shell.py` | execução de comando com timeout, sem shell |

## Testes

Obrigatórios para a fronteira de segurança: `../`, absoluto, symlink, raiz inexistente.
Um teste que prova que o escape é bloqueado vale mais que dez do caminho feliz.
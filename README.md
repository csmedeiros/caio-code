# caio-code

Agente de codificação para tarefas longas em repositórios grandes, desenvolvido como
protótipo da Parte III do TCC *Context Is All You Need*.

O agente é avaliado no Capítulo 17 da monografia; este repositório é o artefato que o Capítulo
16 descreve. Ele é um repositório git independente, mantido dentro de `~/tcc/` apenas por
conveniência — o repositório da monografia o ignora.

## Começo rápido

```bash
make setup          # cria .venv, instala dependências, instala os git hooks
make test           # suíte de testes unitários
make smoke          # execução ponta a ponta, sem rede e sem chave de API
make help           # todos os alvos
```

## Uso

```bash
python -m caio_code run --task "read README.md and summarize it" --root .
```

Por padrão o agente usa o provedor `stub`, determinístico e offline. Para usar um modelo real,
defina `ANTHROPIC_API_KEY` e `CAIO_CODE_MODEL` e passe `--provider anthropic`.

## Documentação

| Arquivo | Conteúdo |
|---|---|
| `CLAUDE.md` | regras do repositório, Linear, versionamento, CI e hooks |
| `docs/linear-workflow.md` | cards, subtarefas e stack de PRs |
| `.claude/skills/tcc/SKILL.md` | roteador `/tcc` para as demais skills |
| `docs/adr/` | decisões de arquitetura |

## Licença

Uso acadêmico. Sem licença de distribuição.
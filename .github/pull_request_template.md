## Card

Linear: <!-- CM-nn -->

## O que mudou

<!-- Uma lista curta. O diff deve cobrir só isto. -->

## Como foi verificado

<!-- Comandos exatos e o resultado. Não escreva "testes passam" sem a saída. -->

```bash
make test-changed
```

## Checklist

- [ ] O escopo do diff corresponde ao card (5 a 20 arquivos)
- [ ] Teste novo ou atualizado para a pasta alterada
- [ ] `AGENTS.md` da pasta atualizado, se a estrutura mudou
- [ ] `CLAUDE.md` continua sendo symlink para `AGENTS.md`
- [ ] Nenhum segredo, `.env` ou artefato de build no diff
- [ ] Comentário de progresso registrado no card do Linear
- [ ] Base do PR correta (`main` ou a branch de baixo, se empilhado)
- [ ] Branch atualizada com a base (rebase, não merge)

## Riscos e o que ficou de fora

<!-- O que este PR deliberadamente não faz. -->
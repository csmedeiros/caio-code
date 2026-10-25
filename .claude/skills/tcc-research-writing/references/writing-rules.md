# Regras de redação do TCC

O texto da tese é em **inglês**. Notas de planejamento e conversa podem ser em português. O
`Resumo` em português no `main.tex` é o resumo secundário e é mantido.

## Contrato do capítulo

Cada `capitulos/*.tex` começa com:

```latex
% ----------------------------------------------------------
% Chapter title
% ----------------------------------------------------------
\chapter{Title}
\label{cap:slug}
% ----------------------------------------------------------
```

Depois `\section{...}` e `\label{sec:...}`. Referência cruzada com `\ref{cap:...}` /
`\ref{sec:...}`, nunca número fixo. O `main.tex` precisa ter `\input{capitulos/<nome>}`.

## Formas de citação

- `\cite{key}` para parênteses.
- `\citeonline{key}` quando o autor é sujeito: `\citeonline{liu2024lost} show that...`.
- Uma entrada por chave em `referencias.bib`; toda chave em `planejamento/bibmap.json`.
- Nunca citar chave antes de verificada. Nunca adicionar entrada de bib à mão: o verifier é
  dono do `referencias.bib`.

## Alegações

Cada frase factual é uma de três:

1. **Sustentada por fonte** — cita chave verificada e fica dentro de `claim_adjusted` /
   `claim_evidence`, respeitando `flags`.
2. **Formalização deste trabalho** — dita explicitamente ("in this work", "the author's
   formalization"), permitida para contexto/memória/estado, janela deslizante, seleção de
   mensagens e guardrails de histórico.
3. **Inferência deste trabalho** — marcada e ligada a um experimento (E1–E6).

Nunca escreva frase factual que não pertença a nenhuma das três.

## Ordem de redação

1. Ler o log de pesquisa do capítulo e todo `claim_adjusted` das chaves.
2. Escrever o esqueleto de seções com uma frase-tópico por seção.
3. Preencher parágrafos a partir da evidência, não da memória. Parágrafo que precisa de fato
   sem evidência volta para verificação.
4. Adicionar referências cruzadas e a transição para o próximo capítulo.
5. Só então `node scripts/state.mjs transition DRAFTED ...`.

## Passagem de refino (obrigatória antes de REFINED)

Faça todas, nesta ordem:

- **Auditoria de alegação.** Cada citação ainda corresponde à evidência; cada inferência está
  rotulada; nenhuma frase excede as `flags` da fonte.
- **Estrutura.** ≥ 2 seções; uma ideia por parágrafo; a primeira frase enuncia a alegação do
  parágrafo; sem subseção órfã.
- **Compressão.** Remover enchimento ("It is important to note", "In today's world"),
  definições duplicadas e frases que repetem a anterior. Meta de 10–20% mais curto sem perder
  alegação.
- **Precisão.** Trocar quantificador vago pelo número e condição da fonte. Apagar "very",
  "significantly" a menos que a fonte tenha medido.
- **LaTeX.** Sem `TODO`/`FIXME`; sem `\cite{}` vazio; acentos e aspas compilam; tabela com
  `booktabs`; código com `lstlisting`.
- **Idioma.** Inglês apenas; terminologia consistente (context, memory, state, harness, long
  horizon); sigla expandida no primeiro uso.
- **Build.** `latexmk -pdf -bibtex -interaction=nonstopmode main.tex` sem citação ou referência
  indefinida.

## Log de revisão (escrito pelo reviewer, verificado pelos guardas)

`evidencias/revisao/cap-NN.md`:

```markdown
# Review — Chapter NN

- [x] Every citation maps to a verified evidence record
- [x] Every source-backed sentence respects claim_adjusted and flags
- [x] Inferences and formalizations are explicitly labelled
- [x] Structure: sections, paragraph claims, cross-references
- [x] Compression pass applied
- [x] LaTeX builds without undefined citations/references

Flags considered: yes
Evidence audit: pass
Verdict: approve
```

Qualquer caixa desmarcada ou linha ausente reprova o guarda de REFINED/APPROVED.

## Simplificar sem mentir

Simplifique a frase, nunca a evidência. Se a compressão remover uma condição de que a fonte
dependia, restaure-a. Uma frase falsa mais curta é pior que uma verdadeira mais longa.
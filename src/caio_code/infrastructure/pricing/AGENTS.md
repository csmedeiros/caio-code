# infrastructure/pricing/

Ponte entre o uso reportado pelo provedor e a contabilidade do domínio.

## O que vive aqui

`sheet.py`: `pricing_for(settings) -> PriceSheet`, `cost_of(usage, model, sheet=None) -> Cost`
e `accounting_for(usages, model, *, proxy_input_tokens=0, sheet=None) -> RunAccounting`.

## Invariantes

- **Nenhum número novo entra aqui.** Preços vêm exclusivamente de `config.PRICE_SHEET` e
  `config.FALLBACK_PRICE`; a aritmética é a de `domain/usage/accounting.py`. Este módulo só
  monta os objetos.
- Modelo desconhecido degrada para o preço de fallback (estimativa conservadora), nunca
  para crash nem para custo zero.
- `Cost` permanece `Decimal`: nada de float na contabilidade.

## O que nunca entra aqui

- Leitura de ambiente, preço hard-coded, chamada de rede ou dependência de provedor.

## Como é testado

`tests/infrastructure/pricing/`, offline e puramente aritmético: modelo conhecido, modelo
desconhecido (fallback), uso zerado, uso com tokens em cache e agregação de múltiplas
chamadas em `RunAccounting`.

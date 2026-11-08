# tests/infrastructure/pricing/

Testes de `infrastructure/pricing/sheet.py` (`test_sheet.py`): `pricing_for` monta a
`PriceSheet` de `config.PRICE_SHEET`, `cost_of` para modelo conhecido/desconhecido (fallback,
nunca crash nem zero), `accounting_for` agregando `RunAccounting` com `proxy_input_tokens`.

Invariantes: aritmética em `Decimal` com valores calculáveis à mão; nenhum preço é definido
no teste — números vêm de `config.py`.

# tests/domain/conversation/

Testes de `src/caio_code/domain/conversation/`: `test_rendering_and_summary.py` cobre o
rendering (`render_message`/`render_indexed`, cap de tool result), o split head/recent e o
resumo ancorado (template com as cinco seções, `parse_summary` tolerante — ordem preservada,
headings desconhecidos mantidos —, `missing_sections`/`is_well_formed`, prompt de merge com
resumo prévio).

Invariantes: dados puros, sem I/O; textos de fixture curtos o suficiente para o custo sob o
char proxy ser calculável à mão.

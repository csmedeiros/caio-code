# Truncation vs retention replay-run-0001

Does spilling oversized tool outputs to files change what the agent
retains after its context is shaped? Same histories, same probes;
`spill` replaces tool outputs above the byte cap with a pointer the
agent can read back during probing.

## baseline_full_history

| Variant | Retention | Prompt tok | Aux tok | Tool calls | Spill reads | Cost/trial | Errors |
|---|---|---|---|---|---|---|---|
| full | 0.00 | 39,525 | 768 | 0.0 | 0.0 | $0.0632 | 0% |
| spill | 0.00 | 12,973 | 768 | 0.0 | 0.0 | $0.0208 | 0% |

- Retention delta (spill - full): +0.00
- Prompt tokens delta: -26,553
- Cost/trial delta: $-0.0425
- Spill reads per trial: 0.0

## sliding_window

| Variant | Retention | Prompt tok | Aux tok | Tool calls | Spill reads | Cost/trial | Errors |
|---|---|---|---|---|---|---|---|
| full | 0.00 | 4,459 | 768 | 0.0 | 0.0 | $0.0071 | 0% |
| spill | 0.00 | 6,897 | 768 | 0.0 | 0.0 | $0.0110 | 0% |

- Retention delta (spill - full): +0.00
- Prompt tokens delta: +2,439
- Cost/trial delta: $+0.0039
- Spill reads per trial: 0.0

## message_selection

| Variant | Retention | Prompt tok | Aux tok | Tool calls | Spill reads | Cost/trial | Errors |
|---|---|---|---|---|---|---|---|
| full | 0.00 | 6,749 | 768 | 0.0 | 0.0 | $0.0108 | 0% |
| spill | 0.00 | 6,852 | 768 | 0.0 | 0.0 | $0.0110 | 0% |

- Retention delta (spill - full): +0.00
- Prompt tokens delta: +103
- Cost/trial delta: $+0.0002
- Spill reads per trial: 0.0

## message_selection_decision

| Variant | Retention | Prompt tok | Aux tok | Tool calls | Spill reads | Cost/trial | Errors |
|---|---|---|---|---|---|---|---|
| full | 0.00 | 7,486 | 21,597 | 0.0 | 0.0 | $0.0537 | 0% |
| spill | 0.00 | 7,554 | 20,951 | 0.0 | 0.0 | $0.0528 | 0% |

- Retention delta (spill - full): +0.00
- Prompt tokens delta: +68
- Cost/trial delta: $-0.0009
- Spill reads per trial: 0.0

## anchored_compaction

| Variant | Retention | Prompt tok | Aux tok | Tool calls | Spill reads | Cost/trial | Errors |
|---|---|---|---|---|---|---|---|
| full | 0.00 | 6,779 | 6,564 | 0.0 | 0.0 | $0.0143 | 0% |
| spill | 0.00 | 6,393 | 4,863 | 0.0 | 0.0 | $0.0127 | 0% |

- Retention delta (spill - full): +0.00
- Prompt tokens delta: -386
- Cost/trial delta: $-0.0016
- Spill reads per trial: 0.0


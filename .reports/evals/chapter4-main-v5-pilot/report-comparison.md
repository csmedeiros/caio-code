# Truncation vs retention chapter4-main-v5-pilot

Does spilling oversized tool outputs to files change what the agent
retains after its context is shaped? Same histories, same probes;
`spill` replaces tool outputs above the byte cap with a pointer the
agent can read back during probing.

## baseline_full_history

| Variant | Retention | Prompt tok | Aux tok | Tool calls | Spill reads | Cost/trial | Errors |
|---|---|---|---|---|---|---|---|
| full | 1.00 | 219,421 | 11,427 | 0.0 | 0.0 | $0.3613 | 0% |
| spill | 1.00 | 69,781 | 11,547 | 0.0 | 0.0 | $0.1320 | 0% |

- Retention delta (spill - full): +0.00
- Prompt tokens delta: -149,640
- Cost/trial delta: $-0.2292
- Spill reads per trial: 0.0

## sliding_window

| Variant | Retention | Prompt tok | Aux tok | Tool calls | Spill reads | Cost/trial | Errors |
|---|---|---|---|---|---|---|---|
| full | 0.42 | 48,704 | 15,147 | 0.0 | 0.0 | $0.1047 | 0% |
| spill | 0.58 | 57,226 | 12,687 | 0.0 | 0.0 | $0.1127 | 0% |

- Retention delta (spill - full): +0.17
- Prompt tokens delta: +8,522
- Cost/trial delta: $+0.0080
- Spill reads per trial: 0.0

## message_selection

| Variant | Retention | Prompt tok | Aux tok | Tool calls | Spill reads | Cost/trial | Errors |
|---|---|---|---|---|---|---|---|
| full | 1.00 | 56,096 | 9,711 | 0.0 | 0.0 | $0.1008 | 0% |
| spill | 1.00 | 56,438 | 8,055 | 0.0 | 0.0 | $0.0992 | 0% |

- Retention delta (spill - full): +0.00
- Prompt tokens delta: +342
- Cost/trial delta: $-0.0016
- Spill reads per trial: 0.0

## message_selection_decision

| Variant | Retention | Prompt tok | Aux tok | Tool calls | Spill reads | Cost/trial | Errors |
|---|---|---|---|---|---|---|---|
| full | 1.00 | 52,390 | 127,887 | 0.0 | 0.0 | $0.2197 | 0% |
| spill | 1.00 | 51,002 | 123,435 | 0.0 | 0.0 | $0.1732 | 0% |

- Retention delta (spill - full): +0.00
- Prompt tokens delta: -1,388
- Cost/trial delta: $-0.0465
- Spill reads per trial: 0.0

## anchored_compaction

| Variant | Retention | Prompt tok | Aux tok | Tool calls | Spill reads | Cost/trial | Errors |
|---|---|---|---|---|---|---|---|
| full | 0.83 | 51,233 | 28,209 | 0.0 | 0.0 | $0.1099 | 0% |
| spill | 0.00 | 0 | 0 | 0.0 | 0.0 | $0.0000 | 100% |

- Retention delta (spill - full): -0.83
- Prompt tokens delta: -51,233
- Cost/trial delta: $-0.1099
- Spill reads per trial: 0.0


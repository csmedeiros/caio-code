# Truncation vs retention chapter4-main-v5

Does spilling oversized tool outputs to files change what the agent
retains after its context is shaped? Same histories, same probes;
`spill` replaces tool outputs above the byte cap with a pointer the
agent can read back during probing.

## baseline_full_history

| Variant | Retention | Prompt tok | Aux tok | Tool calls | Spill reads | Cost/trial | Errors |
|---|---|---|---|---|---|---|---|
| full | 1.00 | 211,989 | 8,277 | 0.0 | 0.0 | $0.3498 | 0% |
| spill | 0.93 | 72,462 | 8,820 | 0.0 | 0.0 | $0.1296 | 0% |

- Retention delta (spill - full): -0.07
- Prompt tokens delta: -139,527
- Cost/trial delta: $-0.2201
- Spill reads per trial: 0.0

## sliding_window

| Variant | Retention | Prompt tok | Aux tok | Tool calls | Spill reads | Cost/trial | Errors |
|---|---|---|---|---|---|---|---|
| full | 0.62 | 46,357 | 17,292 | 0.0 | 0.0 | $0.1064 | 0% |
| spill | 0.70 | 55,455 | 13,980 | 0.0 | 0.0 | $0.1106 | 0% |

- Retention delta (spill - full): +0.08
- Prompt tokens delta: +9,099
- Cost/trial delta: $+0.0042
- Spill reads per trial: 0.0

## message_selection

| Variant | Retention | Prompt tok | Aux tok | Tool calls | Spill reads | Cost/trial | Errors |
|---|---|---|---|---|---|---|---|
| full | 0.97 | 52,671 | 10,375 | 0.0 | 0.0 | $0.0945 | 0% |
| spill | 0.90 | 86,614 | 10,581 | 0.4 | 0.4 | $0.1406 | 0% |

- Retention delta (spill - full): -0.07
- Prompt tokens delta: +33,942
- Cost/trial delta: $+0.0461
- Spill reads per trial: 0.4

## message_selection_decision

| Variant | Retention | Prompt tok | Aux tok | Tool calls | Spill reads | Cost/trial | Errors |
|---|---|---|---|---|---|---|---|
| full | 0.70 | 57,488 | 71,623 | 0.0 | 0.0 | $0.1521 | 0% |
| spill | 0.88 | 53,584 | 105,950 | 0.0 | 0.0 | $0.1587 | 0% |

- Retention delta (spill - full): +0.18
- Prompt tokens delta: -3,904
- Cost/trial delta: $+0.0066
- Spill reads per trial: 0.0

## anchored_compaction

| Variant | Retention | Prompt tok | Aux tok | Tool calls | Spill reads | Cost/trial | Errors |
|---|---|---|---|---|---|---|---|
| full | 0.75 | 49,605 | 31,243 | 0.0 | 0.0 | $0.1230 | 0% |
| spill | 0.70 | 52,992 | 24,459 | 0.0 | 0.0 | $0.1196 | 0% |

- Retention delta (spill - full): -0.05
- Prompt tokens delta: +3,388
- Cost/trial delta: $-0.0033
- Spill reads per trial: 0.0


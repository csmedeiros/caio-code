# Chat-replay evaluation chapter4-main-v5

- Dataset: `long_histories_128k` (5 cases)
- Model: `qwen3.8-max`
- Declared window: 40,000 tokens
- Repetitions per case: 1 (pass^k uses all of them)
- Seed: 20261031
- Started: 2026-11-08T17:18:01.742337+00:00 - finished: 2026-11-08T17:45:11.239560+00:00
- Total cost: $7.4246
- Trials: 50
- Cache hit is **not reported**: a replayed history cannot measure a
  provider prompt cache honestly (see threats to validity).

## Arms x variants

| Arm | Variant | Retention | pass^k | All probes | Prompt tok | Aux tok | Tool calls | Spill reads | Tool misses | Cost/trial | Total cost | Overflow | Errors | Latency ms |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| baseline_full_history | full | 1.00 | 1.00 | 1.00 | 211,989 | 8,277 | 0.0 | 0.0 | 0.0 | $0.3498 | $1.7488 | 100% | 0% | 52,418 |
| baseline_full_history | spill | 0.93 | 0.60 | 0.60 | 72,462 | 8,820 | 0.0 | 0.0 | 0.0 | $0.1296 | $0.6481 | 100% | 0% | 60,845 |
| sliding_window | full | 0.62 | 0.00 | 0.00 | 46,357 | 17,292 | 0.0 | 0.0 | 0.0 | $0.1064 | $0.5320 | 0% | 0% | 122,711 |
| sliding_window | spill | 0.70 | 0.20 | 0.20 | 55,455 | 13,980 | 0.0 | 0.0 | 0.0 | $0.1106 | $0.5530 | 0% | 0% | 93,629 |
| message_selection | full | 0.97 | 0.60 | 0.60 | 52,671 | 10,375 | 0.0 | 0.0 | 0.0 | $0.0945 | $0.4726 | 0% | 0% | 58,476 |
| message_selection | spill | 0.90 | 0.60 | 0.60 | 86,614 | 10,581 | 0.4 | 0.4 | 0.0 | $0.1406 | $0.7029 | 0% | 0% | 74,219 |
| message_selection_decision | full | 0.70 | 0.20 | 0.20 | 57,488 | 71,623 | 0.0 | 0.0 | 0.0 | $0.1521 | $0.7605 | 0% | 0% | 89,075 |
| message_selection_decision | spill | 0.88 | 0.20 | 0.20 | 53,584 | 105,950 | 0.0 | 0.0 | 0.0 | $0.1587 | $0.7937 | 0% | 0% | 64,408 |
| anchored_compaction | full | 0.75 | 0.40 | 0.40 | 49,605 | 31,243 | 0.0 | 0.0 | 0.0 | $0.1230 | $0.6149 | 0% | 0% | 431,720 |
| anchored_compaction | spill | 0.70 | 0.20 | 0.20 | 52,992 | 24,459 | 0.0 | 0.0 | 0.0 | $0.1196 | $0.5981 | 0% | 0% | 210,760 |

## Retention by fact position

| Arm | Variant | Early | Middle | Late |
|---|---|---|---|---|
| baseline_full_history | full | 1.00 | 1.00 | 1.00 |
| baseline_full_history | spill | 0.90 | 0.95 | 0.95 |
| sliding_window | full | 0.00 | 0.85 | 1.00 |
| sliding_window | spill | 0.30 | 0.80 | 1.00 |
| message_selection | full | 0.90 | 1.00 | 1.00 |
| message_selection | spill | 0.85 | 0.95 | 0.90 |
| message_selection_decision | full | 0.75 | 0.65 | 0.70 |
| message_selection_decision | spill | 0.90 | 0.95 | 0.80 |
| anchored_compaction | full | 0.45 | 0.80 | 1.00 |
| anchored_compaction | spill | 0.55 | 0.70 | 0.85 |

## Errors

- No trial reported an error.

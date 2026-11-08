# Chat-replay evaluation replay-run-0001

- Dataset: `long_histories` (5 cases)
- Model: `qwen3.8-max`
- Declared window: 8,000 tokens
- Repetitions per case: 1 (pass^k uses all of them)
- Seed: 20261031
- Started: 2026-11-07T22:06:36.556031+00:00 - finished: 2026-11-07T22:06:36.733418+00:00
- Total cost: $1.2867
- Trials: 50
- Cache hit is **not reported**: a replayed history cannot measure a
  provider prompt cache honestly (see threats to validity).

## Arms x variants

| Arm | Variant | Retention | pass^k | All probes | Prompt tok | Aux tok | Tool calls | Spill reads | Tool misses | Cost/trial | Total cost | Overflow | Errors | Latency ms |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| baseline_full_history | full | 0.00 | 0.00 | 0.00 | 39,525 | 768 | 0.0 | 0.0 | 0.0 | $0.0632 | $0.3162 | 100% | 0% | 2 |
| baseline_full_history | spill | 0.00 | 0.00 | 0.00 | 12,973 | 768 | 0.0 | 0.0 | 0.0 | $0.0208 | $0.1038 | 100% | 0% | 1 |
| sliding_window | full | 0.00 | 0.00 | 0.00 | 4,459 | 768 | 0.0 | 0.0 | 0.0 | $0.0071 | $0.0357 | 0% | 0% | 1 |
| sliding_window | spill | 0.00 | 0.00 | 0.00 | 6,897 | 768 | 0.0 | 0.0 | 0.0 | $0.0110 | $0.0552 | 0% | 0% | 1 |
| message_selection | full | 0.00 | 0.00 | 0.00 | 6,749 | 768 | 0.0 | 0.0 | 0.0 | $0.0108 | $0.0540 | 0% | 0% | 5 |
| message_selection | spill | 0.00 | 0.00 | 0.00 | 6,852 | 768 | 0.0 | 0.0 | 0.0 | $0.0110 | $0.0548 | 0% | 0% | 3 |
| message_selection_decision | full | 0.00 | 0.00 | 0.00 | 7,486 | 21,597 | 0.0 | 0.0 | 0.0 | $0.0537 | $0.2685 | 0% | 0% | 7 |
| message_selection_decision | spill | 0.00 | 0.00 | 0.00 | 7,554 | 20,951 | 0.0 | 0.0 | 0.0 | $0.0528 | $0.2639 | 0% | 0% | 6 |
| anchored_compaction | full | 0.00 | 0.00 | 0.00 | 6,779 | 6,564 | 0.0 | 0.0 | 0.0 | $0.0143 | $0.0714 | 0% | 0% | 3 |
| anchored_compaction | spill | 0.00 | 0.00 | 0.00 | 6,393 | 4,863 | 0.0 | 0.0 | 0.0 | $0.0127 | $0.0633 | 0% | 0% | 3 |

## Retention by fact position

| Arm | Variant | Early | Middle | Late |
|---|---|---|---|---|
| baseline_full_history | full | 0.00 | 0.00 | 0.00 |
| baseline_full_history | spill | 0.00 | 0.00 | 0.00 |
| sliding_window | full | 0.00 | 0.00 | 0.00 |
| sliding_window | spill | 0.00 | 0.00 | 0.00 |
| message_selection | full | 0.00 | 0.00 | 0.00 |
| message_selection | spill | 0.00 | 0.00 | 0.00 |
| message_selection_decision | full | 0.00 | 0.00 | 0.00 |
| message_selection_decision | spill | 0.00 | 0.00 | 0.00 |
| anchored_compaction | full | 0.00 | 0.00 | 0.00 |
| anchored_compaction | spill | 0.00 | 0.00 | 0.00 |

## Errors

- No trial reported an error.

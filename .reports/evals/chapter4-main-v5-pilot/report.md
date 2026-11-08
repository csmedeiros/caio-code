# Chat-replay evaluation chapter4-main-v5-pilot

- Dataset: `long_histories_128k` (1 cases)
- Model: `qwen3.8-max`
- Declared window: 40,000 tokens
- Repetitions per case: 1 (pass^k uses all of them)
- Seed: 20261031
- Started: 2026-11-08T00:01:17.362867+00:00 - finished: 2026-11-08T00:12:56.711824+00:00
- Total cost: $1.4136
- Trials: 10
- Cache hit is **not reported**: a replayed history cannot measure a
  provider prompt cache honestly (see threats to validity).

## Arms x variants

| Arm | Variant | Retention | pass^k | All probes | Prompt tok | Aux tok | Tool calls | Spill reads | Tool misses | Cost/trial | Total cost | Overflow | Errors | Latency ms |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| baseline_full_history | full | 1.00 | 1.00 | 1.00 | 219,421 | 11,427 | 0.0 | 0.0 | 0.0 | $0.3613 | $0.3613 | 100% | 0% | 61,418 |
| baseline_full_history | spill | 1.00 | 1.00 | 1.00 | 69,781 | 11,547 | 0.0 | 0.0 | 0.0 | $0.1320 | $0.1320 | 100% | 0% | 84,769 |
| sliding_window | full | 0.42 | 0.00 | 0.00 | 48,704 | 15,147 | 0.0 | 0.0 | 0.0 | $0.1047 | $0.1047 | 0% | 0% | 96,073 |
| sliding_window | spill | 0.58 | 0.00 | 0.00 | 57,226 | 12,687 | 0.0 | 0.0 | 0.0 | $0.1127 | $0.1127 | 0% | 0% | 73,343 |
| message_selection | full | 1.00 | 1.00 | 1.00 | 56,096 | 9,711 | 0.0 | 0.0 | 0.0 | $0.1008 | $0.1008 | 0% | 0% | 49,005 |
| message_selection | spill | 1.00 | 1.00 | 1.00 | 56,438 | 8,055 | 0.0 | 0.0 | 0.0 | $0.0992 | $0.0992 | 0% | 0% | 47,898 |
| message_selection_decision | full | 1.00 | 1.00 | 1.00 | 52,390 | 127,887 | 0.0 | 0.0 | 0.0 | $0.2197 | $0.2197 | 0% | 0% | 62,329 |
| message_selection_decision | spill | 1.00 | 1.00 | 1.00 | 51,002 | 123,435 | 0.0 | 0.0 | 0.0 | $0.1732 | $0.1732 | 0% | 0% | 37,430 |
| anchored_compaction | full | 0.83 | 0.00 | 0.00 | 51,233 | 28,209 | 0.0 | 0.0 | 0.0 | $0.1099 | $0.1099 | 0% | 0% | 155,712 |
| anchored_compaction | spill | 0.00 | 0.00 | 0.00 | 0 | 0 | 0.0 | 0.0 | 0.0 | $0.0000 | $0.0000 | 0% | 100% | 603,200 |

## Retention by fact position

| Arm | Variant | Early | Middle | Late |
|---|---|---|---|---|
| baseline_full_history | full | 1.00 | 1.00 | 1.00 |
| baseline_full_history | spill | 1.00 | 1.00 | 1.00 |
| sliding_window | full | 0.00 | 0.25 | 1.00 |
| sliding_window | spill | 0.00 | 0.75 | 1.00 |
| message_selection | full | 1.00 | 1.00 | 1.00 |
| message_selection | spill | 1.00 | 1.00 | 1.00 |
| message_selection_decision | full | 1.00 | 1.00 | 1.00 |
| message_selection_decision | spill | 1.00 | 1.00 | 1.00 |
| anchored_compaction | full | 0.50 | 1.00 | 1.00 |
| anchored_compaction | spill | 0.00 | 0.00 | 0.00 |

## Errors

- **anchored_compaction** (spill): ProviderError while shaping the context: model call to 'qwen3.8-flash' failed after 2 attempts: APITimeoutError | Request timed out.

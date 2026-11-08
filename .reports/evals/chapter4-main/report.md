# Context-policy experiment chapter4-main

- Dataset: `long_histories` (5 cases)
- Model: `qwen3.8-max`
- Declared window: 8,000 tokens
- Repetitions per case: 3 (pass^k uses all of them)
- Seed: 20261031
- Started: 2026-11-01T12:11:42.027832+00:00 - finished: 2026-11-01T13:13:36.270670+00:00
- Total cost: $3.0554
- Trials: 135

## Arms

| Arm | Retention | pass^k | All probes | Prompt tok | Cache hit | Cost/trial | Total cost | Overflow | Errors | Latency ms |
|---|---|---|---|---|---|---|---|---|---|---|
| baseline_full_history | 0.97 | 0.80 | 0.87 | 54,459 | 99.3% | $0.0425 | $0.6377 | 100% | 0% | 43,846 |
| baseline_capped | 0.00 | 0.00 | 0.00 | 0 | 0.0% | $0.0000 | $0.0000 | 100% | 100% | 1 |
| sliding_window | 0.23 | 0.00 | 0.00 | 2,984 | 82.1% | $0.0121 | $0.1821 | 0% | 40% | 220,909 |
| message_selection | 0.68 | 0.20 | 0.20 | 8,688 | 71.5% | $0.0244 | $0.3663 | 0% | 0% | 66,501 |
| anchored_compaction | 0.50 | 0.00 | 0.00 | 10,960 | 47.3% | $0.0176 | $0.2635 | 0% | 20% | 190,388 |
| tool_truncation_only | 0.59 | 0.00 | 0.07 | 39,473 | 82.5% | $0.0429 | $0.6440 | 100% | 20% | 172,165 |
| sliding_window_plus_truncation | 0.21 | 0.00 | 0.00 | 3,290 | 76.3% | $0.0144 | $0.2160 | 0% | 47% | 235,522 |
| message_selection_plus_truncation | 0.75 | 0.20 | 0.20 | 8,688 | 71.5% | $0.0268 | $0.4018 | 0% | 0% | 89,262 |
| anchored_compaction_plus_truncation | 0.60 | 0.00 | 0.00 | 12,451 | 39.5% | $0.0229 | $0.3440 | 0% | 7% | 161,162 |

## Retention by fact position

| Arm | Early | Middle | Late |
|---|---|---|---|
| baseline_full_history | 1.00 | 1.00 | 0.90 |
| baseline_capped | 0.00 | 0.00 | 0.00 |
| sliding_window | 0.00 | 0.20 | 0.48 |
| message_selection | 0.87 | 0.53 | 0.76 |
| anchored_compaction | 0.60 | 0.37 | 0.67 |
| tool_truncation_only | 0.80 | 0.37 | 0.81 |
| sliding_window_plus_truncation | 0.00 | 0.20 | 0.38 |
| message_selection_plus_truncation | 1.00 | 0.57 | 0.86 |
| anchored_compaction_plus_truncation | 0.73 | 0.40 | 0.86 |

## Arm descriptions

- **baseline_capped**: context overflow: the arm refuses to send 42176 tokens against a window of 8000
- **sliding_window**: provider error: model call to 'qwen3.8-max' failed after 3 attempts: APITimeoutError | Request timed out.
- **anchored_compaction**: provider error: model call to 'qwen3.8-max' failed after 3 attempts: APITimeoutError | Request timed out.
- **tool_truncation_only**: provider error: model call to 'qwen3.8-max' failed after 3 attempts: APITimeoutError | Request timed out.
- **sliding_window_plus_truncation**: provider error: model call to 'qwen3.8-max' failed after 3 attempts: APITimeoutError | Request timed out.
- **anchored_compaction_plus_truncation**: provider error: model call to 'qwen3.8-max' failed after 3 attempts: APITimeoutError | Request timed out.

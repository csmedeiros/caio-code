# Context-policy experiment chapter4-main-v2

- Dataset: `long_histories` (5 cases)
- Model: `qwen3.8-max`
- Declared window: 8,000 tokens
- Repetitions per case: 3 (pass^k uses all of them)
- Seed: 20261031
- Started: 2026-11-01T13:21:20.955224+00:00 - finished: 2026-11-01T14:13:59.619215+00:00
- Total cost: $5.2542
- Trials: 135

## Arms

| Arm | Retention | pass^k | All probes | Prompt tok | Cache hit | Cost/trial | Total cost | Overflow | Errors | Latency ms |
|---|---|---|---|---|---|---|---|---|---|---|
| baseline_full_history | 0.94 | 0.60 | 0.73 | 54,459 | 67.7% | $0.0634 | $0.9515 | 100% | 0% | 58,511 |
| baseline_capped | 0.00 | 0.00 | 0.00 | 0 | 0.0% | $0.0000 | $0.0000 | 100% | 100% | 0 |
| sliding_window | 0.49 | 0.00 | 0.00 | 5,816 | 62.5% | $0.0631 | $0.9461 | 0% | 0% | 208,116 |
| message_selection | 0.75 | 0.00 | 0.07 | 8,688 | 74.6% | $0.0274 | $0.4109 | 0% | 0% | 71,760 |
| anchored_compaction | 0.58 | 0.00 | 0.00 | 13,313 | 31.8% | $0.0336 | $0.5045 | 0% | 0% | 154,142 |
| tool_truncation_only | 0.72 | 0.00 | 0.07 | 49,480 | 81.6% | $0.0636 | $0.9547 | 100% | 0% | 145,897 |
| sliding_window_plus_truncation | 0.31 | 0.00 | 0.00 | 5,816 | 92.7% | $0.0359 | $0.5380 | 0% | 0% | 115,115 |
| message_selection_plus_truncation | 0.79 | 0.20 | 0.20 | 8,688 | 92.7% | $0.0246 | $0.3688 | 0% | 0% | 65,919 |
| anchored_compaction_plus_truncation | 0.67 | 0.00 | 0.07 | 13,358 | 32.2% | $0.0386 | $0.5796 | 0% | 0% | 170,790 |

## Retention by fact position

| Arm | Early | Middle | Late |
|---|---|---|---|
| baseline_full_history | 1.00 | 0.97 | 0.86 |
| baseline_capped | 0.00 | 0.00 | 0.00 |
| sliding_window | 0.00 | 0.47 | 0.90 |
| message_selection | 1.00 | 0.53 | 0.90 |
| anchored_compaction | 0.73 | 0.40 | 0.76 |
| tool_truncation_only | 1.00 | 0.47 | 0.90 |
| sliding_window_plus_truncation | 0.00 | 0.30 | 0.57 |
| message_selection_plus_truncation | 1.00 | 0.60 | 0.90 |
| anchored_compaction_plus_truncation | 0.80 | 0.47 | 0.90 |

## Arm descriptions

- **baseline_capped**: context overflow: the arm refuses to send 42176 tokens against a window of 8000

# Context-policy experiment chapter4-main-v4

- Dataset: `long_histories` (5 cases)
- Model: `qwen3.8-max`
- Declared window: 8,000 tokens
- Repetitions per case: 3 (pass^k uses all of them)
- Seed: 20261031
- Started: 2026-11-01T16:56:47.555606+00:00 - finished: 2026-11-01T17:56:07.897550+00:00
- Total cost: $7.5541
- Trials: 165

## Arms

| Arm | Retention | pass^k | All probes | Prompt tok | Aux tok | Cache hit | Cost/trial | Total cost | Overflow | Errors | Latency ms |
|---|---|---|---|---|---|---|---|---|---|---|---|
| baseline_full_history | 0.98 | 0.80 | 0.93 | 54,459 | 0 | 68.5% | $0.0580 | $0.8702 | 100% | 0% | 29,632 |
| baseline_capped | 0.00 | 0.00 | 0.00 | 0 | 0 | 0.0% | $0.0000 | $0.0000 | 100% | 100% | 1 |
| sliding_window | 0.35 | 0.00 | 0.00 | 5,816 | 0 | 80.1% | $0.0417 | $0.6260 | 0% | 0% | 167,583 |
| message_selection | 0.75 | 0.20 | 0.20 | 8,688 | 0 | 81.7% | $0.0245 | $0.3681 | 0% | 0% | 63,023 |
| message_selection_decision | 0.75 | 0.00 | 0.13 | 9,038 | 36,009 | 16.6% | $0.0772 | $1.1579 | 0% | 0% | 104,556 |
| message_selection_decision_plus_truncation | 0.74 | 0.00 | 0.00 | 8,969 | 36,009 | 18.8% | $0.0701 | $1.0518 | 0% | 0% | 81,177 |
| anchored_compaction | 0.59 | 0.00 | 0.00 | 7,187 | 6,172 | 32.2% | $0.0368 | $0.5525 | 40% | 0% | 164,979 |
| tool_truncation_only | 0.75 | 0.00 | 0.07 | 49,480 | 0 | 73.5% | $0.0752 | $1.1282 | 100% | 0% | 139,290 |
| sliding_window_plus_truncation | 0.40 | 0.00 | 0.00 | 5,816 | 0 | 66.0% | $0.0544 | $0.8162 | 0% | 0% | 176,216 |
| message_selection_plus_truncation | 0.79 | 0.00 | 0.13 | 8,688 | 0 | 75.4% | $0.0272 | $0.4079 | 0% | 0% | 66,945 |
| anchored_compaction_plus_truncation | 0.64 | 0.00 | 0.00 | 7,208 | 6,172 | 37.5% | $0.0383 | $0.5752 | 40% | 0% | 173,582 |

## Retention by fact position

| Arm | Early | Middle | Late |
|---|---|---|---|
| baseline_full_history | 1.00 | 0.97 | 1.00 |
| baseline_capped | 0.00 | 0.00 | 0.00 |
| sliding_window | 0.00 | 0.37 | 0.57 |
| message_selection | 0.93 | 0.57 | 0.90 |
| message_selection_decision | 0.93 | 0.53 | 0.95 |
| message_selection_decision_plus_truncation | 1.00 | 0.47 | 0.95 |
| anchored_compaction | 0.73 | 0.40 | 0.81 |
| tool_truncation_only | 1.00 | 0.50 | 0.95 |
| sliding_window_plus_truncation | 0.00 | 0.37 | 0.76 |
| message_selection_plus_truncation | 1.00 | 0.57 | 0.95 |
| anchored_compaction_plus_truncation | 0.80 | 0.40 | 0.90 |

## Arm descriptions

- **baseline_capped**: context overflow: the arm refuses to send 42324 tokens against a window of 8000

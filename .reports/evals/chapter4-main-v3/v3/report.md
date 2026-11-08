# Context-policy experiment v3

- Dataset: `long_histories` (5 cases)
- Model: `qwen3.8-max`
- Declared window: 8,000 tokens
- Repetitions per case: 3 (pass^k uses all of them)
- Seed: 20261031
- Started: 2026-11-01T15:41:40.030539+00:00 - finished: 2026-11-01T16:50:31.626924+00:00
- Total cost: $5.1069
- Trials: 165

## Arms

| Arm | Retention | pass^k | All probes | Prompt tok | Aux tok | Cache hit | Cost/trial | Total cost | Overflow | Errors | Latency ms |
|---|---|---|---|---|---|---|---|---|---|---|---|
| baseline_full_history | 0.97 | 0.60 | 0.87 | 54,459 | 0 | 99.3% | $0.0441 | $0.6610 | 100% | 0% | 41,713 |
| baseline_capped | 0.00 | 0.00 | 0.00 | 0 | 0 | 0.0% | $0.0000 | $0.0000 | 100% | 100% | 1 |
| sliding_window | 0.26 | 0.00 | 0.00 | 4,102 | 0 | 78.2% | $0.0237 | $0.3554 | 0% | 20% | 184,022 |
| message_selection | 0.77 | 0.20 | 0.20 | 8,688 | 0 | 71.5% | $0.0261 | $0.3915 | 0% | 0% | 63,693 |
| message_selection_decision | 0.60 | 0.00 | 0.07 | 18,785 | 36,009 | 14.9% | $0.0584 | $0.8764 | 0% | 20% | 136,571 |
| message_selection_decision_plus_truncation | 0.65 | 0.00 | 0.00 | 15,558 | 36,009 | 17.2% | $0.0554 | $0.8308 | 0% | 13% | 103,330 |
| anchored_compaction | 0.55 | 0.00 | 0.07 | 5,876 | 6,172 | 47.2% | $0.0201 | $0.3021 | 40% | 20% | 210,369 |
| tool_truncation_only | 0.49 | 0.00 | 0.00 | 34,249 | 0 | 74.1% | $0.0396 | $0.5940 | 100% | 27% | 169,037 |
| sliding_window_plus_truncation | 0.23 | 0.00 | 0.00 | 4,526 | 0 | 67.9% | $0.0205 | $0.3082 | 0% | 20% | 142,380 |
| message_selection_plus_truncation | 0.75 | 0.00 | 0.07 | 8,688 | 0 | 74.6% | $0.0283 | $0.4247 | 0% | 0% | 105,397 |
| anchored_compaction_plus_truncation | 0.48 | 0.00 | 0.00 | 6,358 | 6,172 | 38.5% | $0.0242 | $0.3629 | 40% | 13% | 187,351 |

## Retention by fact position

| Arm | Early | Middle | Late |
|---|---|---|---|
| baseline_full_history | 1.00 | 0.97 | 0.95 |
| baseline_capped | 0.00 | 0.00 | 0.00 |
| sliding_window | 0.00 | 0.27 | 0.43 |
| message_selection | 1.00 | 0.60 | 0.86 |
| message_selection_decision | 0.80 | 0.43 | 0.76 |
| message_selection_decision_plus_truncation | 0.87 | 0.43 | 0.86 |
| anchored_compaction | 0.67 | 0.37 | 0.81 |
| tool_truncation_only | 0.73 | 0.27 | 0.71 |
| sliding_window_plus_truncation | 0.00 | 0.27 | 0.33 |
| message_selection_plus_truncation | 1.00 | 0.53 | 0.90 |
| anchored_compaction_plus_truncation | 0.60 | 0.33 | 0.67 |

## Arm descriptions

- **baseline_capped**: context overflow: the arm refuses to send 42324 tokens against a window of 8000
- **sliding_window**: provider error: model call to 'qwen3.8-max' failed after 3 attempts: APITimeoutError | Request timed out.
- **message_selection_decision**: provider error: model call to 'qwen3.8-max' failed after 3 attempts: APITimeoutError | Request timed out.
- **message_selection_decision_plus_truncation**: provider error: model call to 'qwen3.8-max' failed after 3 attempts: APITimeoutError | Request timed out.
- **anchored_compaction**: provider error: model call to 'qwen3.8-max' failed after 3 attempts: APITimeoutError | Request timed out.
- **tool_truncation_only**: provider error: model call to 'qwen3.8-max' failed after 3 attempts: APITimeoutError | Request timed out.
- **sliding_window_plus_truncation**: provider error: model call to 'qwen3.8-max' failed after 3 attempts: APITimeoutError | Request timed out.
- **anchored_compaction_plus_truncation**: provider error: model call to 'qwen3.8-max' failed after 3 attempts: APITimeoutError | Request timed out.

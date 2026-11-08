# Experiment runs

Evidence for Chapter 4 of the thesis. Each directory is one run of
`caio-code evaluate` (or `scripts/run_experiment*.py`), written by
`caio_code.application.experiment.runner`.

| File | Content |
|---|---|
| `results.json` | run metadata, per-arm aggregates, and every trial with its probes, usage, cache, cost and policy record |
| `report.md` | the comparison table plus retention by fact position |
| `trials.jsonl` | one line per trial, flushed as it finished (crash-safe progress log) |

Read them with `python scripts/summarize_experiment.py --run <run_id>`, which adds the spread
across repetitions and the dollars per correctly retained fact.

## Runs

### `chapter4-main-v5` — authoritative

Chat-replay run of Chapter 4: five arms x five cases x two variants (`full`, `spill`) x one
repetition = 50 trials, `qwen3.8-max` over the OpenAI-compatible endpoint, declared window
40,000 tokens, provider timeout 900 s, two retries, concurrency 5. Total cost **$7.4246**,
zero errors, zero tool misses.

Unlike v4, each trial is a replay with one shaping step followed by the case's 12 probes
asked in-band to the same agent, which may call tools (cap 3 calls) against a recorded tool
server; an LLM judge (`qwen3.8-flash`, `evals/prompts/judge_v1.md`) grades each answer
without ever seeing the context. Calibration: 28/30 agreement (93.3%) against the stored labels — 29/30 after fixing one mislabel, see `chapter4-main-v5-pilot/calibration-recheck.md` — against labels produced
by two independent blind assistants — not the author — disclosed as a threat to validity.

- `full` is the history as recorded; `spill` replaces tool outputs above
  `ToolOutputConfig.max_bytes` (51.2 KB) with a pointer the agent can read back.
- The 40k window sits below the smallest case in both variants (spill 41.6k, full 114.2k
  proxy tokens), so the seeded history always overflows and the shaping step always fires.
- There is no pass$^k$: one repetition, temperature 0.0, retention is the metric.
- **Cache hit is not reported.** A replayed history cannot measure a provider prompt cache
  honestly; the v4 cache numbers are withdrawn, not reinterpreted.

Headline numbers: `message_selection` retains 0.97 (full) and 0.90 (spill) at 52,671 and
86,614 prompt tokens and $0.0945/$0.1406 per trial; `baseline_full_history` retains 1.00/0.93
at 211,989/72,462 tokens and $0.3498/$0.1296, overflowing in 100% of trials; the decision
model retains 0.70/0.88 while spending 71,623/105,950 auxiliary tokens per trial, six to ten
times the lexical scorer, with no retention gain; `anchored_compaction` retains 0.75/0.70 and
loses the early facts (0.45/0.55). The pilot and judge calibration of this run are in
`chapter4-main-v5-pilot`.

### `chapter4-main-v4` — superseded by v5, kept as evidence

Eleven arms x five cases x three repetitions = 165 trials, `qwen3.8-max` over the
OpenAI-compatible endpoint, declared window 8,000 tokens, provider timeout 420 s, one retry,
concurrency 5. Total cost $7.55. No provider failures: the only 15 errors are the
`baseline_capped` arm refusing to send a context that does not fit its window, which is the
measurement and not a defect.

This is the first run with the two decision-model arms (`message_selection_decision`,
`message_selection_decision_plus_truncation`), where relevance is judged by TypeSafe Jev
instead of the lexical scorer, and the first to split the token bill in two columns:

- `prompt tok` = `probe_usage`, what the agent model was actually sent. Arms are compared on
  this column.
- `aux tok` = `aux_usage`, what the arm spent to shape that context: the summarizer call and
  the Jev calls. It is inside `$/trial` and outside `prompt tok`.

Jev's tokens are priced by `FALLBACK_PRICE` ($1.00 / $0.50 / $3.00 per million) because
TypeSafe publishes no list price; the decision arms' `$/trial` is therefore an estimate,
labelled as such wherever it is quoted.

Headline numbers: `message_selection` retains 0.75 of the critical facts at 8,688 prompt
tokens and $0.0245 per trial, against `baseline_full_history` at 0.98 retention, 54,459
tokens and $0.0580. Judging relevance with the decision model instead of the lexical scorer
does **not** buy retention (0.75 vs 0.75) and costs 36,009 auxiliary tokens and roughly
three times the money per trial ($0.0772 vs $0.0245); it also drops the cache hit ratio from
82% to 17%, because a probabilistic score reshuffles the prefix on every repetition.

### `chapter4-main-v3` — superseded, kept as evidence

Same eleven arms, but launched without the provider-timeout overrides, so it ran on the 120 s
default instead of 420 s. Twenty trials died on `APITimeoutError`, spread unevenly across
seven arms (four of them `tool_truncation_only`, none of `message_selection`), which is the
same asymmetry that invalidated `chapter4-main`. Its `mean_prompt_tokens` also predates the
fix that keeps a failed trial's auxiliary bill out of the prompt column, so the decision arms
read ~18.8k prompt tokens there against ~9.0k in `chapter4-main-v4`. Kept because the
timeout is a finding about measuring agents on a shared endpoint, not a code defect.

### `chapter4-main-v2` — superseded by v4, kept as evidence

Nine arms x five cases x three repetitions = 135 trials, `qwen3.8-max` over the OpenAI-compatible
endpoint, declared window 8,000 tokens, provider timeout 420 s, one retry, concurrency 5.
No provider failures: the only 15 errors are the `baseline_capped` arm refusing to send a context
that does not fit its window, which is the measurement and not a defect. Total cost $5.25.

### `chapter4-main` — superseded, kept as evidence

Same matrix with a 120 s provider timeout. Twenty trials died on `APITimeoutError` (observed
latencies reached 467 s), spread unevenly across arms - 47% of the window-plus-truncation trials
and none of the selection ones - which is exactly the kind of asymmetry that invalidates a
comparison. Kept because the timeout is itself a finding about measuring agents on a shared
endpoint, and because the two runs agree on every arm that succeeded in both.

Two measurement notes that apply to `chapter4-main` and `chapter4-main-v2` alike (v4 reports
the real `tokens_after_policy` and separates prompt from auxiliary tokens):

1. `tokens_after_policy` of the compaction arms is priced on the summary *placeholder*, because the
   planner cannot know the length of a summary that does not exist yet. The authoritative size of
   what those arms sent is `usage.input_tokens` (provider-reported): 13.3k tokens on average,
   above the 8k declared window, because `keep_tokens` (8k) plus a summary of up to
   `summary_max_tokens` (4k) cannot fit it. The runner re-measures the shaped context after
   compaction, so runs executed after that fix report the real number in `tokens_after_policy`;
   both runs above predate it.
2. Cache ratios come from the provider's own `prompt_tokens_details.cached_tokens`. They differ
   structurally between arms: a stable prefix (window, selection) reaches 62-93%, while a
   compaction rewrites the prefix on every summarization and stays near 32%.

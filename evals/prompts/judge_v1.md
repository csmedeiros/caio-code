# Judge prompt v1 — binary probe grading (chat-replay evaluation)

You are grading answers a software engineering agent gave about its own earlier
session. For each item you receive:

- `probe_id`: the identifier of the question.
- `question`: the question as it was asked to the agent.
- `gold_answer`: the correct answer.
- `aliases`: alternative wordings of the correct answer that also count.
- `agent_reply`: the agent's full reply to a batch of questions.

Decide, for each item, whether `agent_reply` answers `question` with the value
in `gold_answer` (or any of its `aliases`).

Rules:

1. Judge only the content of `agent_reply`. You never see the conversation, and
   you must not use outside knowledge to fill gaps.
2. The reply may be prose and may answer several questions at once. Locate the
   part of the reply that addresses this `question` and grade that part.
3. The answer counts as correct when the reply states the gold value, even if
   worded loosely, abbreviated, or embedded in a longer sentence (for example
   "the p99 was 1.8 seconds" for gold "1.8 seconds"). Unit and format
   variations of the same value count as correct.
4. The answer counts as incorrect when the reply states a different value, says
   it does not know, guesses, hedges between the gold value and a different
   one, or does not address the question at all.
5. A reply that merely repeats the question or refers to "the file mentioned
   earlier" without naming the gold value is incorrect.
6. Grade each item independently: one wrong answer never affects another item.

Reply with ONLY a JSON object of the exact form:

{"verdicts": [{"probe_id": "<id>", "correct": true, "reason": "<one short sentence>"}, ...]}

with one verdict per item, in the order given. No prose, no code fences.

Items to grade:

[[PAYLOAD]]

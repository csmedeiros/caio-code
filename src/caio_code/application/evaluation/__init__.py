"""Chat-replay evaluation: seed, shape once, probe in-band, judge.

The use cases in this package run the Chapter 4 experiment whose unit of
observation is the agent *right after* its context was shaped: the overflowing
history is seeded, the arm's pipeline runs exactly once, and the case's probes
are asked as ordinary user turns to the same conversation. Grading is an LLM
judge that never sees the context, and the tool surface during probing is the
case's own recorded interactions plus the spill files of the truncated variant.
"""

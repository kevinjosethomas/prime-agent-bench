"""Benchmark scenarios: one file per scenario.

Measurement semantics (suite spec): launch = exec boundary; first paint =
first non-blank rendered frame; interactive-ready = typed token echoed AND
accepted AND erased (no submit); resumed transcripts require tail sentinel
AND typed echo; frame completeness = chunk-burst decomposition; wall
clock = monotonic controller-side seconds (ms reported).
"""

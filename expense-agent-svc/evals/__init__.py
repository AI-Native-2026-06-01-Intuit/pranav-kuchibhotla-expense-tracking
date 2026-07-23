"""Trajectory + cost-regression + optional RAGAS gate for expense-agent-svc.

Deterministic (`--gate`) mode runs the 20 committed scenarios through
fake node bodies and asserts:

* Ordered trajectory match >=0.70 (see :mod:`.trajectory` for the
  exact matcher).
* Answer-substring match >=0.70.
* Per-scenario cost regression <=15% versus the committed baseline in
  ``evals/last_run.json``.

External (`--external`) mode additionally runs RAGAS faithfulness on
the same scenarios using the injected evaluator. The faithfulness
floor is 0.85. Missing credentials fail loudly unless the local skip
flag is set.
"""

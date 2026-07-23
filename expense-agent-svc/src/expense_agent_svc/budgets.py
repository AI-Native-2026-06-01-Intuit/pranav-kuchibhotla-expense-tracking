"""Per-request budget guard.

Every incoming ``/v1/chat/stream`` request builds its own
:class:`BudgetGuard`. Nodes call :meth:`BudgetGuard.check_or_raise`
before every LLM/tool interaction that could add cost, and
:meth:`BudgetGuard.add_cost` (or :meth:`BudgetGuard.record_usage`) after
the interaction completes.

Money accounting rules (non-negotiable):

* Cost is an **integer** in ``1e-5 USD`` units (``cost_usd_e5``). One
  cent is ``1_000``. This keeps two-branch fan-in and checkpoint replays
  bit-exact — a float cost would round differently on Intel and ARM,
  and would drift across a resumed run.
* Token rates are integers of "``1e-5 USD`` per million tokens" so
  ``tokens * rate // 1_000_000`` stays in ``int`` land. Rates are
  configuration, not authoritative billing: production billing is the
  llm-proxy / CloudWatch metric, and this guard is the local safety
  ceiling.
* The ceiling is enforced strictly: once ``spent_usd_e5 >= ceiling`` the
  guard raises :class:`BudgetExceeded`. :meth:`add_cost` records the
  spend *before* raising, so a subsequent read of ``spent_usd_e5``
  reflects reality — this matches the assignment's "the total should
  reflect the recorded spend before the exception" clause.
"""

from __future__ import annotations


class BudgetExceeded(Exception):
    """Raised when a call would push cumulative spend at or above the ceiling.

    ``spent_usd_e5`` on the guard is left at the recorded post-charge
    total so callers/observers can log the overshoot amount without
    guessing.
    """


class BudgetGuard:
    """Local safety ceiling for a single request's LLM/tool spend.

    Not thread-safe by design — one guard per request, and a single
    request's node execution is coordinated by the LangGraph event loop.
    """

    _DEFAULT_CEILING_USD_E5 = 25_000
    _MICROS_PER_MILLION = 1_000_000

    def __init__(self, ceiling_usd_e5: int = _DEFAULT_CEILING_USD_E5) -> None:
        if not isinstance(ceiling_usd_e5, int):
            raise TypeError("ceiling_usd_e5 must be an int")
        if ceiling_usd_e5 < 0:
            raise ValueError("ceiling_usd_e5 must be >= 0")
        self._ceiling_usd_e5: int = ceiling_usd_e5
        self._spent_usd_e5: int = 0

    @property
    def ceiling_usd_e5(self) -> int:
        return self._ceiling_usd_e5

    @property
    def spent_usd_e5(self) -> int:
        return self._spent_usd_e5

    def check_or_raise(self) -> None:
        """Raise :class:`BudgetExceeded` if we are already at the ceiling.

        Called *before* every LLM/tool interaction. Once spend has met the
        ceiling from a prior charge, no further calls are allowed on this
        request.
        """
        if self._spent_usd_e5 >= self._ceiling_usd_e5:
            raise BudgetExceeded(
                f"budget already exhausted: "
                f"spent={self._spent_usd_e5} ceiling={self._ceiling_usd_e5}"
            )

    def add_cost(self, cost_usd_e5: int) -> None:
        """Record a completed LLM/tool spend.

        Zero cost is accepted (some tools are free); negative cost is not.
        Spend is recorded *before* the ceiling check, so callers observe
        the real overshoot. Non-integer cost is rejected outright — money
        is integer here.
        """
        if not isinstance(cost_usd_e5, int) or isinstance(cost_usd_e5, bool):
            raise TypeError("cost_usd_e5 must be an int")
        if cost_usd_e5 < 0:
            raise ValueError("cost_usd_e5 must be >= 0")
        self._spent_usd_e5 += cost_usd_e5
        if self._spent_usd_e5 >= self._ceiling_usd_e5:
            raise BudgetExceeded(
                f"budget exceeded on charge: "
                f"spent={self._spent_usd_e5} ceiling={self._ceiling_usd_e5}"
            )

    def record_usage(
        self,
        *,
        input_tokens: int,
        output_tokens: int,
        input_rate_usd_e5_per_million: int,
        output_rate_usd_e5_per_million: int,
    ) -> int:
        """Compute + record LLM usage cost from token counts and per-M rates.

        Returns the integer cost added. Uses ``//`` so the result stays
        an ``int``; the truncated fractional cent is intentional and
        matches what llm-proxy CloudWatch metrics do downstream.
        """
        for name, value in (
            ("input_tokens", input_tokens),
            ("output_tokens", output_tokens),
            ("input_rate_usd_e5_per_million", input_rate_usd_e5_per_million),
            ("output_rate_usd_e5_per_million", output_rate_usd_e5_per_million),
        ):
            if not isinstance(value, int) or isinstance(value, bool):
                raise TypeError(f"{name} must be an int")
            if value < 0:
                raise ValueError(f"{name} must be >= 0")
        cost_in = input_tokens * input_rate_usd_e5_per_million // self._MICROS_PER_MILLION
        cost_out = output_tokens * output_rate_usd_e5_per_million // self._MICROS_PER_MILLION
        cost = cost_in + cost_out
        self.add_cost(cost)
        return cost

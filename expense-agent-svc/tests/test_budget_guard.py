"""BudgetGuard behavioural contract.

Cover:

* Integer-only money; float or bool cost is rejected outright.
* Negative ceiling / cost / token counts are rejected.
* ``check_or_raise`` raises exactly at spent >= ceiling.
* ``add_cost`` records the spend *before* raising so an observer sees
  the real overshoot.
* Exact-ceiling boundary raises.
* ``record_usage`` computes ``tokens * rate // 1_000_000`` and returns
  the integer cost added.
* ``budgets.py`` itself contains no float money annotation.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from expense_agent_svc.budgets import BudgetExceeded, BudgetGuard


def test_default_ceiling_matches_rubric() -> None:
    g = BudgetGuard()
    assert g.ceiling_usd_e5 == 25_000
    assert g.spent_usd_e5 == 0


def test_check_or_raise_below_ceiling_passes() -> None:
    g = BudgetGuard(ceiling_usd_e5=1000)
    g.add_cost(500)
    # Well below ceiling — no raise.
    g.check_or_raise()
    assert g.spent_usd_e5 == 500


def test_check_or_raise_raises_when_already_at_ceiling() -> None:
    g = BudgetGuard(ceiling_usd_e5=1000)
    # Reach the ceiling via add_cost, which raises; then confirm check
    # keeps raising thereafter.
    with pytest.raises(BudgetExceeded):
        g.add_cost(1000)
    assert g.spent_usd_e5 == 1000
    with pytest.raises(BudgetExceeded):
        g.check_or_raise()


def test_add_cost_raises_on_exact_ceiling_and_records_spend() -> None:
    g = BudgetGuard(ceiling_usd_e5=1000)
    with pytest.raises(BudgetExceeded):
        g.add_cost(1000)
    # The spend was recorded *before* the raise.
    assert g.spent_usd_e5 == 1000


def test_add_cost_raises_on_overspend_and_records_overshoot() -> None:
    g = BudgetGuard(ceiling_usd_e5=1000)
    g.add_cost(600)
    with pytest.raises(BudgetExceeded):
        g.add_cost(500)
    # Observer sees the real overshoot, not 600.
    assert g.spent_usd_e5 == 1100


def test_zero_cost_is_accepted() -> None:
    g = BudgetGuard(ceiling_usd_e5=1000)
    g.add_cost(0)
    assert g.spent_usd_e5 == 0


def test_negative_cost_rejected() -> None:
    g = BudgetGuard(ceiling_usd_e5=1000)
    with pytest.raises(ValueError):
        g.add_cost(-1)


def test_negative_ceiling_rejected() -> None:
    with pytest.raises(ValueError):
        BudgetGuard(ceiling_usd_e5=-1)


def test_float_cost_rejected() -> None:
    g = BudgetGuard(ceiling_usd_e5=1000)
    with pytest.raises(TypeError):
        g.add_cost(1.5)  # type: ignore[arg-type]


def test_bool_cost_rejected() -> None:
    g = BudgetGuard(ceiling_usd_e5=1000)
    with pytest.raises(TypeError):
        # bool is an int subclass; the guard must catch it explicitly.
        g.add_cost(True)


def test_record_usage_deterministic_integer_math() -> None:
    g = BudgetGuard(ceiling_usd_e5=1_000_000)
    # 1M input tokens * 300 (per M) = 300; 500K output * 1500 = 750
    # Total 1050 cost_usd_e5.
    added = g.record_usage(
        input_tokens=1_000_000,
        output_tokens=500_000,
        input_rate_usd_e5_per_million=300,
        output_rate_usd_e5_per_million=1500,
    )
    assert added == 300 + 750
    assert g.spent_usd_e5 == 1050


def test_record_usage_truncates_fractional_cent() -> None:
    g = BudgetGuard(ceiling_usd_e5=1_000_000)
    # 999_999 * 300 // 1_000_000 = 299 (floor, not round)
    added = g.record_usage(
        input_tokens=999_999,
        output_tokens=0,
        input_rate_usd_e5_per_million=300,
        output_rate_usd_e5_per_million=0,
    )
    assert added == 299
    assert g.spent_usd_e5 == 299


def test_record_usage_rejects_negative_inputs() -> None:
    g = BudgetGuard(ceiling_usd_e5=1_000_000)
    with pytest.raises(ValueError):
        g.record_usage(
            input_tokens=-1,
            output_tokens=0,
            input_rate_usd_e5_per_million=1,
            output_rate_usd_e5_per_million=1,
        )


def test_record_usage_can_trip_ceiling() -> None:
    g = BudgetGuard(ceiling_usd_e5=100)
    with pytest.raises(BudgetExceeded):
        g.record_usage(
            input_tokens=1_000_000,
            output_tokens=0,
            input_rate_usd_e5_per_million=200,
            output_rate_usd_e5_per_million=0,
        )
    assert g.spent_usd_e5 == 200


def test_no_float_money_annotation_in_source() -> None:
    src = Path("src/expense_agent_svc/budgets.py").read_text()
    assert ": float" not in src, "budgets.py must never annotate money as float"
    assert "float(" not in src, "budgets.py must not cast to float"

"""The truth about the check, built from the stores at every model call and never stored, so the
model reads what the page saved even when no tool was called to fetch it.

- turn_state: the loan, its confirmed term, the payment ceiling and its source, the two caps a
  ceiling derived from the finances is the lower of, the check's finances with what is still
  missing, the finances of the person's latest other check, how many real offers and examples
  the check holds, the saved options with their price, the offers awaiting their lender (one
  quoted for less than the loan says so), whether the recommendation was checked against a
  ceiling and whether it holds one option alone, the scenarios already shown on the current
  options with the option each found cheapest, and what a steady payment's certainty costs
  against each option of its term whose payment moves, as one short English block
"""

from collections.abc import Mapping
from dataclasses import asdict
from decimal import Decimal
from typing import cast

from loan_agent.application.check_tools import (
    ToolDeps,
    finances_figures,
    price_text,
    scenario_outcome,
    shekels,
    summary,
    track_text,
)
from loan_agent.domain.models import (
    AwaitingOffer,
    Check,
    LoanRequest,
    Option,
    Recommendation,
    compares_options,
)
from loan_agent.ports.events import OPTION_SAVED, SCENARIO_SHOWN


async def turn_state(user_id: str, check_id: str, deps: ToolDeps) -> str:
    check = await deps.checks.get(user_id, check_id)
    previous = await deps.checks.latest_finances(user_id, other_than=check_id)
    recommendation = await deps.recommendations.latest(check_id)
    options = await deps.options.list(check_id)
    return summary(
        {
            "loan": "none yet" if check.loan is None else _one_line(asdict(check.loan)),
            "term_months": check.term_months,
            "payment_ceiling": check.payment_ceiling,
            "ceiling_source": check.ceiling_source,
            "ceiling_basis": await _ceiling_basis(check, deps),
            **finances_figures(check.finances),
            "previous_finances": None if previous is None else _one_line(asdict(previous)),
            "option_counts": _option_counts(options),
            "offers": "; ".join(map(_option_clause, options)) or None,
            "awaiting_offers": "; ".join(
                _awaiting_clause(offer, check.loan) for offer in await deps.awaiting.list(check_id)
            )
            or None,
            "recommendation": _recommendation_state(recommendation, options, check),
            "scenarios_shown": "; ".join(
                map(_scenario_clause, await deps.sink.since(check_id, SCENARIO_SHOWN, OPTION_SAVED))
            )
            or None,
            "certainty_price": "; ".join(_certainty_clauses(options)) or None,
        }
    )


async def _ceiling_basis(check: Check, deps: ToolDeps) -> str | None:
    """The engine's two caps behind a ceiling derived from the finances, so the model can show
    the person the calculation; None for a stated ceiling or no ceiling. The engine is asked at
    every call because the check stores only the ceiling."""
    if check.ceiling_source != "finances":
        return None
    bounds = await deps.engine.assess(check.finances.engine_profile())
    return (
        f"the lower of {bounds.income_share:.0%} of net_fixed_income = "
        f"{bounds.ceiling_by_income_share} and {bounds.disposable_share:.0%} of "
        f"(net_fixed_income minus fixed_expenses) = {bounds.ceiling_by_disposable_income}"
    )


def _one_line(values: Mapping[str, object]) -> str:
    return ", ".join(summary(values).splitlines())


def _option_clause(option: Option) -> str:
    """The option's single track, with its payments, its total and, for a payment that moves,
    the range of its total across the historical windows, all to the shekel. The payments are
    the first one, the highest on today's assumptions when the payment grows, and the highest in
    the worst historical window, so a steady payment is never set beside a first payment alone."""
    figures = option.summary
    payments = f"first_payment {shekels(figures.first_payment)}"
    if figures.peak_payment != figures.first_payment:
        payments += f", peak_payment {shekels(figures.peak_payment)}"
    if figures.total_paid_low is None or figures.total_paid_high is None:
        history = "total_paid_in_past_periods unchanging"
    else:
        # The engine reports the worst window and the range of totals together.
        assert figures.worst_peak_payment is not None
        assert figures.worst_start is not None and figures.worst_end is not None
        payments += (
            f", worst_past_payment {shekels(figures.worst_peak_payment)} "
            f"({figures.worst_start:%Y-%m} to {figures.worst_end:%Y-%m})"
        )
        history = (
            f"total_paid_in_past_periods {shekels(figures.total_paid_low)}-"
            f"{shekels(figures.total_paid_high)}"
        )
        if figures.total_paid_low > figures.total_paid:
            history += ", every one above total_paid"
        elif figures.total_paid_high < figures.total_paid:
            history += ", every one below total_paid"
    return (
        f"{option.id}: source {option.source}, lender {_or_none(option.lender)}, "
        f"rate {track_text(option)}, term_months {_term(option)}, {payments}, "
        f"total_paid {shekels(figures.total_paid)}, {history}, price ({price_text(option)})"
    )


def _term(option: Option) -> object:
    (track,) = cast(list[Mapping[str, object]], option.loan["tracks"])
    return track["term_months"]


def _certainty_clauses(options: list[Option]) -> list[str]:
    """For each option whose payment never moves, against each option of its term whose payment
    moves: how far its total stands from the other's total on today's assumptions, and from the
    other's highest total in any historical window. The gaps are of the amounts rounded to the
    shekel, so they add up with the totals the person reads."""
    clauses = []
    for steady in options:
        if steady.summary.total_paid_high is not None:
            continue
        for moving in options:
            highest = moving.summary.total_paid_high
            if highest is None or _term(moving) != _term(steady):
                continue
            total = shekels(steady.summary.total_paid)
            clauses.append(
                f"{steady.id} ({_or_none(steady.lender)}) total_paid is "
                f"{_against(total - shekels(moving.summary.total_paid))} the total_paid of "
                f"{moving.id} ({_or_none(moving.lender)}) and "
                f"{_against(total - shekels(highest))} its highest total in past periods"
            )
    return clauses


def _against(gap: Decimal) -> str:
    if gap == 0:
        return "equal to"
    return f"{abs(gap)} {'above' if gap > 0 else 'below'}"


def _scenario_clause(table: Mapping[str, object]) -> str:
    """The scenario a table priced, each movement as its yearly figure and, when the person gave
    it as the last years, those years too, with the option it found cheapest."""
    scenario = cast(Mapping[str, object], table["scenario"])
    named = cast(list[str], table["named"])
    movements = []
    for movement in ("cpi", "prime"):
        per_year = f"{movement}_per_year {scenario[f'{movement}_per_year']}"
        years = scenario[f"{movement}_like_last_years"]
        if years is not None:
            per_year += f" (as over the last {years} years)"
        elif f"{movement}_per_year" not in named:
            per_year += " (default)"
        movements.append(per_year)
    rows = cast(list[Mapping[str, object]], table["rows"])
    return f"{', '.join(movements)}: cheapest {scenario_outcome(rows)}"


def _option_counts(options: list[Option]) -> str:
    offers = sum(1 for option in options if option.source == "offer")
    return f"real offers {offers}, examples {len(options) - offers}"


def _awaiting_clause(offer: AwaitingOffer, loan: LoanRequest | None) -> str:
    kinds = "/".join(reading.kind for reading in offer.readings)
    clause = (
        f"{offer.id}: lender {offer.lender}, monthly_payment {_or_none(offer.monthly_payment)}, "
        f"readings {kinds}, likely {_or_none(offer.likely)}"
    )
    if loan is not None and offer.amount < loan.amount:
        clause += (
            f", quoted for {offer.amount}, less than the loan: awaits the lender's answer on "
            "lending the loan amount on the same terms"
        )
    return clause


def _or_none(value: object) -> str:
    """An optional value as the summary writes it."""
    return "none" if value is None else str(value)


def _recommendation_state(
    recommendation: Recommendation | None, options: list[Option], check: Check
) -> str:
    """Unchecked means made on the loans' merits, while the check had no ceiling. A
    recommendation whose card holds one option alone evaluates it rather than ranking it."""
    if recommendation is None:
        return "none"
    state = "checked" if recommendation.checked else "unchecked"
    if not compares_options(options, recommendation.named_option_ids, check.term_months):
        state += ", of one option alone: evaluate it, never recommend it"
    return state

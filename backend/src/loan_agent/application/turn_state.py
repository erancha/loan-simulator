"""The truth about the check, built from the stores at every model call and never stored, so the
model reads what the page saved even when no tool was called to fetch it.

- turn_state: the loan, its confirmed term, the payment ceiling and its source, the two caps a
  ceiling derived from the finances is the lower of, the check's finances with what is still
  missing, the finances of the person's latest other check, how many real offers and examples
  the check holds, the saved options with their price, the offers awaiting their lender (one
  quoted for less than the loan says so), and whether the recommendation was checked against a
  ceiling and whether it holds one option alone, as one short English block
"""

from collections.abc import Mapping
from dataclasses import asdict
from typing import cast

from loan_agent.application.check_tools import (
    ToolDeps,
    finances_figures,
    price_text,
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
    """The option's single track, with its first payment, its total and, for a payment that
    moves, the range of its total across the historical windows, all to the shekel."""
    (track,) = cast(list[Mapping[str, object]], option.loan["tracks"])
    figures = option.summary
    if figures.total_paid_low is None or figures.total_paid_high is None:
        history = "total_paid_in_past_periods unchanging"
    else:
        history = (
            f"total_paid_in_past_periods {shekels(figures.total_paid_low)}-"
            f"{shekels(figures.total_paid_high)}"
        )
    return (
        f"{option.id}: source {option.source}, lender {_or_none(option.lender)}, "
        f"rate {track_text(option)}, term_months {track['term_months']}, "
        f"first_payment {shekels(figures.first_payment)}, "
        f"total_paid {shekels(figures.total_paid)}, {history}, price ({price_text(option)})"
    )


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

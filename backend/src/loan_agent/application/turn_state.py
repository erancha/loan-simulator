"""The truth about the check, built from the stores at every model call and never stored, so the
model reads what the page saved even when no tool was called to fetch it.

- turn_state: the loan, its confirmed term, the payment ceiling and its source, the check's
  finances with what is still missing, the finances of the person's latest other check, and
  whether the recommendation was checked against a ceiling, as one short English block
"""

from collections.abc import Mapping
from dataclasses import asdict

from loan_agent.application.check_tools import ToolDeps, finances_figures, summary
from loan_agent.domain.models import Recommendation


async def turn_state(user_id: str, check_id: str, deps: ToolDeps) -> str:
    check = await deps.checks.get(user_id, check_id)
    previous = await deps.checks.latest_finances(user_id, other_than=check_id)
    recommendation = await deps.recommendations.latest(check_id)
    return summary(
        {
            "loan": "none yet" if check.loan is None else _one_line(asdict(check.loan)),
            "term_months": check.term_months,
            "payment_ceiling": check.payment_ceiling,
            "ceiling_source": check.ceiling_source,
            **finances_figures(check.finances),
            "previous_finances": None if previous is None else _one_line(asdict(previous)),
            "recommendation": _recommendation_state(recommendation),
        }
    )


def _one_line(values: Mapping[str, object]) -> str:
    return ", ".join(summary(values).splitlines())


def _recommendation_state(recommendation: Recommendation | None) -> str:
    """Unchecked means made on the loans' merits, while the check had no ceiling."""
    if recommendation is None:
        return "none"
    return "checked" if recommendation.checked else "unchecked"

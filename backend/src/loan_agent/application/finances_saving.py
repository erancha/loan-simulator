"""Saves a check's finances, the two figures of the help path, and the payment ceiling the engine
derives from them once both are known. The model's update_finances tool and the page's figures
panel both save through save_finances, so the two write the same check and emit the same event.

- save_finances: merge, store, derive and store the ceiling, emit finances.updated
"""

from collections.abc import Mapping
from dataclasses import asdict
from typing import TYPE_CHECKING

from loan_agent.domain.models import Check
from loan_agent.ports.events import FINANCES_UPDATED

if TYPE_CHECKING:
    # check_tools saves through this module, so importing ToolDeps at run time would be circular.
    from loan_agent.application.check_tools import ToolDeps


async def save_finances(
    check_id: str, user_id: str, update: Mapping[str, object], deps: "ToolDeps"
) -> Check:
    """Raises FinancesError, naming the field, or the engine's EngineError before anything is
    saved, so stored figures always produce the stored derived ceiling. A derived ceiling
    replaces whatever ceiling the check held, stated or derived: the source given last wins. The
    event carries the check's ceiling and its source after the save."""
    check = await deps.checks.get(user_id, check_id)
    finances = check.finances.merged(update)
    missing = finances.missing()
    derived = None
    if not missing:
        derived = (await deps.engine.assess(finances.engine_profile())).payment_ceiling
    await deps.checks.set_finances(check_id, finances)
    if derived is not None:
        await deps.checks.set_ceiling(check_id, derived, "finances")
    saved = await deps.checks.get(user_id, check_id)
    await deps.sink.emit(
        check_id,
        FINANCES_UPDATED,
        {
            "finances": {
                name: None if value is None else str(value)
                for name, value in asdict(finances).items()
            },
            "missing": list(missing),
            "payment_ceiling": None
            if saved.payment_ceiling is None
            else str(saved.payment_ceiling),
            "ceiling_source": saved.ceiling_source,
        },
    )
    return saved

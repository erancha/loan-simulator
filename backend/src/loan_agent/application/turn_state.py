"""The truth about the person's figures, built from the stores at every model call and never
stored, so the model reads what the page saved even when no tool was called to fetch it.

- turn_state: the profile fields, what is still missing and the goal, as one short English block
"""

from loan_agent.application.check_tools import ToolDeps, profile_figures, summary


async def turn_state(user_id: str, check_id: str, deps: ToolDeps) -> str:
    profile, _ = await deps.profiles.get(user_id)
    check = await deps.checks.get(user_id, check_id)
    if check.goal is None:
        goal = "none yet"
    else:
        goal = f"purpose: {check.goal.purpose}, price: {check.goal.price}"
    return summary({**profile_figures(profile), "goal": goal})

"""Domain errors; profile and goal errors carry a person-readable message naming the field."""

from datetime import datetime


class ProfileError(ValueError):
    """A profile update or read broke the profile contract."""


class GoalError(ValueError):
    """A loan goal has an amount outside its legal range."""


class CheckNotFoundError(Exception):
    """The check does not exist for this person."""


class TurnConflictError(Exception):
    """A turn is already running for the check."""

    def __init__(self, check_id: str) -> None:
        super().__init__(f"check {check_id!r} is still answering")
        self.check_id = check_id


class TurnLimitError(Exception):
    """The person used all the messages allowed across their checks within a rolling time window."""

    def __init__(self, limit: int, next_allowed: datetime) -> None:
        super().__init__(
            f"Message limit of {limit} reached; the next message is allowed at "
            f"{next_allowed.isoformat()}"
        )
        self.limit = limit
        self.next_allowed = next_allowed


class InvalidTokenError(Exception):
    """An ID token failed verification; the message says why, for the person."""

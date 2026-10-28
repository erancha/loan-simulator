"""Port to the identity provider: turns an ID token into the person it describes."""

from typing import Protocol, runtime_checkable

from loan_agent.domain.models import VerifiedToken


@runtime_checkable
class TokenVerifier(Protocol):
    def verify(self, token: str) -> VerifiedToken:
        """The person a valid token describes and when it expires; raises InvalidTokenError
        otherwise."""
        ...

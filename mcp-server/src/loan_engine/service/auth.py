"""Bearer-token check against the one static token set in ENGINE_BEARER_TOKEN."""

import hmac

from mcp.server.auth.provider import AccessToken
from pydantic import SecretStr

_CLIENT_ID = "agent"


class StaticTokenVerifier:
    def __init__(self, token: SecretStr) -> None:
        self._token = token.get_secret_value().encode()

    async def verify_token(self, token: str) -> AccessToken | None:
        """The single client's access, or None when the token differs; compares in constant time."""
        if hmac.compare_digest(token.encode(), self._token):
            return AccessToken(token=token, client_id=_CLIENT_ID, scopes=[])
        return None

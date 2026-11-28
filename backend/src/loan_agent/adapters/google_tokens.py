"""Verifies Google ID tokens locally: signature, issuer, expiry and audience.

Core building blocks:
- GoogleTokenVerifier: the TokenVerifier port over PyJWT; accepts only RS256 tokens for one
  client id, from the configured issuer, signed by a key its KeySource knows
- JwksKeys: Google's published keys, fetched from the JWKS URL and cached by PyJWT
- StaticKey: one public key from a PEM file, for tests that must not reach Google

Google issues its ID tokens under "https://accounts.google.com" and also the bare
"accounts.google.com"; the verifier accepts the bare form only for Google's issuer.
"""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Protocol, Self

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicKey
from jwt import PyJWK, PyJWKClient

from loan_agent.domain.errors import InvalidTokenError
from loan_agent.domain.models import User, VerifiedToken

GOOGLE_ISSUER = "https://accounts.google.com"
GOOGLE_JWKS_URL = "https://www.googleapis.com/oauth2/v3/certs"
ALGORITHM = "RS256"


class KeySource(Protocol):
    def key_for(self, token: str) -> PyJWK | RSAPublicKey:
        """The public key that signed the token, chosen by its key id; raises PyJWTError when
        the source has no such key."""
        ...


class JwksKeys:
    def __init__(self, url: str) -> None:
        self._client = PyJWKClient(url, cache_keys=True)

    def key_for(self, token: str) -> PyJWK:
        return self._client.get_signing_key_from_jwt(token)


class StaticKey:
    def __init__(self, pem: bytes) -> None:
        key = serialization.load_pem_public_key(pem)
        if not isinstance(key, RSAPublicKey):
            raise TypeError("the public key file must hold an RSA public key")
        self._key = key

    @classmethod
    def from_file(cls, path: Path) -> Self:
        return cls(path.read_bytes())

    def key_for(self, token: str) -> RSAPublicKey:
        return self._key


# Google's clock and this machine's differ by seconds, so a token arriving right after it was
# issued can carry an issue time still ahead of the local clock; the tolerance applies to the
# expiry the same way.
CLOCK_SKEW = timedelta(seconds=60)


class GoogleTokenVerifier:
    """The TokenVerifier port: decodes an ID token with the key its KeySource gives, and raises
    InvalidTokenError naming the check that failed."""

    def __init__(self, client_id: str, issuer: str, keys: KeySource) -> None:
        self._client_id = client_id
        self._issuers = [issuer, "accounts.google.com"] if issuer == GOOGLE_ISSUER else [issuer]
        self._keys = keys

    def verify(self, token: str) -> VerifiedToken:
        try:
            claims = jwt.decode(
                token,
                self._keys.key_for(token),
                algorithms=[ALGORITHM],
                audience=self._client_id,
                issuer=self._issuers,
                options={"require": ["exp", "iat", "sub", "aud", "iss"]},
                leeway=CLOCK_SKEW,
            )
        except jwt.ExpiredSignatureError as error:
            raise InvalidTokenError("the sign-in has expired") from error
        except jwt.InvalidAudienceError as error:
            raise InvalidTokenError("the token was issued for another application") from error
        except jwt.InvalidIssuerError as error:
            raise InvalidTokenError(f"the token was not issued by {self._issuers[0]}") from error
        except jwt.PyJWTError as error:
            raise InvalidTokenError(f"the token is not valid: {error}") from error
        return VerifiedToken(_user(claims), datetime.fromtimestamp(claims["exp"], UTC))


def _user(claims: dict[str, Any]) -> User:
    """Email and name are optional claims: Google sends them only for the scopes the sign-in
    button requests, so their absence is a legal token, not a fault."""
    return User(id=claims["sub"], email=claims.get("email"), name=claims.get("name"))

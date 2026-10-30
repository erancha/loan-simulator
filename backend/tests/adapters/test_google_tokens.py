"""Token verification against the test key pair, so no test reaches Google."""

import time
from pathlib import Path
from typing import Any

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from jwt import PyJWKClient

from auth_keys import CLIENT_ID, KID, OTHER_KEY, PRIVATE_KEY, PUBLIC_PEM, sign
from loan_agent.adapters.google_tokens import (
    CLOCK_SKEW,
    GOOGLE_ISSUER,
    GoogleTokenVerifier,
    JwksKeys,
    StaticKey,
)
from loan_agent.domain.errors import InvalidTokenError
from loan_agent.domain.models import User


def verifier(issuer: str = GOOGLE_ISSUER) -> GoogleTokenVerifier:
    return GoogleTokenVerifier(CLIENT_ID, issuer, StaticKey(PUBLIC_PEM))


def test_a_valid_token_names_the_person_and_its_expiry() -> None:
    now = int(time.time())
    verified = verifier().verify(sign(exp=now + 60))
    assert verified.user == User("1001", "dana@example.com", "Dana")
    assert int(verified.expires_at.timestamp()) == now + 60


def test_a_token_issued_seconds_ahead_of_the_local_clock_is_accepted() -> None:
    assert verifier().verify(sign(iat=int(time.time()) + 5)).user.id == "1001"


def test_a_token_issued_beyond_the_clock_tolerance_is_refused() -> None:
    issued = int(time.time()) + 2 * int(CLOCK_SKEW.total_seconds())
    with pytest.raises(InvalidTokenError, match="not valid"):
        verifier().verify(sign(iat=issued))


def test_email_and_name_are_optional() -> None:
    payload = jwt.decode(sign(), options={"verify_signature": False})
    del payload["email"], payload["name"]
    bare = jwt.encode(payload, PRIVATE_KEY, algorithm="RS256", headers={"kid": KID})
    assert verifier().verify(bare).user == User("1001", None, None)


def test_google_bare_issuer_form_is_accepted_for_google_only() -> None:
    assert verifier().verify(sign(iss="accounts.google.com")).user.id == "1001"
    with pytest.raises(InvalidTokenError, match="not issued by loan-e2e"):
        verifier("loan-e2e").verify(sign(iss="accounts.google.com"))


@pytest.mark.parametrize(
    ("claims", "reason"),
    [
        ({"exp": int(time.time()) - 2 * int(CLOCK_SKEW.total_seconds())}, "expired"),
        ({"aud": "other-client"}, "another application"),
        ({"iss": "https://evil.example"}, "not issued by"),
    ],
)
def test_wrong_claims_are_refused_with_a_reason(claims: dict[str, Any], reason: str) -> None:
    with pytest.raises(InvalidTokenError, match=reason):
        verifier().verify(sign(**claims))


def test_a_token_signed_by_another_key_is_refused() -> None:
    with pytest.raises(InvalidTokenError, match="not valid"):
        verifier().verify(sign(key=OTHER_KEY))


def test_unsigned_and_symmetric_tokens_are_refused() -> None:
    payload = jwt.decode(sign(), options={"verify_signature": False})
    for token in (
        jwt.encode(payload, None, algorithm="none"),
        jwt.encode(payload, "s" * 32, algorithm="HS256"),
        "not.a.token",
    ):
        with pytest.raises(InvalidTokenError, match="not valid"):
            verifier().verify(token)


def test_a_token_missing_a_required_claim_is_refused() -> None:
    payload = jwt.decode(sign(), options={"verify_signature": False})
    del payload["sub"]
    token = jwt.encode(payload, PRIVATE_KEY, algorithm="RS256", headers={"kid": KID})
    with pytest.raises(InvalidTokenError, match="not valid"):
        verifier().verify(token)


def test_static_key_reads_a_pem_file_and_refuses_a_non_rsa_key(tmp_path: Path) -> None:
    pem = tmp_path / "public.pem"
    pem.write_bytes(PUBLIC_PEM)
    assert GoogleTokenVerifier(CLIENT_ID, GOOGLE_ISSUER, StaticKey.from_file(pem)).verify(sign())
    ec_pem = (
        ec.generate_private_key(ec.SECP256R1())
        .public_key()
        .public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
    )
    with pytest.raises(TypeError, match="RSA"):
        StaticKey(ec_pem)


def test_jwks_keys_select_the_signing_key_by_its_id(monkeypatch: pytest.MonkeyPatch) -> None:
    def published(key: Any, kid: str) -> dict[str, Any]:
        jwk = jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key(), as_dict=True)
        return {**jwk, "kid": kid, "alg": "RS256", "use": "sig"}

    fetched: list[str] = []

    def fetch_data(self: PyJWKClient) -> dict[str, Any]:
        fetched.append(self.uri)
        return {"keys": [published(OTHER_KEY, "key-2"), published(PRIVATE_KEY, KID)]}

    monkeypatch.setattr(PyJWKClient, "fetch_data", fetch_data)
    checker = GoogleTokenVerifier(CLIENT_ID, GOOGLE_ISSUER, JwksKeys("https://keys.example/certs"))

    assert checker.verify(sign()).user.id == "1001"
    assert checker.verify(sign()).user.id == "1001"
    assert fetched == ["https://keys.example/certs"]
    unknown_kid = jwt.encode(
        jwt.decode(sign(), options={"verify_signature": False}),
        OTHER_KEY,
        algorithm="RS256",
        headers={"kid": "key-3"},
    )
    with pytest.raises(InvalidTokenError, match="not valid"):
        checker.verify(unknown_kid)

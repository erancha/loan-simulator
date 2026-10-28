"""Checks that .env.example documents exactly the keys the engine owns.

A key counts as documented when a line of the file assigns it, commented out or not
(KEY=value or # KEY=value). The one .env serves two services, so a key belongs to exactly one: the
engine owns the ENGINE_-prefixed keys (its Settings fields plus the keys only docker-compose.yml
reads) except ENGINE_URL, which the agent owns. The agent's own test checks every other key.
"""

import re
import shutil
import subprocess
from pathlib import Path

import pytest
from pydantic import ValidationError

from loan_engine.service.config import Settings

REPO = Path(__file__).resolve().parents[2]
ENV_EXAMPLE = REPO / ".env.example"
SCRIPTS = REPO / "scripts"
PREFIX = Settings.model_config["env_prefix"]

COMPOSE_ONLY_KEYS = {"ENGINE_HOST_PORT"}
AGENT_ENGINE_KEYS = {"ENGINE_URL"}

_ASSIGNMENT = re.compile(r"^(?:#\s*)?([A-Z][A-Z0-9_]*)=", re.MULTILINE)


def _documented_keys() -> set[str]:
    """The ENGINE_ keys the engine owns; the agent's keys share the file."""
    keys = set(_ASSIGNMENT.findall(ENV_EXAMPLE.read_text(encoding="utf-8")))
    return {k for k in keys if k.startswith(PREFIX) and k not in AGENT_ENGINE_KEYS}


def _settings_keys() -> set[str]:
    return {f"{PREFIX}{name.upper()}" for name in Settings.model_fields}


def test_every_settings_field_is_documented() -> None:
    missing = sorted(_settings_keys() - _documented_keys())
    assert not missing, f"Settings fields missing from .env.example: {missing}"


def test_every_compose_only_key_is_documented() -> None:
    assert COMPOSE_ONLY_KEYS <= _documented_keys()


def test_no_documented_key_is_unknown() -> None:
    unknown = sorted(_documented_keys() - _settings_keys() - COMPOSE_ONLY_KEYS)
    assert not unknown, f".env.example documents keys nothing reads: {unknown}"


def test_an_unfilled_copy_does_not_start(monkeypatch: pytest.MonkeyPatch) -> None:
    for line in ENV_EXAMPLE.read_text(encoding="utf-8").splitlines():
        if _ASSIGNMENT.match(line) and not line.startswith("#"):
            key, value = line.split("=", 1)
            monkeypatch.setenv(key, value)
    with pytest.raises(ValidationError) as error:
        Settings()  # type: ignore[call-arg]
    failed = {e["loc"][0] for e in error.value.errors()}
    assert failed == {"bearer_token", "allowed_hosts", "public_url"}


def _repo_with_init_env(tmp_path: Path, env_example: str) -> Path:
    """A repo copy holding init-env.sh, its helpers and the given .env.example text."""
    root = tmp_path / "repo"
    (root / "scripts").mkdir(parents=True)
    for script in ("common.sh", "init-env.sh"):
        shutil.copy(SCRIPTS / script, root / "scripts" / script)
    (root / ".env.example").write_text(env_example, encoding="utf-8")
    return root


def test_init_env_writes_settings_the_engine_accepts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _repo_with_init_env(tmp_path, ENV_EXAMPLE.read_text(encoding="utf-8"))
    subprocess.run([str(root / "scripts" / "init-env.sh")], check=True, capture_output=True)
    env = {}
    for line in (root / ".env").read_text(encoding="utf-8").splitlines():
        if _ASSIGNMENT.match(line):
            key, value = line.split("=", 1)
            env[key] = value
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    settings = Settings()  # type: ignore[call-arg]
    host_port = env["ENGINE_HOST_PORT"]
    assert len(settings.bearer_token.get_secret_value()) == 48
    assert settings.allowed_hosts == [
        f"engine:{settings.port}",
        f"localhost:{host_port}",
        f"127.0.0.1:{host_port}",
    ]
    assert settings.public_url == f"http://localhost:{host_port}"


def test_init_env_leaves_no_env_when_verification_fails(tmp_path: Path) -> None:
    example = ENV_EXAMPLE.read_text(encoding="utf-8")
    root = _repo_with_init_env(tmp_path, example.replace("ENGINE_PUBLIC_URL=\n", ""))
    result = subprocess.run(
        [str(root / "scripts" / "init-env.sh")], capture_output=True, text=True, check=False
    )
    assert result.returncode != 0
    assert "ENGINE_PUBLIC_URL has no value" in result.stderr
    assert sorted(p.name for p in root.iterdir()) == [".env.example", "scripts"]

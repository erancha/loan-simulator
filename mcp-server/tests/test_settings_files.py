"""Checks that the settings files document exactly the keys the engine owns.

The settings live in three files under scripts/lib/: the committed stack-params.sh, and
params.example.sh and secrets.example.sh, which init-env.sh copies to the gitignored params.sh
and secrets.sh. A key counts as documented when a line of one of them assigns it, commented out
or not (export KEY="value" or # export KEY="value"). The files serve two services, so a key
belongs to exactly one: the engine owns the ENGINE_-prefixed keys (its Settings fields plus the
keys only docker-compose.yml reads) except ENGINE_URL, which the agent owns. The agent's own test
checks every other key.
"""

import re
import shutil
import subprocess
from pathlib import Path

import pytest
from pydantic import ValidationError

from loan_engine.service.config import Settings

REPO = Path(__file__).resolve().parents[2]
LIB = REPO / "scripts" / "lib"
STACK_PARAMS = LIB / "stack-params.sh"
EXAMPLES = (LIB / "params.example.sh", LIB / "secrets.example.sh")
SCRIPTS = REPO / "scripts"
PREFIX = Settings.model_config["env_prefix"]

COMPOSE_ONLY_KEYS = {"ENGINE_HOST_PORT"}
AGENT_ENGINE_KEYS = {"ENGINE_URL"}

_ASSIGNMENT = re.compile(r"^(?:#\s*)?export ([A-Z][A-Z0-9_]*)=", re.MULTILINE)


def _documented_keys() -> set[str]:
    """The ENGINE_ keys the engine owns; the agent's keys share the files."""
    text = "".join(path.read_text(encoding="utf-8") for path in (STACK_PARAMS, *EXAMPLES))
    keys = set(_ASSIGNMENT.findall(text))
    return {k for k in keys if k.startswith(PREFIX) and k not in AGENT_ENGINE_KEYS}


def _settings_keys() -> set[str]:
    return {f"{PREFIX}{name.upper()}" for name in Settings.model_fields}


def _exported_by(*files: Path) -> dict[str, str]:
    """The variables a shell holds after sourcing the files in order, as the scripts do."""
    sources = "; ".join(f'source "{path}"' for path in files)
    output = subprocess.run(
        ["bash", "-c", f"{sources}; env -0"], check=True, capture_output=True, env={}
    ).stdout.decode()
    return dict(entry.split("=", 1) for entry in output.split("\0") if "=" in entry)


def test_every_settings_field_is_documented() -> None:
    missing = sorted(_settings_keys() - _documented_keys())
    assert not missing, f"Settings fields missing from the settings files: {missing}"


def test_every_compose_only_key_is_documented() -> None:
    assert COMPOSE_ONLY_KEYS <= _documented_keys()


def test_no_documented_key_is_unknown() -> None:
    unknown = sorted(_documented_keys() - _settings_keys() - COMPOSE_ONLY_KEYS)
    assert not unknown, f"The settings files document keys nothing reads: {unknown}"


def test_unfilled_copies_do_not_start(monkeypatch: pytest.MonkeyPatch) -> None:
    for key, value in _exported_by(STACK_PARAMS, *EXAMPLES).items():
        monkeypatch.setenv(key, value)
    with pytest.raises(ValidationError) as error:
        Settings()  # type: ignore[call-arg]
    failed = {e["loc"][0] for e in error.value.errors()}
    assert failed == {"bearer_token"}


def _repo_with_init_env(tmp_path: Path, secrets_example: str) -> Path:
    """A repo copy holding init-env.sh, its helpers, the committed settings and the examples,
    with the given text as secrets.example.sh."""
    root = tmp_path / "repo"
    (root / "scripts" / "lib").mkdir(parents=True)
    for script in ("common.sh", "init-env.sh"):
        shutil.copy(SCRIPTS / script, root / "scripts" / script)
    for path in (
        STACK_PARAMS,
        LIB / "settings-guard.sh",
        LIB / "ec2.sh",
        LIB / "aws-config.example.sh",
        EXAMPLES[0],
    ):
        shutil.copy(path, root / "scripts" / "lib" / path.name)
    (root / "scripts" / "lib" / EXAMPLES[1].name).write_text(secrets_example, encoding="utf-8")
    return root


def test_init_env_writes_settings_the_engine_accepts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _repo_with_init_env(tmp_path, EXAMPLES[1].read_text(encoding="utf-8"))
    subprocess.run([str(root / "scripts" / "init-env.sh")], check=True, capture_output=True)
    lib = root / "scripts" / "lib"
    env = _exported_by(lib / "stack-params.sh", lib / "params.sh", lib / "secrets.sh")
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


def test_init_env_keeps_existing_files_without_force(tmp_path: Path) -> None:
    root = _repo_with_init_env(tmp_path, EXAMPLES[1].read_text(encoding="utf-8"))
    script = str(root / "scripts" / "init-env.sh")
    subprocess.run([script], check=True, capture_output=True)
    secrets = root / "scripts" / "lib" / "secrets.sh"
    first = secrets.read_text(encoding="utf-8")
    subprocess.run([script], check=True, capture_output=True)
    assert secrets.read_text(encoding="utf-8") == first
    subprocess.run([script, "--force"], check=True, capture_output=True)
    assert secrets.read_text(encoding="utf-8") != first


def test_init_env_leaves_no_settings_file_when_verification_fails(tmp_path: Path) -> None:
    example = EXAMPLES[1].read_text(encoding="utf-8")
    root = _repo_with_init_env(tmp_path, example.replace('export POSTGRES_PASSWORD=""\n', ""))
    result = subprocess.run(
        [str(root / "scripts" / "init-env.sh")], capture_output=True, text=True, check=False
    )
    assert result.returncode != 0
    assert "POSTGRES_PASSWORD has no value" in result.stderr
    assert sorted(p.name for p in (root / "scripts" / "lib").iterdir()) == [
        "aws-config.example.sh",
        "ec2.sh",
        "params.example.sh",
        "secrets.example.sh",
        "settings-guard.sh",
        "stack-params.sh",
    ]

"""Times the agent's turns on one fixed scenario, repeated, with the real model, for
scripts/tools/turn-timing.sh, which checks the preconditions and documents the run.

The script starts an agent on this machine that verifies sign-ins with a key made for the run, so
it signs its own token and never reaches Google. It drives the scenario through the agent's API
as the page does, reads each turn's events from the check's event stream, and reads the model
calls each turn made from the agent's log, where every answered call writes one model_call line.

Core building blocks:
- TestAgent: the agent process, its log file and the signed-in HTTP client
- SCENARIOS and steps_of: the scenarios a run can follow, and a scenario's steps, each a request
  the page would send
- run_once: one run of the scenario on a new check, with its turns' times, calls and facts
- report: each run's turns, then each turn's median and slowest time across the runs
"""

import argparse
import json
import os
import statistics
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

PORT = 8111
BASE = f"http://127.0.0.1:{PORT}"
ISSUER = "https://turn-timing.invalid"
ACCOUNT = "turn-timing"
# A turn that has not ended after this long has hung, which the run reports instead of waiting on.
TURN_TIMEOUT_SECONDS = 300
MODEL_CALL_PREFIX = '{"event": "model_call"'
# The line httpx logs at INFO for each request the model's client sends, with the HTTP status the
# provider answered; a refused request, such as a 429 over a rate limit, is retried by the client
# inside one model call, so only these lines show it.
PROVIDER_REQUEST = "HTTP Request: POST https://api.openai.com/"


@dataclass(frozen=True)
class Step:
    """One request the page would send, named for the report. method and path take the check's
    id; body is the request's JSON; ceiling is the payment ceiling the step leaves on the check,
    which the recommendation it leads to must fit."""

    name: str
    method: str
    path: str
    body: dict[str, Any] | None
    takes_turn: bool
    ceiling: Decimal | None = None
    checks_recommendation: bool = False


@dataclass(frozen=True)
class Scenario:
    """A car loan of amount over 48 months, one offer from the offer form with its line as the
    page writes it and its tracks, then each ceiling in turn as the answer to the ceiling
    question."""

    amount: int
    offer_line: str
    tracks: list[dict[str, object]]
    ceilings: list[int]


SCENARIOS = {
    "one-track": Scenario(
        40000,
        "קיבלתי הצעה. הגוף המלווה: הראל. (1) פריים פלוס 1.5%, לא צמוד למדד. לתקופה של עד 84 "
        "חודשים, בתשלומים חודשיים שווים.",
        [{"rate_kind": "prime", "rate": "1.5", "cpi_linked": False}],
        [],
    ),
    "two-tracks": Scenario(
        39000,
        "קיבלתי הצעה. הגוף המלווה: הראל. (1) פריים פלוס 1.4%, לא צמוד למדד (2) ריבית קבועה "
        "3.4%, צמוד למדד. לתקופה של עד 84 חודשים, בתשלומים חודשיים שווים.",
        [
            {"rate_kind": "prime", "rate": "1.4", "cpi_linked": False},
            {"rate_kind": "fixed", "rate": "3.4", "cpi_linked": True},
        ],
        [1000, 2000],
    ),
}


def steps_of(scenario: Scenario) -> list[Step]:
    steps = [
        Step(
            "opening",
            "POST",
            "/opening",
            {
                "text": f"רכב: הלוואה בסך {scenario.amount:,} ₪",
                "purpose": "רכב",
                "amount": str(scenario.amount),
            },
            takes_turn=True,
        ),
        Step("term", "PUT", "/term", {"term_months": 48}, takes_turn=False),
        Step(
            "term confirmed",
            "POST",
            "/term-confirmation",
            {"text": "אישור: 48 חודשים"},
            takes_turn=True,
        ),
        Step(
            f"offer, {len(scenario.tracks)} track(s)",
            "POST",
            "/messages",
            {
                "offer": {
                    "line": scenario.offer_line,
                    "lender": "הראל",
                    "tracks": scenario.tracks,
                    "max_term_months": 84,
                }
            },
            takes_turn=True,
            checks_recommendation=True,
        ),
    ]
    for ceiling in scenario.ceilings:
        steps.append(
            Step(
                f"ceiling {ceiling:,}",
                "POST",
                "/messages",
                {"text": f"מה ההחזר החודשי הגבוה ביותר שנוח לך? {ceiling:,} ₪"},
                takes_turn=True,
                ceiling=Decimal(ceiling),
                checks_recommendation=True,
            )
        )
    return steps


@dataclass(frozen=True)
class Call:
    kind: str
    seconds: float
    reasoning_tokens: int
    cost: float


@dataclass
class Turn:
    name: str
    seconds: float
    calls: list[Call]
    refused: list[str]
    problems: list[str] = field(default_factory=list)


class TestAgent:
    """The agent process on 127.0.0.1:8111, started from the repo root so it reads the stack's
    settings files, with sign-ins verified by a key made for this run and no message cap that a
    few runs could reach."""

    def __init__(self, workdir: Path) -> None:
        private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        public_file = workdir / "public.pem"
        public_file.write_bytes(
            private_key.public_key().public_bytes(
                serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
            )
        )
        self._private_key = private_key
        self.log_file = workdir / "agent.log"
        env = {
            **os.environ,
            "AUTH_PUBLIC_KEY_FILE": str(public_file),
            "AUTH_ISSUER": ISSUER,
            "AGENT_TURN_LIMIT": "1000",
            "AGENT_LOG_LEVEL": "INFO",
            "AGENT_FRONTEND_DIST": "",
        }
        with self.log_file.open("w") as log:
            self._process = subprocess.Popen(
                [
                    str(Path(sys.executable).with_name("uvicorn")),
                    "loan_agent.platform.app:create_app",
                    "--factory",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(PORT),
                ],
                env=env,
                stdout=log,
                stderr=subprocess.STDOUT,
            )
        self.client = httpx.Client(base_url=BASE, timeout=30)

    def wait_ready(self) -> None:
        for _ in range(60):
            if self._process.poll() is not None:
                raise SystemExit(f"the test agent stopped while starting; see {self.log_file}")
            try:
                if self.client.get("/ready").status_code == 200:
                    return
            except httpx.TransportError:
                pass
            time.sleep(1)
        raise SystemExit(f"the test agent did not answer /ready in 60 s; see {self.log_file}")

    def sign_in(self) -> None:
        now = int(time.time())
        token = jwt.encode(
            {
                "iss": ISSUER,
                "aud": os.environ["GOOGLE_CLIENT_ID"],
                "sub": ACCOUNT,
                "email": f"{ACCOUNT}@example.invalid",
                "iat": now,
                "exp": now + 3600,
            },
            self._private_key,
            algorithm="RS256",
        )
        response = self.client.post("/api/auth/session", json={"credential": token})
        response.raise_for_status()

    def model_calls_after(self, offset: int) -> tuple[list[Call], list[str], int]:
        """The model_call lines the agent logged past offset bytes, the HTTP status of each
        request to the provider that it refused, and the new offset."""
        with self.log_file.open("rb") as log:
            log.seek(offset)
            data = log.read()
        calls = []
        refused = []
        requests = 0
        decoder = json.JSONDecoder()
        for line in data.decode().splitlines():
            if PROVIDER_REQUEST in line:
                requests += 1
                if '200 OK"' not in line:
                    refused.append(line[line.rindex('"HTTP/') :].strip('"'))
            start = line.find(MODEL_CALL_PREFIX)
            if start != -1:
                call, _ = decoder.raw_decode(line, start)
                calls.append(
                    Call(call["kind"], call["seconds"], call["reasoning_tokens"], call["cost"])
                )
        # Every answered call sent at least one request, so fewer request lines than calls means
        # the log no longer shows them, and a refusal would go unseen.
        if requests < len(calls):
            raise SystemExit(
                f"{len(calls)} model calls but {requests} provider request lines in "
                f"{self.log_file}; the refusal count cannot be trusted"
            )
        return calls, refused, offset + len(data)

    def stop(self) -> None:
        self.client.close()
        self._process.terminate()
        self._process.wait(timeout=30)


def _wait_for_turn(client: httpx.Client, check_id: str, after_seq: int) -> tuple[int, float]:
    """Reads the check's events after after_seq until the turn that follows ends; returns the
    last event's seq and the seconds from the turn's start to its end, by the events' own
    times."""
    started = None
    headers = {"Last-Event-ID": str(after_seq)}
    deadline = time.monotonic() + TURN_TIMEOUT_SECONDS
    with client.stream(
        "GET", f"/api/checks/{check_id}/events", headers=headers, timeout=TURN_TIMEOUT_SECONDS
    ) as stream:
        seq = after_seq
        event_type = None
        for line in stream.iter_lines():
            if time.monotonic() > deadline:
                raise SystemExit(f"a turn of check {check_id} ran past {TURN_TIMEOUT_SECONDS} s")
            if line.startswith("id: "):
                seq = int(line[4:])
            elif line.startswith("event: "):
                event_type = line[7:]
            elif line.startswith("data: ") and event_type == "turn.status":
                data = json.loads(line[6:])
                at = _seconds_of(data["at"])
                if data["status"] == "running":
                    started = at
                elif started is not None:
                    return seq, at - started
    raise SystemExit(f"the event stream of check {check_id} closed before its turn ended")


def _seconds_of(iso: str) -> float:
    return datetime.fromisoformat(iso).timestamp()


def _recommendation_problems(
    view: dict[str, Any], tracks: int, ceiling: Decimal | None
) -> list[str]:
    """The facts a recommendation must hold: one option saved per track, the card made for the
    check's ceiling, and the preferred one the cheapest in total among those whose highest
    payment, in the worst historical window when the payment moves, fits the ceiling."""
    options = view["options"]
    if len(options) != tracks:
        return [f"{len(options)} options saved, not {tracks}"]
    recommendation = view["recommendation"]
    if recommendation is None:
        return ["no recommendation"]
    made_for = recommendation["payment_ceiling"]
    if (None if made_for is None else Decimal(made_for)) != ceiling:
        return [f"card not updated: made for ceiling {made_for or 'none'}, not {ceiling or 'none'}"]

    def risk(option: dict[str, Any]) -> Decimal:
        figures = option["figures"]
        worst = figures["worst_peak_payment"]
        return Decimal(worst if worst is not None else figures["peak_payment"])

    fitting = [o for o in options if ceiling is None or risk(o) <= ceiling]
    if not fitting:
        return [f"no option fits {ceiling}; the scenario expects one"]
    cheapest = min(fitting, key=lambda o: Decimal(o["figures"]["total_paid"]))
    if recommendation["preferred_option_id"] != cheapest["id"]:
        chosen = next(o for o in options if o["id"] == recommendation["preferred_option_id"])
        return [
            (
                f"prefers {_track(chosen)}, expected {_track(cheapest)}"
                f" (ceiling {ceiling if ceiling is not None else 'none'})"
            )
        ]
    return []


def _track(option: dict[str, Any]) -> str:
    (track,) = option["loan"]["tracks"]
    if track["rate_kind"] == "prime":
        return f"prime + {track['prime_spread']}"
    linked = "linked" if track["cpi_linked"] else "unlinked"
    return f"fixed {track['annual_rate']} {linked}"


def run_once(agent: TestAgent, scenario: Scenario, log_offset: int) -> tuple[list[Turn], int]:
    client = agent.client
    check_id = client.post("/api/checks").raise_for_status().json()["id"]
    turns = []
    try:
        seq = 0
        for step in steps_of(scenario):
            response = client.request(
                step.method, f"/api/checks/{check_id}{step.path}", json=step.body
            )
            if response.status_code >= 400:
                raise SystemExit(f"{step.name}: {response.status_code} {response.text}")
            if not step.takes_turn:
                continue
            seq, seconds = _wait_for_turn(client, check_id, seq)
            calls, refused, log_offset = agent.model_calls_after(log_offset)
            turn = Turn(step.name, seconds, calls, refused)
            if step.checks_recommendation:
                view = client.get(f"/api/checks/{check_id}").raise_for_status().json()
                turn.problems = _recommendation_problems(view, len(scenario.tracks), step.ceiling)
            turns.append(turn)
    finally:
        client.delete(f"/api/checks/{check_id}")
    return turns, log_offset


def _turn_line(turn: Turn) -> str:
    calls = ", ".join(f"{c.kind} {c.seconds:.1f}s/{c.reasoning_tokens}" for c in turn.calls)
    facts = "ok" if not turn.problems else "WRONG: " + "; ".join(turn.problems)
    refused = f"  REFUSED by the provider: {', '.join(turn.refused)}" if turn.refused else ""
    return (
        f"  {turn.name:<17}{turn.seconds:>6.1f} s  [{calls or 'no model call'}]  {facts}{refused}"
    )


def report(scenario: Scenario, runs: list[list[Turn]]) -> int:
    """Prints the summary and returns the number of turns whose facts were wrong."""
    print("\nsummary (seconds per turn across the runs)")
    print(f"  {'turn':<17}{'median':>8}{'slowest':>9}{'calls':>7}{'reasoning':>11}")
    for index, step in enumerate(s for s in steps_of(scenario) if s.takes_turn):
        turns = [run[index] for run in runs]
        seconds = [t.seconds for t in turns]
        calls = statistics.median(len(t.calls) for t in turns)
        reasoning = statistics.median(sum(c.reasoning_tokens for c in t.calls) for t in turns)
        print(
            f"  {step.name:<17}{statistics.median(seconds):>8.1f}{max(seconds):>9.1f}"
            f"{calls:>7g}{reasoning:>11g}"
        )
    whole = [sum(t.seconds for t in run) for run in runs]
    cost = sum(c.cost for run in runs for t in run for c in t.calls)
    wrong = sum(1 for run in runs for t in run if t.problems)
    refused = sum(len(t.refused) for run in runs for t in run)
    print(f"  {'whole run':<17}{statistics.median(whole):>8.1f}{max(whole):>9.1f}")
    print(
        f"\nmodel cost of the {len(runs)} runs: ${cost:.4f}; turns with wrong facts: {wrong}; "
        f"requests the provider refused: {refused}"
    )
    return wrong


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, required=True)
    parser.add_argument("--scenario", choices=SCENARIOS, required=True)
    parser.add_argument("--pause", type=int, required=True)
    arguments = parser.parse_args(argv)
    runs_wanted = arguments.runs
    scenario = SCENARIOS[arguments.scenario]
    with tempfile.TemporaryDirectory(prefix="turn-timing-") as workdir:
        agent = TestAgent(Path(workdir))
        try:
            agent.wait_ready()
            agent.sign_in()
            _, _, log_offset = agent.model_calls_after(0)
            runs = []
            for number in range(1, runs_wanted + 1):
                if number > 1:
                    time.sleep(arguments.pause)
                turns, log_offset = run_once(agent, scenario, log_offset)
                print(f"run {number}: {sum(t.seconds for t in turns):.1f} s")
                for turn in turns:
                    print(_turn_line(turn))
                runs.append(turns)
                sys.stdout.flush()
        finally:
            agent.stop()
    return 1 if report(scenario, runs) else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

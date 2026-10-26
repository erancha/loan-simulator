"""The loan-engine MCP server: tools, rate resources, bearer auth and the HTTP app.

- build_server(): the MCPServer with the tools and the rates:// resources
- build_app(): the Streamable HTTP app at /mcp with the host allow-list
"""

from collections.abc import Callable
from datetime import date
from decimal import Decimal
from typing import Any

from mcp.server import MCPServer
from mcp.server.auth.settings import AuthSettings
from mcp.server.transport_security import TransportSecuritySettings
from pydantic import AnyHttpUrl, BaseModel, ConfigDict
from starlette.applications import Starlette

from loan_engine.domain.assumptions import PRIME_MARGIN
from loan_engine.domain.history import MarketHistory
from loan_engine.service.auth import StaticTokenVerifier
from loan_engine.service.config import Settings
from loan_engine.service.tools import register_tools

_JSON = "application/json"


class _Resource(BaseModel):
    model_config = ConfigDict(frozen=True)


class BoiMonth(_Resource):
    month: date
    boi_rate: Decimal


class BoiHistory(_Resource):
    as_of: date
    months: list[BoiMonth]


class CpiMonth(_Resource):
    month: date
    inflation: Decimal


class CpiHistory(_Resource):
    as_of: date
    months: list[CpiMonth]


class CurrentRates(_Resource):
    boi_rate: Decimal
    prime: Decimal
    rate_as_of: date
    cpi_as_of: date
    consumer_rate: Decimal
    consumer_rate_month: date


def build_server(
    settings: Settings,
    history_provider: Callable[[], MarketHistory],
) -> MCPServer[Any]:
    server: MCPServer[Any] = MCPServer(
        "loan-engine",
        token_verifier=StaticTokenVerifier(settings.bearer_token),
        auth=AuthSettings(
            issuer_url=AnyHttpUrl(settings.public_url),
            resource_server_url=AnyHttpUrl(f"{settings.public_url}/mcp"),
            # The static token names no audience to check against resource_server_url.
            validate_token_resource=False,
        ),
    )
    register_tools(server, history_provider)

    @server.resource(
        "rates://boi/history",
        mime_type=_JSON,
        description="Bank of Israel rate in annual percent in effect on the first of each month, "
        "and the date of the latest daily value",
    )
    def boi_history() -> str:
        market = history_provider()
        return BoiHistory(
            as_of=market.rate_as_of,
            months=[BoiMonth(month=m, boi_rate=r) for m, r in zip(market.months, market.boi_rate)],
        ).model_dump_json()

    @server.resource(
        "rates://cpi/history",
        mime_type=_JSON,
        description="Monthly change of the consumer price index as a fraction, and the month of "
        "the latest index",
    )
    def cpi_history() -> str:
        market = history_provider()
        return CpiHistory(
            as_of=market.cpi_as_of,
            months=[
                CpiMonth(month=m, inflation=i)
                for m, i in zip(market.months, market.monthly_inflation)
            ],
        ).model_dump_json()

    @server.resource(
        "rates://current",
        mime_type=_JSON,
        description="Today's Bank of Israel rate and prime in annual percent, and the latest "
        "average rate on new household consumer loans with its month",
    )
    def current_rates() -> str:
        market = history_provider()
        return CurrentRates(
            boi_rate=market.current_boi_rate,
            prime=market.current_boi_rate + PRIME_MARGIN,
            rate_as_of=market.rate_as_of,
            cpi_as_of=market.cpi_as_of,
            consumer_rate=market.consumer_rate,
            consumer_rate_month=market.consumer_rate_month,
        ).model_dump_json()

    return server


def build_app(server: MCPServer[Any], settings: Settings) -> Starlette:
    return server.streamable_http_app(
        stateless_http=True,
        json_response=True,
        transport_security=TransportSecuritySettings(allowed_hosts=settings.allowed_hosts),
    )

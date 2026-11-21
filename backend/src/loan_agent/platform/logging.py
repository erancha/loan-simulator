"""Process logging: structlog and standard-library records rendered through one stderr handler.

Core building blocks:
- configure_logging: the root level, uvicorn's loggers routed to the shared handler, and plain
  tracebacks
- the model_call logger kept at INFO, so each model call's line reaches the log whatever level
  the process runs at
- ProbeAccessDemotion: drops /health and /ready access lines answered below 400 to DEBUG so
  frequent orchestrator probes do not flood the log
"""

import logging
import sys

import structlog

from loan_agent.adapters.model_costs import MODEL_CALL_LOGGER

PROBE_PATHS = frozenset({"/health", "/ready"})
UVICORN_LOGGERS = ("uvicorn", "uvicorn.error", "uvicorn.access")
ACCESS_LOGGER = "uvicorn.access"

_SHARED_PROCESSORS: list[structlog.typing.Processor] = [
    structlog.contextvars.merge_contextvars,
    structlog.stdlib.add_logger_name,
    structlog.stdlib.add_log_level,
    structlog.processors.TimeStamper(fmt="iso"),
]


class ProbeAccessDemotion(logging.Filter):
    """Uvicorn access records carry (client, method, path, http_version, status) as args."""

    def filter(self, record: logging.LogRecord) -> bool:
        assert isinstance(record.args, tuple), "uvicorn access records use positional args"
        path, status = record.args[2], record.args[4]
        assert isinstance(status, int), f"unexpected access status {status!r}"
        if path not in PROBE_PATHS or status >= 400:
            return True
        record.levelno, record.levelname = logging.DEBUG, logging.getLevelName(logging.DEBUG)
        return logging.getLogger(record.name).isEnabledFor(logging.DEBUG)


def configure_logging(level: str) -> None:
    """level: a standard level name; tracebacks render as plain text, one block per exception,
    since structlog's default rich rendering costs seconds per exception."""
    structlog.configure(
        processors=[*_SHARED_PROCESSORS, structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        # Uncached, so a later reconfiguration (tests, a second app) reaches module-level loggers.
        cache_logger_on_first_use=False,
    )
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(
        structlog.stdlib.ProcessorFormatter(
            foreign_pre_chain=_SHARED_PROCESSORS,
            processors=[
                structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                structlog.dev.ConsoleRenderer(
                    colors=False, exception_formatter=structlog.dev.plain_traceback
                ),
            ],
        )
    )
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)
    # Uvicorn installs its own handlers and levels; reset them so its lines take the root level
    # and handler.
    for name in UVICORN_LOGGERS:
        logger = logging.getLogger(name)
        logger.handlers.clear()
        logger.propagate = True
        logger.setLevel(logging.NOTSET)
    logging.getLogger(MODEL_CALL_LOGGER).setLevel(logging.INFO)
    access = logging.getLogger(ACCESS_LOGGER)
    access.filters[:] = [f for f in access.filters if not isinstance(f, ProbeAccessDemotion)]
    access.addFilter(ProbeAccessDemotion())

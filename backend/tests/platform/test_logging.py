"""The process log keeps each model call's line whatever level it runs at."""

import logging

from loan_agent.adapters.model_costs import MODEL_CALL_LOGGER
from loan_agent.platform.logging import configure_logging


def test_model_call_lines_pass_a_warning_level_log() -> None:
    configure_logging("WARNING")

    assert logging.getLogger(MODEL_CALL_LOGGER).isEnabledFor(logging.INFO)
    assert not logging.getLogger("loan_agent").isEnabledFor(logging.INFO)

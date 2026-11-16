"""The ranges of a loan the engine prices; a principal, term or rate outside them is refused."""

from loan_engine.domain.assumptions import PRIME_MARGIN

MIN_PRINCIPAL = 10000
MAX_PRINCIPAL = 10000000
MIN_TERM = 6
MAX_TERM = 84
MIN_ANNUAL_RATE = 0
MAX_ANNUAL_RATE = 30
# Prime is the Bank of Israel rate plus PRIME_MARGIN, so a margin under prime goes no lower than
# the Bank of Israel rate itself.
MIN_PRIME_SPREAD = -PRIME_MARGIN
MAX_PRIME_SPREAD = 20

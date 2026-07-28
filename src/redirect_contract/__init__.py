"""redirect-contract: assert that old URLs still redirect where you intended."""

from redirect_contract.checker import check
from redirect_contract.exceptions import ConfigError, InterpolationError, RecordError
from redirect_contract.models import Config, Defaults, ResolvedRule, Rule
from redirect_contract.record import record
from redirect_contract.results import CheckReport, FailureReason, Hop, RuleResult

__version__ = "0.1.0"

__all__ = [
    "CheckReport",
    "Config",
    "ConfigError",
    "Defaults",
    "FailureReason",
    "Hop",
    "InterpolationError",
    "RecordError",
    "ResolvedRule",
    "Rule",
    "RuleResult",
    "check",
    "record",
]

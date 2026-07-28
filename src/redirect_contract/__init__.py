"""redirect-contract: assert that old URLs still redirect where you intended."""

from redirect_contract.exceptions import ConfigError, InterpolationError
from redirect_contract.models import Config, Defaults, ResolvedRule, Rule

__version__ = "0.1.0"

__all__ = [
    "Config",
    "ConfigError",
    "Defaults",
    "InterpolationError",
    "ResolvedRule",
    "Rule",
]

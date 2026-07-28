"""Result types produced by the checker."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from redirect_contract.models import ResolvedRule


class FailureReason(str, Enum):
    """Why a rule failed. None of these apply when RuleResult.passed is True."""

    WRONG_STATUS = "wrong_status"
    WRONG_FINAL_URL = "wrong_final_url"
    TOO_MANY_HOPS = "too_many_hops"
    LOOP = "loop"
    ERROR_STATUS = "error_status"
    DOWNGRADE = "downgrade"
    TIMEOUT = "timeout"
    CONNECTION_ERROR = "connection_error"


@dataclass(frozen=True)
class Hop:
    """One response received while following a redirect chain."""

    url: str
    status: int


@dataclass(frozen=True)
class RuleResult:
    """The outcome of checking a single (resolved) rule."""

    rule: ResolvedRule
    passed: bool
    chain: list[Hop]
    final_url: str | None
    failure_reason: FailureReason | None
    message: str | None = None


@dataclass(frozen=True)
class CheckReport:
    """The outcome of checking every rule in a Config."""

    results: list[RuleResult]

    @property
    def passed(self) -> bool:
        return all(result.passed for result in self.results)

    @property
    def exit_code(self) -> int:
        return 0 if self.passed else 1

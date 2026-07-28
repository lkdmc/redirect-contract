"""Pydantic v2 models for the redirects.yml contract."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from redirect_contract.exceptions import ConfigError
from redirect_contract.interpolate import interpolate


def _is_absolute_http_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in ("http", "https") and bool(parsed.netloc)


class Defaults(BaseModel):
    """Fallback values applied to every rule unless overridden."""

    model_config = ConfigDict(extra="forbid")

    status: int = 301
    max_hops: int = 5
    timeout: float = 10.0
    headers: dict[str, str] = Field(default_factory=dict)
    basic_auth: str | None = None

    @field_validator("status")
    @classmethod
    def _status_is_redirect(cls, v: int) -> int:
        if not (300 <= v < 400):
            raise ValueError("must be a 3xx redirect status code")
        return v

    @field_validator("max_hops")
    @classmethod
    def _max_hops_positive(cls, v: int) -> int:
        if v < 1:
            raise ValueError("must be >= 1")
        return v

    @field_validator("timeout")
    @classmethod
    def _timeout_positive(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("must be > 0")
        return v

    @field_validator("basic_auth")
    @classmethod
    def _basic_auth_format(cls, v: str | None) -> str | None:
        if v is not None and ":" not in v:
            raise ValueError("must be in 'user:pass' format")
        return v


class Rule(BaseModel):
    """A single redirect assertion: ``from`` must resolve to ``to``."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    from_: str = Field(alias="from")
    to: str
    status: int | None = None
    max_hops: int | None = None
    name: str | None = None
    headers: dict[str, str] = Field(default_factory=dict)

    @field_validator("from_")
    @classmethod
    def _from_is_path(cls, v: str) -> str:
        if not v.startswith("/"):
            raise ValueError("must start with '/' (paths are relative to base_url)")
        return v

    @field_validator("to")
    @classmethod
    def _to_is_path_or_url(cls, v: str) -> str:
        if not v:
            raise ValueError("must not be empty")
        if not (v.startswith("/") or _is_absolute_http_url(v)):
            raise ValueError("must be an absolute path (starting with '/') or a full http(s) URL")
        return v

    @field_validator("status")
    @classmethod
    def _status_is_redirect(cls, v: int | None) -> int | None:
        if v is not None and not (300 <= v < 400):
            raise ValueError("must be a 3xx redirect status code")
        return v

    @field_validator("max_hops")
    @classmethod
    def _max_hops_positive(cls, v: int | None) -> int | None:
        if v is not None and v < 1:
            raise ValueError("must be >= 1")
        return v


@dataclass(frozen=True)
class ResolvedRule:
    """A Rule with defaults merged in, ready for the checker to execute."""

    from_: str
    to: str
    status: int
    max_hops: int
    timeout: float
    headers: dict[str, str]
    basic_auth: str | None
    name: str | None


def resolve_rule(rule: Rule, defaults: Defaults) -> ResolvedRule:
    """Merge a Rule's overrides over the Defaults into a fully-populated ResolvedRule."""
    return ResolvedRule(
        from_=rule.from_,
        to=rule.to,
        status=rule.status if rule.status is not None else defaults.status,
        max_hops=rule.max_hops if rule.max_hops is not None else defaults.max_hops,
        timeout=defaults.timeout,
        headers={**defaults.headers, **rule.headers},
        basic_auth=defaults.basic_auth,
        name=rule.name,
    )


class Config(BaseModel):
    """A full redirects.yml contract: base_url, defaults, and a list of rules."""

    model_config = ConfigDict(extra="forbid")

    version: Literal[1]
    base_url: str
    defaults: Defaults = Field(default_factory=Defaults)
    rules: list[Rule]

    @field_validator("base_url")
    @classmethod
    def _base_url_is_absolute(cls, v: str) -> str:
        if not _is_absolute_http_url(v):
            raise ValueError("must be an absolute http(s) URL")
        return v.rstrip("/")

    @field_validator("rules")
    @classmethod
    def _rules_nonempty(cls, v: list[Rule]) -> list[Rule]:
        if not v:
            raise ValueError("must contain at least one rule")
        return v

    @classmethod
    def from_yaml_str(cls, text: str, *, env: Mapping[str, str] | None = None) -> Config:
        """Parse a redirects.yml document from a string.

        Raises ConfigError (with a message naming the offending rule/field,
        never a raw traceback) on invalid YAML, missing env vars, or failed
        validation.
        """
        try:
            raw = yaml.safe_load(text)
        except yaml.YAMLError as exc:
            raise ConfigError(f"Invalid YAML: {exc}") from exc

        if not isinstance(raw, dict):
            raise ConfigError("Config must be a YAML mapping at the top level")

        interpolated = interpolate(raw, env=env if env is not None else os.environ)

        try:
            return cls.model_validate(interpolated)
        except ValidationError as exc:
            raise ConfigError(_format_validation_error(exc)) from exc

    @classmethod
    def from_yaml_file(cls, path: str | Path, *, env: Mapping[str, str] | None = None) -> Config:
        """Parse a redirects.yml document from a file path. See from_yaml_str."""
        text = Path(path).read_text(encoding="utf-8")
        return cls.from_yaml_str(text, env=env)

    def resolved_rules(self) -> list[ResolvedRule]:
        """Return every rule with Defaults merged in."""
        return [resolve_rule(rule, self.defaults) for rule in self.rules]

    def to_yaml(self) -> str:
        """Serialize back to a redirects.yml document."""
        data = self.model_dump(mode="json", by_alias=True, exclude_defaults=True)
        data.setdefault("version", self.version)
        return yaml.safe_dump(data, sort_keys=False, allow_unicode=True)


def _format_validation_error(exc: ValidationError) -> str:
    lines = ["Invalid redirects.yml configuration:"]
    for error in exc.errors():
        loc = ".".join(str(part) for part in error["loc"])
        lines.append(f"  - {loc}: {error['msg']}")
    return "\n".join(lines)

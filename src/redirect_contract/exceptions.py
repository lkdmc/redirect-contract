"""Exceptions raised by redirect_contract."""

from __future__ import annotations


class ConfigError(Exception):
    """A redirects.yml file is malformed, invalid, or cannot be read.

    Raised in place of raw YAML/pydantic exceptions so the CLI can print a
    single, friendly, non-traceback message and exit with code 2.
    """


class InterpolationError(ConfigError):
    """A ``${VAR}`` placeholder referenced an environment variable that is not set."""

    def __init__(self, var_name: str, path: str) -> None:
        self.var_name = var_name
        self.path = path
        super().__init__(
            f"{path}: environment variable '{var_name}' is not set "
            f"(referenced as '${{{var_name}}}')"
        )

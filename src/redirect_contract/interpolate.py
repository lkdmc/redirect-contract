"""``${VAR}`` environment variable interpolation for raw config data.

Applied to the raw YAML data (dicts/lists/strings) before pydantic parsing, so
any string field in the config may reference an environment variable.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from redirect_contract.exceptions import InterpolationError

_PLACEHOLDER = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


def interpolate(data: Any, *, env: Mapping[str, str], path: str = "config") -> Any:
    """Recursively substitute ``${VAR}`` placeholders in strings within ``data``.

    Raises InterpolationError naming the offending variable and its location
    (e.g. ``config.rules[2].headers.Authorization``) if a referenced variable
    is not present in ``env``.
    """
    if isinstance(data, str):
        return _interpolate_str(data, env=env, path=path)
    if isinstance(data, dict):
        return {
            key: interpolate(value, env=env, path=f"{path}.{key}") for key, value in data.items()
        }
    if isinstance(data, list):
        return [interpolate(item, env=env, path=f"{path}[{i}]") for i, item in enumerate(data)]
    return data


def _interpolate_str(value: str, *, env: Mapping[str, str], path: str) -> str:
    def replace(match: re.Match[str]) -> str:
        var_name = match.group(1)
        if var_name not in env:
            raise InterpolationError(var_name, path)
        return env[var_name]

    return _PLACEHOLDER.sub(replace, value)

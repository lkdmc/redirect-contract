import pytest

from redirect_contract.exceptions import InterpolationError
from redirect_contract.interpolate import interpolate


def test_substitutes_single_variable() -> None:
    result = interpolate("https://${HOST}/path", env={"HOST": "example.org"})
    assert result == "https://example.org/path"


def test_substitutes_multiple_variables_in_one_string() -> None:
    result = interpolate("${USER}:${PASS}", env={"USER": "alice", "PASS": "secret"})
    assert result == "alice:secret"


def test_missing_variable_raises_interpolation_error() -> None:
    with pytest.raises(InterpolationError) as exc_info:
        interpolate("${MISSING}", env={}, path="config.base_url")
    assert exc_info.value.var_name == "MISSING"
    assert "config.base_url" in str(exc_info.value)
    assert "MISSING" in str(exc_info.value)


def test_recurses_into_dicts_and_lists() -> None:
    data = {
        "base_url": "https://${HOST}",
        "rules": [
            {"from": "/a", "headers": {"Authorization": "Bearer ${TOKEN}"}},
        ],
    }
    result = interpolate(data, env={"HOST": "example.org", "TOKEN": "abc123"})
    assert result == {
        "base_url": "https://example.org",
        "rules": [
            {"from": "/a", "headers": {"Authorization": "Bearer abc123"}},
        ],
    }


def test_missing_variable_nested_reports_path() -> None:
    data = {"rules": [{"to": "${MISSING}"}]}
    with pytest.raises(InterpolationError) as exc_info:
        interpolate(data, env={})
    assert "rules[0].to" in exc_info.value.path


def test_non_string_values_are_left_untouched() -> None:
    data = {"status": 301, "enabled": True, "note": None, "hops": [1, 2, 3]}
    assert interpolate(data, env={}) == data


def test_string_without_placeholders_is_unchanged() -> None:
    assert interpolate("/plain/path", env={}) == "/plain/path"

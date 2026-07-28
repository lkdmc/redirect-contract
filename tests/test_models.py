import pytest

from redirect_contract.exceptions import ConfigError
from redirect_contract.models import Config, Defaults, Rule, resolve_rule

MINIMAL = """\
version: 1
base_url: https://example.org
rules:
  - from: /old
    to: /new
"""


def test_parses_minimal_valid_config() -> None:
    config = Config.from_yaml_str(MINIMAL)
    assert config.base_url == "https://example.org"
    assert len(config.rules) == 1
    assert config.rules[0].from_ == "/old"
    assert config.rules[0].to == "/new"
    # library-level defaults apply when the `defaults:` block is omitted
    assert config.defaults.status == 301
    assert config.defaults.max_hops == 5


def test_parses_full_example_from_readme() -> None:
    text = """\
version: 1
base_url: https://example.org
defaults:
  status: 301
  max_hops: 2
rules:
  - from: /2024/files
    to: /2024-files/
  - from: /old-page
    to: https://other.example.org/new-page
    status: 302
  - from: /
    to: /2026/
"""
    config = Config.from_yaml_str(text)
    assert config.defaults.max_hops == 2
    assert config.rules[1].to == "https://other.example.org/new-page"
    assert config.rules[1].status == 302


def test_base_url_trailing_slash_is_normalized() -> None:
    text = MINIMAL.replace("https://example.org", "https://example.org/")
    config = Config.from_yaml_str(text)
    assert config.base_url == "https://example.org"


@pytest.mark.parametrize(
    "bad_base_url",
    ["ftp://example.org", "example.org", "not a url", ""],
)
def test_base_url_must_be_absolute_http_url(bad_base_url: str) -> None:
    text = MINIMAL.replace("https://example.org", bad_base_url or '""')
    with pytest.raises(ConfigError) as exc_info:
        Config.from_yaml_str(text)
    assert "base_url" in str(exc_info.value)


def test_version_must_be_1() -> None:
    text = MINIMAL.replace("version: 1", "version: 2")
    with pytest.raises(ConfigError) as exc_info:
        Config.from_yaml_str(text)
    assert "version" in str(exc_info.value)


def test_rules_must_be_nonempty() -> None:
    text = """\
version: 1
base_url: https://example.org
rules: []
"""
    with pytest.raises(ConfigError) as exc_info:
        Config.from_yaml_str(text)
    assert "rules" in str(exc_info.value)


def test_from_must_start_with_slash() -> None:
    text = MINIMAL.replace("from: /old", "from: old")
    with pytest.raises(ConfigError) as exc_info:
        Config.from_yaml_str(text)
    message = str(exc_info.value)
    assert "rules.0.from" in message or "rules[0].from" in message or "from" in message


def test_to_rejects_bare_string_that_is_not_path_or_url() -> None:
    text = MINIMAL.replace("to: /new", "to: not-a-path-or-url")
    with pytest.raises(ConfigError) as exc_info:
        Config.from_yaml_str(text)
    assert "to" in str(exc_info.value)


def test_to_accepts_absolute_url() -> None:
    text = MINIMAL.replace("to: /new", "to: https://other.example.org/new")
    config = Config.from_yaml_str(text)
    assert config.rules[0].to == "https://other.example.org/new"


def test_unknown_top_level_field_is_rejected() -> None:
    text = MINIMAL + "extra_field: oops\n"
    with pytest.raises(ConfigError) as exc_info:
        Config.from_yaml_str(text)
    assert "extra_field" in str(exc_info.value)


def test_unknown_rule_field_is_rejected() -> None:
    text = MINIMAL.replace("to: /new", "to: /new\n    typo_field: oops")
    with pytest.raises(ConfigError) as exc_info:
        Config.from_yaml_str(text)
    assert "typo_field" in str(exc_info.value)


def test_defaults_status_must_be_3xx() -> None:
    text = """\
version: 1
base_url: https://example.org
defaults:
  status: 200
rules:
  - from: /old
    to: /new
"""
    with pytest.raises(ConfigError) as exc_info:
        Config.from_yaml_str(text)
    assert "status" in str(exc_info.value)


def test_defaults_max_hops_must_be_positive() -> None:
    text = """\
version: 1
base_url: https://example.org
defaults:
  max_hops: 0
rules:
  - from: /old
    to: /new
"""
    with pytest.raises(ConfigError) as exc_info:
        Config.from_yaml_str(text)
    assert "max_hops" in str(exc_info.value)


def test_basic_auth_must_contain_colon() -> None:
    text = """\
version: 1
base_url: https://example.org
defaults:
  basic_auth: no-colon-here
rules:
  - from: /old
    to: /new
"""
    with pytest.raises(ConfigError) as exc_info:
        Config.from_yaml_str(text)
    assert "basic_auth" in str(exc_info.value)


def test_malformed_yaml_raises_config_error_not_traceback() -> None:
    text = "version: 1\nbase_url: [unclosed\n"
    with pytest.raises(ConfigError) as exc_info:
        Config.from_yaml_str(text)
    assert "Invalid YAML" in str(exc_info.value)


def test_top_level_must_be_a_mapping() -> None:
    with pytest.raises(ConfigError):
        Config.from_yaml_str("- just\n- a\n- list\n")


def test_env_var_interpolation_in_base_url() -> None:
    text = """\
version: 1
base_url: https://${HOST}
rules:
  - from: /old
    to: /new
"""
    config = Config.from_yaml_str(text, env={"HOST": "example.org"})
    assert config.base_url == "https://example.org"


def test_env_var_interpolation_in_headers() -> None:
    text = """\
version: 1
base_url: https://example.org
defaults:
  headers:
    Authorization: "Bearer ${TOKEN}"
rules:
  - from: /old
    to: /new
"""
    config = Config.from_yaml_str(text, env={"TOKEN": "abc123"})
    assert config.defaults.headers["Authorization"] == "Bearer abc123"


def test_missing_env_var_raises_config_error() -> None:
    text = """\
version: 1
base_url: https://${MISSING_HOST}
rules:
  - from: /old
    to: /new
"""
    with pytest.raises(ConfigError) as exc_info:
        Config.from_yaml_str(text, env={})
    assert "MISSING_HOST" in str(exc_info.value)


def test_from_yaml_file(tmp_path: pytest.TempPathFactory) -> None:
    path = tmp_path / "redirects.yml"  # type: ignore[attr-defined]
    path.write_text(MINIMAL, encoding="utf-8")
    config = Config.from_yaml_file(path)
    assert config.base_url == "https://example.org"


def test_resolve_rule_uses_defaults_when_rule_has_no_override() -> None:
    defaults = Defaults(status=301, max_hops=5, headers={"X-A": "1"})
    rule = Rule(from_="/old", to="/new")
    resolved = resolve_rule(rule, defaults)
    assert resolved.status == 301
    assert resolved.max_hops == 5
    assert resolved.headers == {"X-A": "1"}


def test_resolve_rule_override_wins_over_defaults() -> None:
    defaults = Defaults(status=301, max_hops=5, headers={"X-A": "1"})
    rule = Rule(from_="/old", to="/new", status=302, max_hops=1, headers={"X-B": "2"})
    resolved = resolve_rule(rule, defaults)
    assert resolved.status == 302
    assert resolved.max_hops == 1
    # rule headers are merged over (not replacing) default headers
    assert resolved.headers == {"X-A": "1", "X-B": "2"}


def test_config_resolved_rules_merges_all_rules() -> None:
    config = Config.from_yaml_str(MINIMAL)
    resolved = config.resolved_rules()
    assert len(resolved) == 1
    assert resolved[0].status == 301
    assert resolved[0].max_hops == 5


def test_to_yaml_round_trips() -> None:
    config = Config.from_yaml_str(MINIMAL)
    dumped = config.to_yaml()
    reloaded = Config.from_yaml_str(dumped)
    assert reloaded.base_url == config.base_url
    assert reloaded.rules == config.rules

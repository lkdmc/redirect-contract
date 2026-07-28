import json
from pathlib import Path

import httpx
import respx
from typer.testing import CliRunner

from redirect_contract.cli import app

runner = CliRunner()

BASE = "https://example.org"

VALID_CONFIG = f"""\
version: 1
base_url: {BASE}
rules:
  - from: /old
    to: /new
"""


def _write_config(tmp_path: Path, text: str = VALID_CONFIG) -> Path:
    path = tmp_path / "redirects.yml"
    path.write_text(text, encoding="utf-8")
    return path


def test_missing_config_file_exits_2(tmp_path: Path) -> None:
    result = runner.invoke(app, ["check", str(tmp_path / "does-not-exist.yml")])
    assert result.exit_code == 2


def test_malformed_config_exits_2_with_friendly_message(tmp_path: Path) -> None:
    config_path = _write_config(tmp_path, "version: 1\nbase_url: [unclosed\n")
    result = runner.invoke(app, ["check", str(config_path)])
    assert result.exit_code == 2
    assert "Invalid YAML" in result.output
    assert "Traceback" not in result.output


def test_invalid_format_choice_exits_2(tmp_path: Path) -> None:
    config_path = _write_config(tmp_path)
    result = runner.invoke(app, ["check", str(config_path), "--format", "yaml"])
    assert result.exit_code == 2


def test_invalid_header_format_exits_2(tmp_path: Path) -> None:
    config_path = _write_config(tmp_path)
    result = runner.invoke(app, ["check", str(config_path), "--header", "no-colon-here"])
    assert result.exit_code == 2
    assert "--header" in result.output


def test_invalid_basic_auth_format_exits_2(tmp_path: Path) -> None:
    config_path = _write_config(tmp_path)
    result = runner.invoke(app, ["check", str(config_path), "--basic-auth", "no-colon"])
    assert result.exit_code == 2
    assert "--basic-auth" in result.output


@respx.mock
def test_passing_check_exits_0_and_prints_pass(tmp_path: Path) -> None:
    respx.head(f"{BASE}/old").mock(return_value=httpx.Response(301, headers={"location": "/new"}))
    respx.head(f"{BASE}/new").mock(return_value=httpx.Response(200))

    config_path = _write_config(tmp_path)
    result = runner.invoke(app, ["check", str(config_path), "--no-color"])

    assert result.exit_code == 0
    assert "PASS /old" in result.output


@respx.mock
def test_failing_check_exits_1(tmp_path: Path) -> None:
    respx.head(f"{BASE}/old").mock(return_value=httpx.Response(404))

    config_path = _write_config(tmp_path)
    result = runner.invoke(app, ["check", str(config_path), "--no-color"])

    assert result.exit_code == 1
    assert "FAIL /old" in result.output


@respx.mock
def test_json_format_output(tmp_path: Path) -> None:
    respx.head(f"{BASE}/old").mock(return_value=httpx.Response(301, headers={"location": "/new"}))
    respx.head(f"{BASE}/new").mock(return_value=httpx.Response(200))

    config_path = _write_config(tmp_path)
    result = runner.invoke(app, ["check", str(config_path), "--format", "json"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["passed"] is True


@respx.mock
def test_junit_format_output(tmp_path: Path) -> None:
    respx.head(f"{BASE}/old").mock(return_value=httpx.Response(301, headers={"location": "/new"}))
    respx.head(f"{BASE}/new").mock(return_value=httpx.Response(200))

    config_path = _write_config(tmp_path)
    result = runner.invoke(app, ["check", str(config_path), "--format", "junit"])

    assert result.exit_code == 0
    assert "<testsuite" in result.output


@respx.mock
def test_output_flag_writes_file_not_stdout(tmp_path: Path) -> None:
    respx.head(f"{BASE}/old").mock(return_value=httpx.Response(301, headers={"location": "/new"}))
    respx.head(f"{BASE}/new").mock(return_value=httpx.Response(200))

    config_path = _write_config(tmp_path)
    output_path = tmp_path / "report.json"
    result = runner.invoke(
        app, ["check", str(config_path), "--format", "json", "--output", str(output_path)]
    )

    assert result.exit_code == 0
    assert output_path.exists()
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["passed"] is True


def test_record_requires_exactly_one_source(tmp_path: Path) -> None:
    result = runner.invoke(app, ["record", "--base-url", BASE])
    assert result.exit_code == 2
    assert "exactly one" in result.output


def test_record_rejects_multiple_sources(tmp_path: Path) -> None:
    config_path = _write_config(tmp_path)
    result = runner.invoke(
        app, ["record", "/old", "--from-config", str(config_path), "--base-url", BASE]
    )
    assert result.exit_code == 2
    assert "exactly one" in result.output


def test_record_requires_base_url_for_positional_paths() -> None:
    result = runner.invoke(app, ["record", "/old"])
    assert result.exit_code == 2
    assert "--base-url" in result.output


@respx.mock
def test_record_positional_paths_writes_to_output(tmp_path: Path) -> None:
    respx.head(f"{BASE}/old").mock(return_value=httpx.Response(301, headers={"location": "/new"}))
    respx.head(f"{BASE}/new").mock(return_value=httpx.Response(200))

    output_path = tmp_path / "snapshot.yml"
    result = runner.invoke(
        app, ["record", "/old", "--base-url", BASE, "--output", str(output_path)]
    )

    assert result.exit_code == 0
    assert output_path.exists()
    assert "from: /old" in output_path.read_text(encoding="utf-8")


@respx.mock
def test_record_from_config_reuses_base_url_and_from_list(tmp_path: Path) -> None:
    respx.head(f"{BASE}/old").mock(return_value=httpx.Response(301, headers={"location": "/new"}))
    respx.head(f"{BASE}/new").mock(return_value=httpx.Response(200))

    config_path = _write_config(tmp_path)
    result = runner.invoke(app, ["record", "--from-config", str(config_path)])

    assert result.exit_code == 0
    assert "base_url: https://example.org" in result.output
    assert "from: /old" in result.output


@respx.mock
def test_record_from_file_reads_paths(tmp_path: Path) -> None:
    respx.head(f"{BASE}/old").mock(return_value=httpx.Response(301, headers={"location": "/new"}))
    respx.head(f"{BASE}/new").mock(return_value=httpx.Response(200))

    paths_file = tmp_path / "paths.txt"
    paths_file.write_text("/old\n", encoding="utf-8")
    result = runner.invoke(app, ["record", "--from-file", str(paths_file), "--base-url", BASE])

    assert result.exit_code == 0
    assert "from: /old" in result.output


def test_record_invalid_basic_auth_exits_2() -> None:
    result = runner.invoke(app, ["record", "/old", "--base-url", BASE, "--basic-auth", "no-colon"])
    assert result.exit_code == 2
    assert "--basic-auth" in result.output


@respx.mock
def test_record_error_exits_2(tmp_path: Path) -> None:
    respx.head(f"{BASE}/no-redirect").mock(return_value=httpx.Response(200))

    result = runner.invoke(app, ["record", "/no-redirect", "--base-url", BASE])

    assert result.exit_code == 2
    assert "did not redirect" in result.output


@respx.mock
def test_extra_header_and_basic_auth_reach_request(tmp_path: Path) -> None:
    route = respx.head(f"{BASE}/old").mock(
        return_value=httpx.Response(301, headers={"location": "/new"})
    )
    respx.head(f"{BASE}/new").mock(return_value=httpx.Response(200))

    config_path = _write_config(tmp_path)
    result = runner.invoke(
        app,
        [
            "check",
            str(config_path),
            "--header",
            "X-Extra: 1",
            "--basic-auth",
            "user:pass",
            "--no-color",
        ],
    )

    assert result.exit_code == 0
    sent = route.calls.last.request
    assert sent.headers["X-Extra"] == "1"
    assert "Authorization" in sent.headers

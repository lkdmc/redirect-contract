import json
import xml.etree.ElementTree as ET

from redirect_contract.formatters import format_json, format_junit, format_text
from redirect_contract.models import ResolvedRule
from redirect_contract.results import CheckReport, FailureReason, Hop, RuleResult


def _rule(**overrides: object) -> ResolvedRule:
    defaults: dict[str, object] = {
        "from_": "/2024/files",
        "to": "/2024-files/",
        "status": 301,
        "max_hops": 1,
        "timeout": 10.0,
        "headers": {},
        "basic_auth": None,
        "name": None,
    }
    defaults.update(overrides)
    return ResolvedRule(**defaults)  # type: ignore[arg-type]


def test_text_pass_line() -> None:
    result = RuleResult(
        rule=_rule(),
        passed=True,
        chain=[
            Hop("https://example.org/2024/files", 301),
            Hop("https://example.org/2024-files/", 200),
        ],
        final_url="https://example.org/2024-files/",
        failure_reason=None,
    )
    output = format_text(CheckReport(results=[result]), color=False)
    assert "PASS /2024/files" in output
    assert "1/1 passed" in output


def test_text_fail_shows_expected_and_actual_chain() -> None:
    result = RuleResult(
        rule=_rule(),
        passed=False,
        chain=[
            Hop("https://example.org/2024/files", 301),
            Hop("https://example.org/2024-files", 301),
            Hop("https://example.org/2024-files/", 200),
        ],
        final_url="https://example.org/2024-files/",
        failure_reason=FailureReason.TOO_MANY_HOPS,
        message="chain took 2 hops, max_hops is 1",
    )
    output = format_text(CheckReport(results=[result]), color=False)
    assert "FAIL /2024/files" in output
    assert "expected: 301 -> /2024-files/" in output
    assert (
        "actual:   301 -> https://example.org/2024-files -> "
        "301 -> https://example.org/2024-files/  (2 hops)" in output
    )
    assert "0/1 passed" in output


def test_text_color_uses_rich_markup() -> None:
    result = RuleResult(
        rule=_rule(), passed=True, chain=[Hop("u", 301)], final_url="u", failure_reason=None
    )
    output = format_text(CheckReport(results=[result]), color=True)
    assert "[green]PASS[/green]" in output


def test_text_network_error_has_no_chain_but_shows_message() -> None:
    result = RuleResult(
        rule=_rule(),
        passed=False,
        chain=[],
        final_url=None,
        failure_reason=FailureReason.TIMEOUT,
        message="request timed out",
    )
    output = format_text(CheckReport(results=[result]), color=False)
    assert "(no response) (request timed out)" in output


def test_json_output_is_valid_and_shapes_fields() -> None:
    result = RuleResult(
        rule=_rule(),
        passed=False,
        chain=[Hop("https://example.org/2024/files", 301)],
        final_url="https://example.org/2024/files",
        failure_reason=FailureReason.WRONG_FINAL_URL,
        message="expected final URL ..., got ...",
    )
    output = format_json(CheckReport(results=[result]))
    payload = json.loads(output)
    assert payload["passed"] is False
    entry = payload["results"][0]
    assert entry["from"] == "/2024/files"
    assert entry["to"] == "/2024-files/"
    assert entry["failure_reason"] == "wrong_final_url"
    assert entry["chain"] == [{"url": "https://example.org/2024/files", "status": 301}]


def test_junit_output_is_valid_xml_with_failure_element() -> None:
    passing = RuleResult(
        rule=_rule(from_="/ok"),
        passed=True,
        chain=[Hop("u", 301)],
        final_url="u",
        failure_reason=None,
    )
    failing = RuleResult(
        rule=_rule(),
        passed=False,
        chain=[Hop("https://example.org/2024/files", 301)],
        final_url="https://example.org/2024/files",
        failure_reason=FailureReason.WRONG_FINAL_URL,
        message="wrong final url",
    )
    output = format_junit(CheckReport(results=[passing, failing]))
    root = ET.fromstring(output)
    assert root.tag == "testsuite"
    assert root.attrib["tests"] == "2"
    assert root.attrib["failures"] == "1"
    cases = root.findall("testcase")
    assert len(cases) == 2
    assert cases[0].attrib["name"] == "/ok"
    assert cases[0].find("failure") is None
    failure = cases[1].find("failure")
    assert failure is not None
    assert failure.attrib["type"] == "wrong_final_url"


def test_junit_uses_rule_name_when_present() -> None:
    result = RuleResult(
        rule=_rule(name="2024 files rollover"),
        passed=True,
        chain=[Hop("u", 301)],
        final_url="u",
        failure_reason=None,
    )
    output = format_junit(CheckReport(results=[result]))
    root = ET.fromstring(output)
    assert root.find("testcase").attrib["name"] == "2024 files rollover"  # type: ignore[union-attr]

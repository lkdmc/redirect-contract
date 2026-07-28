"""JUnit XML output, for GitLab CI / GitHub Actions test report integrations."""

from __future__ import annotations

import xml.etree.ElementTree as ET

from redirect_contract.formatters.text import render_actual_chain
from redirect_contract.results import CheckReport


def format_junit(report: CheckReport) -> str:
    total = len(report.results)
    failures = sum(1 for result in report.results if not result.passed)

    suite = ET.Element(
        "testsuite",
        {"name": "redirect-contract", "tests": str(total), "failures": str(failures)},
    )
    for result in report.results:
        label = result.rule.name or result.rule.from_
        case = ET.SubElement(suite, "testcase", {"classname": "redirect_contract", "name": label})
        if not result.passed:
            failure_type = result.failure_reason.value if result.failure_reason else "failure"
            failure = ET.SubElement(
                case,
                "failure",
                {"message": result.message or failure_type, "type": failure_type},
            )
            failure.text = (
                f"expected: {result.rule.status} -> {result.rule.to}\n"
                f"actual:   {render_actual_chain(result)}"
            )

    ET.indent(suite)
    body = ET.tostring(suite, encoding="unicode")
    return f'<?xml version="1.0" encoding="UTF-8"?>\n{body}\n'

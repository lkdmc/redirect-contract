"""Human-readable text output, with an optional plain (no-color) mode for CI logs."""

from __future__ import annotations

from redirect_contract.results import CheckReport, Hop, RuleResult


def format_text(report: CheckReport, *, color: bool) -> str:
    lines: list[str] = []
    for result in report.results:
        label = result.rule.name or result.rule.from_
        if result.passed:
            word = "[green]PASS[/green]" if color else "PASS"
            lines.append(f"{word} {label}")
        else:
            word = "[red]FAIL[/red]" if color else "FAIL"
            lines.append(f"{word} {label}")
            lines.append(f"  expected: {result.rule.status} -> {result.rule.to}")
            lines.append(f"  actual:   {render_actual_chain(result)}")

    total = len(report.results)
    passed = sum(1 for result in report.results if result.passed)
    lines.append("")
    lines.append(f"{passed}/{total} passed")
    return "\n".join(lines)


def render_actual_chain(result: RuleResult) -> str:
    if not result.chain:
        detail = f" ({result.message})" if result.message else ""
        return f"(no response){detail}"

    chain_str = _render_chain(result.chain)
    hops = max(len(result.chain) - 1, 0)
    suffix = f"  ({hops} hop{'s' if hops != 1 else ''})"
    return f"{chain_str}{suffix}"


def _render_chain(chain: list[Hop]) -> str:
    if len(chain) == 1:
        return str(chain[0].status)
    parts: list[str] = []
    for i in range(len(chain) - 1):
        parts.append(str(chain[i].status))
        parts.append(chain[i + 1].url)
    return " -> ".join(parts)

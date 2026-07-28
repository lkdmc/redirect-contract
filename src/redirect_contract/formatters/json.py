"""Machine-readable JSON output."""

from __future__ import annotations

import json as _json
from typing import Any

from redirect_contract.results import CheckReport


def format_json(report: CheckReport) -> str:
    payload: dict[str, Any] = {
        "passed": report.passed,
        "results": [
            {
                "from": result.rule.from_,
                "to": result.rule.to,
                "name": result.rule.name,
                "expected_status": result.rule.status,
                "max_hops": result.rule.max_hops,
                "passed": result.passed,
                "failure_reason": result.failure_reason.value if result.failure_reason else None,
                "message": result.message,
                "final_url": result.final_url,
                "chain": [{"url": hop.url, "status": hop.status} for hop in result.chain],
            }
            for result in report.results
        ],
    }
    return _json.dumps(payload, indent=2)

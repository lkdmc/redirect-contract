import httpx
import respx

from redirect_contract.checker import check
from redirect_contract.models import Config
from redirect_contract.results import FailureReason

BASE = "https://example.org"


def _config(rules_yaml: str, defaults_yaml: str = "") -> Config:
    text = f"""\
version: 1
base_url: {BASE}
{defaults_yaml}rules:
{rules_yaml}
"""
    return Config.from_yaml_str(text)


@respx.mock
async def test_happy_path_single_hop() -> None:
    respx.head(f"{BASE}/old").mock(return_value=httpx.Response(301, headers={"location": "/new"}))
    respx.head(f"{BASE}/new").mock(return_value=httpx.Response(200))

    config = _config("  - from: /old\n    to: /new\n")
    report = await check(config)

    assert report.passed
    result = report.results[0]
    assert result.final_url == f"{BASE}/new"
    assert [(h.url, h.status) for h in result.chain] == [
        (f"{BASE}/old", 301),
        (f"{BASE}/new", 200),
    ]


@respx.mock
async def test_wrong_final_url() -> None:
    respx.head(f"{BASE}/old").mock(
        return_value=httpx.Response(301, headers={"location": "/somewhere-else"})
    )
    respx.head(f"{BASE}/somewhere-else").mock(return_value=httpx.Response(200))

    config = _config("  - from: /old\n    to: /new\n")
    report = await check(config)

    assert not report.passed
    result = report.results[0]
    assert result.failure_reason == FailureReason.WRONG_FINAL_URL
    assert result.final_url == f"{BASE}/somewhere-else"


@respx.mock
async def test_wrong_status() -> None:
    respx.head(f"{BASE}/old").mock(return_value=httpx.Response(302, headers={"location": "/new"}))
    respx.head(f"{BASE}/new").mock(return_value=httpx.Response(200))

    config = _config("  - from: /old\n    to: /new\n    status: 301\n")
    report = await check(config)

    assert not report.passed
    result = report.results[0]
    assert result.failure_reason == FailureReason.WRONG_STATUS


@respx.mock
async def test_redirect_loop_detected() -> None:
    respx.head(f"{BASE}/a").mock(return_value=httpx.Response(301, headers={"location": "/b"}))
    respx.head(f"{BASE}/b").mock(return_value=httpx.Response(301, headers={"location": "/a"}))

    config = _config("  - from: /a\n    to: /new\n    max_hops: 10\n")
    report = await check(config)

    assert not report.passed
    result = report.results[0]
    assert result.failure_reason == FailureReason.LOOP


@respx.mock
async def test_chain_too_long() -> None:
    respx.head(f"{BASE}/hop0").mock(return_value=httpx.Response(301, headers={"location": "/hop1"}))
    respx.head(f"{BASE}/hop1").mock(return_value=httpx.Response(301, headers={"location": "/hop2"}))
    respx.head(f"{BASE}/hop2").mock(return_value=httpx.Response(200))

    config = _config("  - from: /hop0\n    to: /hop2\n    max_hops: 1\n")
    report = await check(config)

    assert not report.passed
    result = report.results[0]
    assert result.failure_reason == FailureReason.TOO_MANY_HOPS
    assert len(result.chain) == 3


@respx.mock
async def test_timeout() -> None:
    respx.head(f"{BASE}/old").mock(side_effect=httpx.TimeoutException("timed out"))

    config = _config("  - from: /old\n    to: /new\n")
    report = await check(config)

    assert not report.passed
    result = report.results[0]
    assert result.failure_reason == FailureReason.TIMEOUT
    assert result.chain == []


@respx.mock
async def test_connection_error() -> None:
    respx.head(f"{BASE}/old").mock(side_effect=httpx.ConnectError("connection refused"))

    config = _config("  - from: /old\n    to: /new\n")
    report = await check(config)

    assert not report.passed
    result = report.results[0]
    assert result.failure_reason == FailureReason.CONNECTION_ERROR


@respx.mock
async def test_final_error_status() -> None:
    respx.head(f"{BASE}/old").mock(return_value=httpx.Response(404))

    config = _config("  - from: /old\n    to: /new\n")
    report = await check(config)

    assert not report.passed
    result = report.results[0]
    assert result.failure_reason == FailureReason.ERROR_STATUS


@respx.mock
async def test_https_to_http_downgrade() -> None:
    respx.head(f"{BASE}/old").mock(
        return_value=httpx.Response(301, headers={"location": "http://example.org/new"})
    )
    respx.head("http://example.org/new").mock(return_value=httpx.Response(200))

    config = _config("  - from: /old\n    to: http://example.org/new\n")
    report = await check(config)

    assert not report.passed
    result = report.results[0]
    assert result.failure_reason == FailureReason.DOWNGRADE


@respx.mock
async def test_head_405_falls_back_to_get_for_whole_chain() -> None:
    respx.head(f"{BASE}/old").mock(return_value=httpx.Response(405))
    respx.get(f"{BASE}/old").mock(return_value=httpx.Response(301, headers={"location": "/new"}))
    respx.get(f"{BASE}/new").mock(return_value=httpx.Response(200))

    config = _config("  - from: /old\n    to: /new\n")
    report = await check(config)

    assert report.passed
    # only GET routes were used for the second hop; HEAD was never retried there
    assert respx.calls.call_count == 3


@respx.mock
async def test_cross_domain_absolute_to() -> None:
    respx.head(f"{BASE}/old-page").mock(
        return_value=httpx.Response(302, headers={"location": "https://other.example.org/new-page"})
    )
    respx.head("https://other.example.org/new-page").mock(return_value=httpx.Response(200))

    config = _config(
        "  - from: /old-page\n    to: https://other.example.org/new-page\n    status: 302\n"
    )
    report = await check(config)

    assert report.passed


@respx.mock
async def test_extra_headers_and_basic_auth_override_reach_request() -> None:
    route = respx.head(f"{BASE}/old").mock(
        return_value=httpx.Response(301, headers={"location": "/new"})
    )
    respx.head(f"{BASE}/new").mock(return_value=httpx.Response(200))

    config = _config("  - from: /old\n    to: /new\n")
    await check(config, headers={"X-Extra": "1"}, basic_auth="user:pass")

    sent = route.calls.last.request
    assert sent.headers["X-Extra"] == "1"
    assert "Authorization" in sent.headers


@respx.mock
async def test_multiple_rules_checked_concurrently() -> None:
    respx.head(f"{BASE}/a").mock(return_value=httpx.Response(301, headers={"location": "/a-new"}))
    respx.head(f"{BASE}/a-new").mock(return_value=httpx.Response(200))
    respx.head(f"{BASE}/b").mock(return_value=httpx.Response(301, headers={"location": "/b-new"}))
    respx.head(f"{BASE}/b-new").mock(return_value=httpx.Response(200))

    config = _config("  - from: /a\n    to: /a-new\n  - from: /b\n    to: /b-new\n")
    report = await check(config, concurrency=1)

    assert report.passed
    assert len(report.results) == 2

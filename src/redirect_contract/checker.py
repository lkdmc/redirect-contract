"""Async redirect chain resolution and assertion checking."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from urllib.parse import urljoin, urlparse

import httpx

from redirect_contract.models import Config, ResolvedRule
from redirect_contract.results import CheckReport, FailureReason, Hop, RuleResult

# Extra hops fetched beyond a rule's configured max_hops, purely so a
# too-many-hops failure can report the real chain instead of truncating
# right at the limit.
HOP_REPORTING_BUFFER = 10


class ChainTimeout(Exception):
    def __init__(self, partial_chain: list[Hop]) -> None:
        self.partial_chain = partial_chain


class ChainConnectionError(Exception):
    def __init__(self, partial_chain: list[Hop], message: str) -> None:
        self.partial_chain = partial_chain
        self.message = message


async def check(
    config: Config,
    *,
    concurrency: int = 10,
    client: httpx.AsyncClient | None = None,
    headers: Mapping[str, str] | None = None,
    basic_auth: str | None = None,
) -> CheckReport:
    """Fetch every rule in ``config`` and assert its redirect chain.

    ``headers`` are merged over (and win ties with) each rule's own headers.
    ``basic_auth`` ("user:pass"), if given, overrides any basic_auth set in
    the config's defaults. ``client`` lets callers inject their own
    httpx.AsyncClient (e.g. a mocked one in tests); one is created and closed
    automatically otherwise.
    """
    semaphore = asyncio.Semaphore(concurrency)
    owns_client = client is None
    active_client = client if client is not None else httpx.AsyncClient()
    try:

        async def run(resolved: ResolvedRule) -> RuleResult:
            async with semaphore:
                return await _check_rule(
                    active_client,
                    config.base_url,
                    resolved,
                    extra_headers=headers,
                    basic_auth_override=basic_auth,
                )

        results = await asyncio.gather(*(run(rule) for rule in config.resolved_rules()))
        return CheckReport(results=list(results))
    finally:
        if owns_client:
            await active_client.aclose()


async def _check_rule(
    client: httpx.AsyncClient,
    base_url: str,
    resolved: ResolvedRule,
    *,
    extra_headers: Mapping[str, str] | None,
    basic_auth_override: str | None,
) -> RuleResult:
    start_url = urljoin(base_url + "/", resolved.from_.lstrip("/"))
    expected_final_url = urljoin(base_url + "/", resolved.to.lstrip("/"))
    request_headers = {**resolved.headers, **(extra_headers or {})}

    basic_auth_value = (
        basic_auth_override if basic_auth_override is not None else resolved.basic_auth
    )
    auth: tuple[str, str] | None = None
    if basic_auth_value is not None:
        user, _, password = basic_auth_value.partition(":")
        auth = (user, password)

    max_requests = resolved.max_hops + HOP_REPORTING_BUFFER + 1

    try:
        chain, looped = await fetch_chain(
            client,
            start_url,
            headers=request_headers,
            auth=auth,
            timeout=resolved.timeout,
            max_requests=max_requests,
        )
    except ChainTimeout as exc:
        return RuleResult(
            rule=resolved,
            passed=False,
            chain=exc.partial_chain,
            final_url=None,
            failure_reason=FailureReason.TIMEOUT,
            message="request timed out",
        )
    except ChainConnectionError as exc:
        return RuleResult(
            rule=resolved,
            passed=False,
            chain=exc.partial_chain,
            final_url=None,
            failure_reason=FailureReason.CONNECTION_ERROR,
            message=exc.message,
        )

    final_url = chain[-1].url if chain else None
    num_hops = max(len(chain) - 1, 0)

    if looped:
        return _fail(resolved, chain, final_url, FailureReason.LOOP, "redirect loop detected")
    if num_hops > resolved.max_hops:
        return _fail(
            resolved,
            chain,
            final_url,
            FailureReason.TOO_MANY_HOPS,
            f"chain took {num_hops} hops, max_hops is {resolved.max_hops}",
        )
    if _has_downgrade(chain):
        return _fail(
            resolved, chain, final_url, FailureReason.DOWNGRADE, "https -> http downgrade in chain"
        )
    if chain[-1].status >= 400:
        return _fail(
            resolved,
            chain,
            final_url,
            FailureReason.ERROR_STATUS,
            f"final response was {chain[-1].status}",
        )
    if chain[0].status != resolved.status:
        return _fail(
            resolved,
            chain,
            final_url,
            FailureReason.WRONG_STATUS,
            f"expected first-hop status {resolved.status}, got {chain[0].status}",
        )
    if not _urls_match(final_url, expected_final_url):
        return _fail(
            resolved,
            chain,
            final_url,
            FailureReason.WRONG_FINAL_URL,
            f"expected final URL {expected_final_url}, got {final_url}",
        )

    return RuleResult(
        rule=resolved, passed=True, chain=chain, final_url=final_url, failure_reason=None
    )


async def fetch_chain(
    client: httpx.AsyncClient,
    start_url: str,
    *,
    headers: Mapping[str, str],
    auth: tuple[str, str] | None,
    timeout: float,
    max_requests: int,
) -> tuple[list[Hop], bool]:
    """Follow redirects from start_url, HEAD-first with GET fallback on 405/501.

    Returns (chain, looped). The chain always ends with either a terminal
    (non-redirect) response or is truncated at max_requests hops.
    """
    method = "HEAD"
    current_url = start_url
    chain: list[Hop] = []
    visited: set[str] = set()
    requests_made = 0

    while requests_made < max_requests:
        if current_url in visited:
            return chain, True

        try:
            response = await client.request(
                method, current_url, headers=headers, auth=auth, timeout=timeout
            )
        except httpx.TimeoutException as exc:
            raise ChainTimeout(chain) from exc
        except httpx.HTTPError as exc:
            raise ChainConnectionError(chain, str(exc)) from exc
        requests_made += 1

        if method == "HEAD" and response.status_code in (405, 501):
            method = "GET"
            continue

        visited.add(current_url)
        chain.append(Hop(url=current_url, status=response.status_code))

        if 300 <= response.status_code < 400 and "location" in response.headers:
            current_url = urljoin(current_url, response.headers["location"])
            continue

        break

    return chain, False


def _has_downgrade(chain: list[Hop]) -> bool:
    for previous, following in zip(chain, chain[1:], strict=False):
        if urlparse(previous.url).scheme == "https" and urlparse(following.url).scheme == "http":
            return True
    return False


def _urls_match(actual: str | None, expected: str) -> bool:
    if actual is None:
        return False
    a, e = urlparse(actual), urlparse(expected)
    return (a.scheme.lower(), a.netloc.lower(), a.path, a.query) == (
        e.scheme.lower(),
        e.netloc.lower(),
        e.path,
        e.query,
    )


def _fail(
    resolved: ResolvedRule,
    chain: list[Hop],
    final_url: str | None,
    reason: FailureReason,
    message: str,
) -> RuleResult:
    return RuleResult(
        rule=resolved,
        passed=False,
        chain=chain,
        final_url=final_url,
        failure_reason=reason,
        message=message,
    )

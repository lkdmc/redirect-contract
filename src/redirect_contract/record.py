"""Probe a live site and capture its current redirect behaviour as a Config.

This is the migration workflow: snapshot with record() before touching the
server config, then use check() against the snapshot afterwards to assert
nothing changed unexpectedly.

Note that ``headers``/``basic_auth`` here authenticate the probe requests
only. They are never written into the returned Config, so a snapshot can be
safely committed without leaking whatever credentials were needed to take it.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from urllib.parse import urljoin, urlparse

import httpx

from redirect_contract.checker import (
    HOP_REPORTING_BUFFER,
    ChainConnectionError,
    ChainTimeout,
    fetch_chain,
)
from redirect_contract.exceptions import RecordError
from redirect_contract.models import Config, Defaults, Rule


async def record(
    base_url: str,
    paths: Sequence[str],
    *,
    status: int = 301,
    max_hops: int = 5,
    headers: Mapping[str, str] | None = None,
    basic_auth: str | None = None,
    concurrency: int = 10,
    client: httpx.AsyncClient | None = None,
) -> Config:
    """Probe every path against base_url and build a Config from what's observed.

    ``status``/``max_hops`` become the returned Config's ``defaults``; each
    rule's own status/max_hops is only set when the observed behaviour
    wouldn't already satisfy those defaults.
    """
    probe_auth: tuple[str, str] | None = None
    if basic_auth is not None:
        user, _, password = basic_auth.partition(":")
        probe_auth = (user, password)
    probe_headers = dict(headers) if headers is not None else {}

    semaphore = asyncio.Semaphore(concurrency)
    owns_client = client is None
    active_client = client if client is not None else httpx.AsyncClient()
    try:

        async def probe(path: str) -> Rule:
            async with semaphore:
                return await _probe_path(
                    active_client,
                    base_url,
                    path,
                    status=status,
                    max_hops=max_hops,
                    headers=probe_headers,
                    auth=probe_auth,
                )

        rules = await asyncio.gather(*(probe(path) for path in paths))
    finally:
        if owns_client:
            await active_client.aclose()

    return Config(
        version=1,
        base_url=base_url,
        defaults=Defaults(status=status, max_hops=max_hops),
        rules=list(rules),
    )


async def _probe_path(
    client: httpx.AsyncClient,
    base_url: str,
    path: str,
    *,
    status: int,
    max_hops: int,
    headers: Mapping[str, str],
    auth: tuple[str, str] | None,
) -> Rule:
    normalized_path = path if path.startswith("/") else f"/{path}"
    start_url = urljoin(base_url + "/", normalized_path.lstrip("/"))
    max_requests = max_hops + HOP_REPORTING_BUFFER + 1

    try:
        chain, looped = await fetch_chain(
            client, start_url, headers=headers, auth=auth, timeout=10.0, max_requests=max_requests
        )
    except ChainTimeout as exc:
        raise RecordError(f"failed to probe {path}: request timed out") from exc
    except ChainConnectionError as exc:
        raise RecordError(f"failed to probe {path}: {exc.message}") from exc

    if not chain:
        raise RecordError(f"failed to probe {path}: no response received")
    if looped:
        raise RecordError(f"failed to probe {path}: redirect loop detected")
    if 300 <= chain[-1].status < 400:
        raise RecordError(
            f"failed to probe {path}: chain did not terminate within {max_requests} requests "
            "(possible very long or effectively infinite redirect chain)"
        )

    first_status = chain[0].status
    if not (300 <= first_status < 400):
        raise RecordError(
            f"failed to probe {path}: did not redirect "
            f"(got {first_status} directly), nothing to record"
        )
    num_hops = max(len(chain) - 1, 0)
    to_value = _relativize(chain[-1].url, base_url)

    return Rule(
        from_=normalized_path,
        to=to_value,
        status=first_status if first_status != status else None,
        max_hops=num_hops if num_hops > max_hops else None,
    )


def _relativize(url: str, base_url: str) -> str:
    """Return url as a base_url-relative path if it shares base_url's origin, else as-is."""
    target, base = urlparse(url), urlparse(base_url)
    if (target.scheme, target.netloc) != (base.scheme, base.netloc):
        return url
    relative = target.path or "/"
    if target.query:
        relative = f"{relative}?{target.query}"
    return relative

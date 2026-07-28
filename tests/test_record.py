import httpx
import pytest
import respx

from redirect_contract.exceptions import RecordError
from redirect_contract.record import record

BASE = "https://example.org"


@respx.mock
async def test_records_single_hop_matching_defaults() -> None:
    respx.head(f"{BASE}/old").mock(return_value=httpx.Response(301, headers={"location": "/new"}))
    respx.head(f"{BASE}/new").mock(return_value=httpx.Response(200))

    config = await record(BASE, ["/old"])

    assert config.base_url == BASE
    assert config.defaults.status == 301
    assert config.defaults.max_hops == 5
    rule = config.rules[0]
    assert rule.from_ == "/old"
    assert rule.to == "/new"
    # matches the baseline defaults, so no per-rule override needed
    assert rule.status is None
    assert rule.max_hops is None


@respx.mock
async def test_records_status_override_when_it_differs_from_baseline() -> None:
    respx.head(f"{BASE}/old").mock(return_value=httpx.Response(302, headers={"location": "/new"}))
    respx.head(f"{BASE}/new").mock(return_value=httpx.Response(200))

    config = await record(BASE, ["/old"], status=301)

    assert config.rules[0].status == 302


@respx.mock
async def test_records_max_hops_override_when_chain_exceeds_baseline() -> None:
    respx.head(f"{BASE}/hop0").mock(return_value=httpx.Response(301, headers={"location": "/hop1"}))
    respx.head(f"{BASE}/hop1").mock(return_value=httpx.Response(301, headers={"location": "/hop2"}))
    respx.head(f"{BASE}/hop2").mock(return_value=httpx.Response(200))

    config = await record(BASE, ["/hop0"], max_hops=1)

    assert config.rules[0].max_hops == 2
    assert config.rules[0].to == "/hop2"


@respx.mock
async def test_cross_domain_final_url_kept_absolute() -> None:
    respx.head(f"{BASE}/old").mock(
        return_value=httpx.Response(301, headers={"location": "https://other.example.org/new"})
    )
    respx.head("https://other.example.org/new").mock(return_value=httpx.Response(200))

    config = await record(BASE, ["/old"])

    assert config.rules[0].to == "https://other.example.org/new"


@respx.mock
async def test_multiple_paths_recorded_in_order() -> None:
    respx.head(f"{BASE}/a").mock(return_value=httpx.Response(301, headers={"location": "/a-new"}))
    respx.head(f"{BASE}/a-new").mock(return_value=httpx.Response(200))
    respx.head(f"{BASE}/b").mock(return_value=httpx.Response(301, headers={"location": "/b-new"}))
    respx.head(f"{BASE}/b-new").mock(return_value=httpx.Response(200))

    config = await record(BASE, ["/a", "/b"])

    assert [rule.from_ for rule in config.rules] == ["/a", "/b"]
    assert [rule.to for rule in config.rules] == ["/a-new", "/b-new"]


@respx.mock
async def test_path_without_leading_slash_is_normalized() -> None:
    respx.head(f"{BASE}/old").mock(return_value=httpx.Response(301, headers={"location": "/new"}))
    respx.head(f"{BASE}/new").mock(return_value=httpx.Response(200))

    config = await record(BASE, ["old"])

    assert config.rules[0].from_ == "/old"


@respx.mock
async def test_direct_response_with_no_redirect_raises_record_error() -> None:
    respx.head(f"{BASE}/already-there").mock(return_value=httpx.Response(200))

    with pytest.raises(RecordError, match="did not redirect"):
        await record(BASE, ["/already-there"])


@respx.mock
async def test_loop_raises_record_error() -> None:
    respx.head(f"{BASE}/a").mock(return_value=httpx.Response(301, headers={"location": "/b"}))
    respx.head(f"{BASE}/b").mock(return_value=httpx.Response(301, headers={"location": "/a"}))

    with pytest.raises(RecordError, match="loop"):
        await record(BASE, ["/a"], max_hops=10)


@respx.mock
async def test_timeout_raises_record_error() -> None:
    respx.head(f"{BASE}/old").mock(side_effect=httpx.TimeoutException("timed out"))

    with pytest.raises(RecordError, match="timed out"):
        await record(BASE, ["/old"])


@respx.mock
async def test_connection_error_raises_record_error() -> None:
    respx.head(f"{BASE}/old").mock(side_effect=httpx.ConnectError("refused"))

    with pytest.raises(RecordError, match="refused"):
        await record(BASE, ["/old"])


@respx.mock
async def test_probe_auth_and_headers_reach_request_but_are_not_in_output() -> None:
    route = respx.head(f"{BASE}/old").mock(
        return_value=httpx.Response(301, headers={"location": "/new"})
    )
    respx.head(f"{BASE}/new").mock(return_value=httpx.Response(200))

    config = await record(BASE, ["/old"], headers={"X-Extra": "1"}, basic_auth="user:pass")

    sent = route.calls.last.request
    assert sent.headers["X-Extra"] == "1"
    assert "Authorization" in sent.headers
    # credentials used to authenticate the probe must never leak into the snapshot
    assert config.defaults.headers == {}
    assert config.defaults.basic_auth is None


@respx.mock
async def test_recorded_config_round_trips_through_yaml() -> None:
    respx.head(f"{BASE}/old").mock(return_value=httpx.Response(301, headers={"location": "/new"}))
    respx.head(f"{BASE}/new").mock(return_value=httpx.Response(200))

    config = await record(BASE, ["/old"])
    dumped = config.to_yaml()

    from redirect_contract.models import Config

    reloaded = Config.from_yaml_str(dumped)
    assert reloaded.rules == config.rules
    assert reloaded.base_url == config.base_url

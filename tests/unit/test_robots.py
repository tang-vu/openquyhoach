"""robots.txt handling — parsed through our own fetch (SSRF + UA policy),
never robotparser.read(); conservative on auth blocks and 5xx."""

from __future__ import annotations

import httpx
import pytest
import respx
from openquyhoach_core import robots

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _clear_cache():
    robots.reset_cache()
    yield
    robots.reset_cache()


ROBOTS_TXT = """\
User-agent: *
Disallow: /private/
Crawl-delay: 7
"""


@respx.mock
def test_rules_parsed_and_enforced():
    respx.get("https://example.com/robots.txt").mock(
        return_value=httpx.Response(200, text=ROBOTS_TXT)
    )
    assert robots.robots_allowed("https://example.com/public/page")
    assert not robots.robots_allowed("https://example.com/private/doc.pdf")


@respx.mock
def test_specific_group_overrides_star():
    """RFC 9309: the most specific matching group wins, exclusively."""
    respx.get("https://example.com/robots.txt").mock(
        return_value=httpx.Response(
            200,
            text=(
                "User-agent: *\nDisallow: /private/\nCrawl-delay: 7\n\n"
                "User-agent: OpenQuyHoach\nDisallow:\n"
            ),
        )
    )
    # our UA matches the OpenQuyHoach group -> * rules do not apply
    assert robots.robots_allowed("https://example.com/private/doc.pdf")
    assert robots.crawl_delay("https://example.com/x") is None
    # a different UA falls back to the * group
    assert not robots.robots_allowed(
        "https://example.com/private/doc.pdf", user_agent="OtherBot"
    )
    assert robots.crawl_delay("https://example.com/x", user_agent="OtherBot") == 7.0


@respx.mock
def test_crawl_delay_honoured():
    respx.get("https://example.com/robots.txt").mock(
        return_value=httpx.Response(200, text=ROBOTS_TXT)
    )
    assert robots.crawl_delay("https://example.com/anything") == 7.0


@respx.mock
def test_missing_robots_allows():
    respx.get("https://example.com/robots.txt").mock(
        return_value=httpx.Response(404)
    )
    assert robots.robots_allowed("https://example.com/anything")
    assert robots.crawl_delay("https://example.com/anything") is None


@respx.mock
@pytest.mark.parametrize("status", [401, 403, 500, 503])
def test_auth_blocks_and_5xx_disallow(status):
    """401/403 and server errors are treated conservatively: no fetch."""
    respx.get("https://example.com/robots.txt").mock(
        return_value=httpx.Response(status)
    )
    assert not robots.robots_allowed("https://example.com/page")


@respx.mock
def test_transport_error_disallows():
    respx.get("https://example.com/robots.txt").mock(
        side_effect=httpx.ConnectError("down")
    )
    assert not robots.robots_allowed("https://example.com/page")


def test_file_scheme_skips_robots():
    assert robots.robots_allowed("file:///fixtures/x.pdf")
    assert robots.crawl_delay("file:///fixtures/x.pdf") is None

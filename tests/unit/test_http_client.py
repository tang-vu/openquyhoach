"""fetch_url — conditional requests, checksum verification, caps,
Content-Disposition filenames, retry on 5xx/429. All HTTP via respx."""

from __future__ import annotations

import hashlib

import httpx
import pytest
import respx
from openquyhoach_core.errors import ValidationError
from openquyhoach_ingest.http_client import FetchBlockedError, fetch_url

pytestmark = pytest.mark.unit

BODY = b"PK\x03\x04 fake artifact bytes" * 64
SHA = hashlib.sha256(BODY).hexdigest()
URL = "https://example.com/plans/qh-2024.zip"


@pytest.fixture(autouse=True)
def _robots_404():
    """Every test host answers robots.txt 404 (allow-all, no delay)."""
    with respx.mock(assert_all_called=False) as m:
        m.get(path__regex=r"https://[^/]+/robots\.txt").mock(
            return_value=httpx.Response(404)
        )
        yield m


@respx.mock
def test_download_captures_provenance(tmp_path):
    respx.get(URL).mock(
        return_value=httpx.Response(
            200,
            content=BODY,
            headers={
                "etag": '"v1"',
                "last-modified": "Wed, 01 Jan 2025 00:00:00 GMT",
                "content-type": "application/zip; charset=binary",
                "content-disposition": 'attachment; filename="qh-tp-2024.zip"',
            },
        )
    )
    r = fetch_url(URL, tmp_path)
    assert r["sha256"] == SHA
    assert r["size"] == len(BODY)
    assert r["etag"] == '"v1"'
    assert r["mime_type"] == "application/zip"
    assert r["filename"] == "qh-tp-2024.zip"
    assert r["http_status"] == 200
    assert r["response_headers"]["etag"] == '"v1"'
    assert r["local_path"].read_bytes() == BODY


@respx.mock
def test_conditional_request_sends_validators_and_304(tmp_path):
    route = respx.get(URL).mock(return_value=httpx.Response(304))
    r = fetch_url(URL, tmp_path, etag='"v1"', last_modified="Wed, 01 Jan 2025 00:00:00 GMT")
    assert r["not_modified"] is True
    assert r["http_status"] == 304
    sent = route.calls.last.request
    assert sent.headers["if-none-match"] == '"v1"'
    assert "if-modified-since" in sent.headers


@respx.mock
def test_checksum_mismatch_rejected(tmp_path):
    respx.get(URL).mock(return_value=httpx.Response(200, content=BODY))
    with pytest.raises(ValidationError, match="checksum mismatch"):
        fetch_url(URL, tmp_path, expected_sha256="0" * 64)


@respx.mock
def test_content_length_cap(tmp_path):
    respx.get(URL).mock(
        return_value=httpx.Response(
            200, content=BODY, headers={"content-length": str(len(BODY))}
        )
    )
    with pytest.raises(FetchBlockedError, match="exceeds cap"):
        fetch_url(URL, tmp_path, max_bytes=16)


@respx.mock
def test_streaming_cap(tmp_path):
    """Cap enforced even without a content-length header."""
    respx.get(URL).mock(return_value=httpx.Response(200, content=BODY))
    with pytest.raises(FetchBlockedError, match="exceeds cap"):
        fetch_url(URL, tmp_path, max_bytes=16)


@respx.mock
def test_retry_on_503_then_success(tmp_path):
    route = respx.get(URL)
    route.side_effect = [
        httpx.Response(503),
        httpx.Response(200, content=BODY),
    ]
    r = fetch_url(URL, tmp_path)
    assert r["sha256"] == SHA
    assert route.call_count == 2


@respx.mock
def test_user_agent_override(tmp_path):
    route = respx.get(URL).mock(return_value=httpx.Response(200, content=BODY))
    fetch_url(URL, tmp_path, user_agent="OpenQuyHoach-test/9.9")
    assert route.calls.last.request.headers["user-agent"] == "OpenQuyHoach-test/9.9"


@respx.mock
def test_redirect_final_url_reported(tmp_path):
    respx.get("https://example.com/old").mock(
        return_value=httpx.Response(302, headers={"location": URL})
    )
    respx.get(URL).mock(return_value=httpx.Response(200, content=BODY))
    r = fetch_url("https://example.com/old", tmp_path)
    assert r["retrieved_url"] == URL
    assert r["canonical_url"] == "https://example.com/old"


@respx.mock
def test_redirect_to_private_host_blocked(tmp_path):
    respx.get("https://example.com/redir").mock(
        return_value=httpx.Response(
            302, headers={"location": "http://169.254.169.254/latest/meta-data"}
        )
    )
    with pytest.raises(FetchBlockedError):
        fetch_url("https://example.com/redir", tmp_path)

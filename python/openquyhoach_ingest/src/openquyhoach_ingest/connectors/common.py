"""Shared helpers for HTTP-API connectors (sitemap/feed/ckan/ogc-api).

Small on purpose — connectors stay self-contained; this only removes the
repeated "GET JSON/XML politely" boilerplate.
"""

from __future__ import annotations

import httpx
from openquyhoach_core.security import check_url_allowed
from openquyhoach_core.settings import get_settings


def http_client(user_agent: str | None = None, verify_tls: bool = True) -> httpx.Client:
    s = get_settings()
    return httpx.Client(
        headers={"User-Agent": user_agent or s.fetch_user_agent, "Accept": "*/*"},
        timeout=s.fetch_timeout_seconds,
        follow_redirects=True,
        verify=verify_tls,
    )


def get_json(
    url: str,
    params: dict | None = None,
    user_agent: str | None = None,
    verify_tls: bool = True,
):
    """GET a JSON endpoint with SSRF validation. Returns parsed body."""
    check_url_allowed(url)
    with http_client(user_agent, verify_tls) as c:
        resp = c.get(url, params=params)
        resp.raise_for_status()
        return resp.json()


def get_xml(url: str, user_agent: str | None = None, verify_tls: bool = True):
    """GET an XML document with SSRF validation. Returns the root element."""
    import xml.etree.ElementTree as ET

    check_url_allowed(url)
    with http_client(user_agent, verify_tls) as c:
        resp = c.get(url)
        resp.raise_for_status()
    return ET.fromstring(resp.content)


def get_text(url: str, user_agent: str | None = None, verify_tls: bool = True) -> str:
    check_url_allowed(url)
    with http_client(user_agent, verify_tls) as c:
        resp = c.get(url)
        resp.raise_for_status()
        return resp.text


def _patterns(discovery: dict, singular: str, plural: str) -> list[str]:
    """Normalise descriptor filter syntax: the schema's single-regex
    ``include``/``exclude`` plus the array forms ``url_include``/
    ``url_exclude`` (additionalProperties allows both)."""
    out: list[str] = []
    single = discovery.get(singular)
    if single:
        out.append(single)
    out.extend(discovery.get(plural) or [])
    return out

"""Connector discovery — sitemap, feed, ckan, ogc_api, html, ogc_wfs —
all HTTP mocked with respx; no network in unit tests."""

from __future__ import annotations

import httpx
import pytest
import respx
from openquyhoach_ingest.connectors.base import SourceConfig, get_connector

pytestmark = pytest.mark.unit

HOST = "https://example.com"


def cfg(source_type: str, **kw) -> SourceConfig:
    return SourceConfig(
        key=f"test/{source_type}",
        name="test",
        source_type=source_type,
        base_url=kw.pop("base_url", HOST),
        discovery=kw.pop("discovery", {}),
        allowed_formats=kw.pop("allowed_formats", []),
        crawl_policy=kw.pop("crawl_policy", {}),
        **kw,
    )


# --- sitemap -------------------------------------------------------------

SITEMAP_INDEX = """<?xml version="1.0"?>
<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <sitemap><loc>{h}/sitemap-1.xml</loc></sitemap>
</sitemapindex>"""

SITEMAP_1 = """<?xml version="1.0"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>{h}/docs/qh-2024.pdf</loc><lastmod>2025-01-01</lastmod></url>
  <url><loc>{h}/docs/other.pdf</loc></url>
  <url><loc>{h}/blog/post-1</loc></url>
</urlset>"""


@respx.mock
def test_sitemap_index_and_filters():
    respx.get(f"{HOST}/robots.txt").mock(
        return_value=httpx.Response(200, text=f"Sitemap: {HOST}/sitemap_index.xml")
    )
    respx.get(f"{HOST}/sitemap_index.xml").mock(
        return_value=httpx.Response(200, text=SITEMAP_INDEX.format(h=HOST))
    )
    respx.get(f"{HOST}/sitemap-1.xml").mock(
        return_value=httpx.Response(200, text=SITEMAP_1.format(h=HOST))
    )
    conn = get_connector("sitemap")
    items = list(
        conn.discover(
            cfg(
                "sitemap",
                discovery={"url_include": ["\\.pdf$"], "url_exclude": ["other"]},
            )
        )
    )
    assert [i.url for i in items] == [f"{HOST}/docs/qh-2024.pdf"]


# --- feed ----------------------------------------------------------------

RSS = """<?xml version="1.0"?>
<rss version="2.0"><channel>
  <item>
    <title>Quyet dinh 123</title>
    <link>{h}/posts/qd-123</link>
    <guid>qd-123</guid>
    <pubDate>Mon, 01 Jan 2024 00:00:00 GMT</pubDate>
    <enclosure url="{h}/files/qd-123.pdf" type="application/pdf"/>
  </item>
  <item>
    <title>No attachment</title>
    <link>{h}/posts/none</link>
    <guid>none</guid>
  </item>
</channel></rss>"""


@respx.mock
def test_feed_enclosures_and_format_filter():
    respx.get(f"{HOST}/feed.xml").mock(return_value=httpx.Response(200, text=RSS.format(h=HOST)))
    conn = get_connector("feed")
    items = list(
        conn.discover(
            cfg(
                "feed",
                discovery={"feed_url": f"{HOST}/feed.xml"},
                allowed_formats=["pdf"],
            )
        )
    )
    # enclosure passes the pdf filter; the bare page link does not
    assert len(items) == 1
    assert items[0].url == f"{HOST}/files/qd-123.pdf"
    assert items[0].identity == "qd-123"


@respx.mock
def test_feed_page_link_fallback_without_format_filter():
    respx.get(f"{HOST}/feed.xml").mock(return_value=httpx.Response(200, text=RSS.format(h=HOST)))
    conn = get_connector("feed")
    items = list(
        conn.discover(cfg("feed", discovery={"feed_url": f"{HOST}/feed.xml"}))
    )
    assert len(items) == 2  # enclosure + page-link fallback
    assert items[1].url == f"{HOST}/posts/none"


# --- ckan ----------------------------------------------------------------

CKAN_SEARCH = {
    "success": True,
    "result": {
        "count": 1,
        "results": [
            {
                "id": "pkg-1",
                "name": "quy-hoach",
                "title": "Quy hoach phan khu",
                "organization": {"title": "So TNMT"},
                "resources": [
                    {"id": "r1", "url": f"{HOST}/data/qhpk.geojson", "format": "GeoJSON", "name": "QHPK"},
                    {"id": "r2", "url": f"{HOST}/data/readme.txt", "format": "TXT"},
                ],
            }
        ],
    },
}


@respx.mock
def test_ckan_package_search_and_format_filter():
    route = respx.get(f"{HOST}/api/3/action/package_search").mock(
        return_value=httpx.Response(200, json=CKAN_SEARCH)
    )
    conn = get_connector("ckan")
    items = list(
        conn.discover(
            cfg(
                "ckan",
                discovery={"package_query": "quy hoach", "formats": ["geojson"]},
            )
        )
    )
    assert [i.url for i in items] == [f"{HOST}/data/qhpk.geojson"]
    assert items[0].identity == "ckan:r1"
    assert items[0].metadata["package_name"] == "quy-hoach"
    assert "fq" in route.calls.last.request.url.params


# --- ogc api features ----------------------------------------------------

OAF_COLLECTIONS = {
    "collections": [
        {"id": "qhpk_sdd", "title": "Quy hoach phan khu SDD", "links": []},
        {"id": "buildings", "title": "Buildings"},
    ]
}


@respx.mock
def test_ogc_api_collection_allowlist():
    respx.get(f"{HOST}/ogc/collections").mock(
        return_value=httpx.Response(200, json=OAF_COLLECTIONS)
    )
    conn = get_connector("ogc_api_features")
    items = list(
        conn.discover(
            cfg(
                "ogc_api_features",
                base_url=f"{HOST}/ogc",
                discovery={"collections": ["qhpk_sdd"]},
            )
        )
    )
    assert len(items) == 1
    assert items[0].url == f"{HOST}/ogc/collections/qhpk_sdd/items"
    assert items[0].identity == "oaf:qhpk_sdd"


# --- html ----------------------------------------------------------------

INDEX = """<html><body>
<ul>
<li><a href="/Uploads/Document/ApproveDecision/1.pdf">QD 1</a><span class="d">2024</span></li>
<li><a href="/Uploads/Document/ApproveDecision/2.pdf">QD 2</a></li>
<li><a href="/news/item">tin tuc</a></li>
<li><a class="next" href="/van-ban/page/2">next</a></li>
</ul></body></html>"""

PAGE2 = """<html><body>
<li><a href="/Uploads/Document/ApproveDecision/3.pdf">QD 3</a></li>
</body></html>"""


@respx.mock
def test_html_index_include_exclude_and_pagination():
    respx.get(f"{HOST}/van-ban").mock(return_value=httpx.Response(200, text=INDEX))
    respx.get(f"{HOST}/van-ban/page/2").mock(return_value=httpx.Response(200, text=PAGE2))
    conn = get_connector("html_index")
    items = list(
        conn.discover(
            cfg(
                "html_index",
                discovery={
                    "index_url": f"{HOST}/van-ban",
                    "link_selector": "a",
                    "include": "ApproveDecision/.*\\.pdf$",
                    "pagination": {"style": "next_link", "next_selector": "a.next", "max_pages": 5},
                },
                allowed_formats=["pdf"],
            )
        )
    )
    urls = [i.url for i in items]
    assert urls == [
        f"{HOST}/Uploads/Document/ApproveDecision/1.pdf",
        f"{HOST}/Uploads/Document/ApproveDecision/2.pdf",
        f"{HOST}/Uploads/Document/ApproveDecision/3.pdf",
    ]
    assert items[0].metadata["page_url"] == f"{HOST}/van-ban"


# --- ogc wfs typename filter ---------------------------------------------

WFS_CAPS = """<?xml version="1.0"?>
<wfs:WFS_Capabilities xmlns:wfs="http://www.opengis.net/wfs/2.0"
    xmlns:ows="http://www.opengis.net/ows/1.1" version="2.0.0">
  <FeatureTypeList>
    <FeatureType><Name>ns:qhpksdd_q1</Name><Title>Zoning Q1</Title>
      <DefaultCRS>urn:ogc:def:crs:EPSG::4326</DefaultCRS></FeatureType>
    <FeatureType><Name>ns:roads</Name><Title>Roads</Title></FeatureType>
    <FeatureType><Name>ns:qhpksdd_q3</Name><Title>Zoning Q3</Title></FeatureType>
  </FeatureTypeList>
</wfs:WFS_Capabilities>"""


@respx.mock
def test_wfs_typename_include_exclude():
    respx.get(f"{HOST}/wfs").mock(
        return_value=httpx.Response(200, text=WFS_CAPS)
    )
    conn = get_connector("ogc_wfs")
    items = list(
        conn.discover(
            cfg(
                "ogc_wfs",
                base_url=f"{HOST}/wfs",
                discovery={"include": "qhpksdd", "exclude": "q3"},
            )
        )
    )
    assert [i.metadata["typename"] for i in items] == ["ns:qhpksdd_q1"]
    assert items[0].suggested_filename == "ns_qhpksdd_q1.geojson"

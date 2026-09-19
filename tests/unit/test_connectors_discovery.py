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


@respx.mock
def test_html_index_param_pagination_includes_index_page():
    """param/path pagination must still scan the bare index page — the
    first result page lives there, not only under ?page=N."""
    def _dispatch(request):
        if request.url.params.get("page") == "1":
            return httpx.Response(200, text=PAGE2)
        return httpx.Response(200, text=INDEX)

    respx.get(f"{HOST}/van-ban").mock(side_effect=_dispatch)
    conn = get_connector("html_index")
    items = list(
        conn.discover(
            cfg(
                "html_index",
                discovery={
                    "index_url": f"{HOST}/van-ban",
                    "link_selector": "a",
                    "include": "ApproveDecision/.*\\.pdf$",
                    "pagination": {"style": "param", "param": "page", "start": 1, "max_pages": 5},
                },
                allowed_formats=["pdf"],
            )
        )
    )
    urls = [i.url for i in items]
    assert f"{HOST}/Uploads/Document/ApproveDecision/1.pdf" in urls  # index page
    assert f"{HOST}/Uploads/Document/ApproveDecision/3.pdf" in urls  # ?page=1


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


# --- arcgis_rest ---------------------------------------------------------

ARCGIS_FIELDS = [
    {"name": "OBJECTID", "type": "esriFieldTypeOID"},
    {"name": "TEN", "type": "esriFieldTypeString"},
]


def _arcgis_service(*layer_ids: int) -> dict:
    return {
        "layers": [{"id": i, "name": f"layer{i}"} for i in layer_ids],
        "mapName": "svc",
    }


def _arcgis_layer_meta(name: str, **over) -> dict:
    meta = {
        "name": name,
        "geometryType": "esriGeometryPolygon",
        "fields": ARCGIS_FIELDS,
        "maxRecordCount": 2,
        "advancedQueryCapabilities": {"supportsPagination": True},
    }
    meta.update(over)
    return meta


@respx.mock
def test_arcgis_multi_service_discovery_and_filters():
    svc_a, svc_b = f"{HOST}/rest/services/QH/A/MapServer", f"{HOST}/rest/services/QH/B/MapServer"
    respx.get(svc_a).mock(return_value=httpx.Response(200, json=_arcgis_service(0, 1)))
    respx.get(svc_b).mock(return_value=httpx.Response(200, json=_arcgis_service(0)))
    respx.get(f"{svc_a}/0").mock(
        return_value=httpx.Response(200, json=_arcgis_layer_meta("QHSDD_NhaTrang"))
    )
    respx.get(f"{svc_a}/1").mock(
        return_value=httpx.Response(200, json=_arcgis_layer_meta("BaseMap_Roads"))
    )
    respx.get(f"{svc_b}/0").mock(
        return_value=httpx.Response(200, json=_arcgis_layer_meta("QHSDD_CamRanh"))
    )
    conn = get_connector("arcgis_rest")
    items = list(
        conn.discover(
            cfg(
                "arcgis_rest",
                base_url="",
                discovery={
                    "services": [svc_a, svc_b],
                    "include": "QHSDD",
                },
            )
        )
    )
    assert [i.metadata["layer_name"] for i in items] == [
        "QHSDD_NhaTrang",
        "QHSDD_CamRanh",
    ]
    assert items[0].url == f"{svc_a}/0/query"
    assert items[0].metadata["oid_field"] == "OBJECTID"
    assert items[0].metadata["max_record_count"] == 2
    assert items[0].metadata["supports_pagination"] is True


def _features(start: int, n: int) -> list[dict]:
    return [
        {
            "type": "Feature",
            "properties": {"OBJECTID": start + i, "TEN": f"f{start + i}"},
            "geometry": {"type": "Point", "coordinates": [0.0, 0.0]},
        }
        for i in range(n)
    ]


@respx.mock
def test_arcgis_fetch_offset_pagination(tmp_path):
    """maxRecordCount=2, server count=3 → two offset pages."""
    base = f"{HOST}/rest/services/QH/A/MapServer"
    calls = []

    def query(req):
        p = req.url.params
        if p.get("returnCountOnly") == "true":
            return httpx.Response(200, json={"count": 3})
        calls.append(int(p["resultOffset"]))
        off = int(p["resultOffset"])
        feats = _features(off, min(2, 3 - off))
        return httpx.Response(200, json={"features": feats})

    respx.get(f"{base}/0/query").mock(side_effect=query)
    conn = get_connector("arcgis_rest")
    from openquyhoach_ingest.connectors.base import DiscoveredItem

    item = DiscoveredItem(
        url=f"{base}/0/query",
        suggested_filename="l.geojson",
        metadata={
            "layer_name": "L",
            "max_record_count": 2,
            "supports_pagination": True,
            "oid_field": "OBJECTID",
        },
    )
    res = conn.fetch(cfg("arcgis_rest"), item, tmp_path)
    import json as _json

    fc = _json.loads(res.local_path.read_text())
    assert [f["properties"]["OBJECTID"] for f in fc["features"]] == [0, 1, 2]
    assert calls == [0, 2]
    assert fc["openquyhoach"]["server_feature_count"] == 3


@respx.mock
def test_arcgis_fetch_oid_fallback_on_pagination_error(tmp_path):
    """Pre-10.3 server: resultOffset rejected → self-heal OID meta + range pages."""
    base = f"{HOST}/rest/services/QH/Old/MapServer"
    respx.get(f"{base}/0").mock(
        return_value=httpx.Response(200, json=_arcgis_layer_meta("Old_Layer"))
    )

    def query(req):
        p = req.url.params
        if p.get("returnCountOnly") == "true":
            return httpx.Response(200, json={"count": 4})
        if "resultOffset" in p:
            return httpx.Response(
                200, json={"error": {"message": "Pagination is not supported."}}
            )
        # OID-range page — server rejects resultRecordCount too
        if "resultRecordCount" in p:
            return httpx.Response(
                200, json={"error": {"message": "Pagination is not supported."}}
            )
        last = int(p["where"].split(">")[1])
        feats = _features(last + 1, min(3, 4 - (last + 1)))
        return httpx.Response(200, json={"features": feats})

    respx.get(f"{base}/0/query").mock(side_effect=query)
    conn = get_connector("arcgis_rest")
    from openquyhoach_ingest.connectors.base import DiscoveredItem

    item = DiscoveredItem(
        url=f"{base}/0/query",
        suggested_filename="old.geojson",
        # stale discovery metadata: no oid_field, claims pagination works
        metadata={"layer_name": "Old_Layer", "supports_pagination": True},
    )
    res = conn.fetch(cfg("arcgis_rest"), item, tmp_path)
    import json as _json

    fc = _json.loads(res.local_path.read_text())
    assert [f["properties"]["OBJECTID"] for f in fc["features"]] == [0, 1, 2, 3]


@respx.mock
def test_arcgis_oid_pages_rejects_order_by(tmp_path):
    """OID path degrades orderByFields + resultRecordCount independently."""
    base = f"{HOST}/rest/services/QH/Old/MapServer"

    def query(req):
        p = req.url.params
        if p.get("returnCountOnly") == "true":
            return httpx.Response(200, json={"count": 4})
        if "resultRecordCount" in p:
            return httpx.Response(
                200, json={"error": {"message": "Pagination is not supported."}}
            )
        if "orderByFields" in p:
            return httpx.Response(
                200,
                json={"error": {"message": "Unable to order results by fields."}},
            )
        last = int(p["where"].split(">")[1])
        feats = _features(last + 1, min(3, 4 - (last + 1)))
        return httpx.Response(200, json={"features": feats})

    respx.get(f"{base}/0/query").mock(side_effect=query)
    conn = get_connector("arcgis_rest")
    from openquyhoach_ingest.connectors.base import DiscoveredItem

    item = DiscoveredItem(
        url=f"{base}/0/query",
        suggested_filename="old.geojson",
        metadata={
            "layer_name": "Old_Layer",
            "supports_pagination": False,
            "oid_field": "OBJECTID",
        },
    )
    res = conn.fetch(cfg("arcgis_rest"), item, tmp_path)
    import json as _json

    fc = _json.loads(res.local_path.read_text())
    assert [f["properties"]["OBJECTID"] for f in fc["features"]] == [0, 1, 2, 3]

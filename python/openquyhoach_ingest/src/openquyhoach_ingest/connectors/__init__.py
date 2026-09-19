"""Connector registry. Connectors are keyed by SourceType and implement
discover/fetch/inspect; normalize+emit happen in the pipeline."""

# side-effect imports register connectors
from . import (
    arcgis_rest,  # noqa: F401
    ckan,  # noqa: F401
    feed,  # noqa: F401
    file,  # noqa: F401
    html,  # noqa: F401
    http,  # noqa: F401
    ogc,  # noqa: F401
    ogc_api,  # noqa: F401
    planning_portal,  # noqa: F401
    sitemap,  # noqa: F401
)
from .base import Connector, DiscoveredItem, FetchResult, get_connector, register

__all__ = ["Connector", "DiscoveredItem", "FetchResult", "get_connector", "register"]

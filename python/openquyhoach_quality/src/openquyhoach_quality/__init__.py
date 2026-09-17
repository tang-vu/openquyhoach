"""OpenQuyHoach quality engine.

Rules are individually addressable via stable codes (``QH-GEOM-INVALID`` …)
and produce :class:`Finding` objects — persisted as ``quality_observations``
when run inside the ingest pipeline, or returned as a report for the CLI.
"""

from .engine import Finding, Rule, rule_catalog, run_rules

__all__ = ["Finding", "Rule", "rule_catalog", "run_rules"]

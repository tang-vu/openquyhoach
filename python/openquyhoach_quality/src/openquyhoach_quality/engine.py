"""Rule engine core.

A rule is a function over a :class:`ValidationContext` yielding findings.
Rules never throw — a crashing rule becomes a ``QH-RULE-ERROR`` finding.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any

from openquyhoach_core.enums import QualitySeverity


@dataclass
class Finding:
    rule_code: str
    severity: str  # QualitySeverity value
    message: str
    target_type: str  # dataset|layer|feature
    target_ref: str | None = None  # layer name / feature key
    geometry_wkt: str | None = None  # offending geometry, when spatial
    evidence: dict[str, Any] = field(default_factory=dict)


@dataclass
class Rule:
    code: str
    description: str
    default_severity: str
    check: Callable[[ValidationContext], Iterable[Finding]]
    applies_to: str = "feature"  # feature|layer|dataset


@dataclass
class ValidationContext:
    """Everything rules can inspect for one dataset being validated."""

    dataset_id: str | None = None
    dataset_group: str | None = None
    dataset_type: str | None = None
    derivation_level: str | None = None
    original_crs: dict | None = None
    artifact_sha256: str | None = None
    artifact_recorded_sha256: str | None = None  # as stored at download time
    layers: list[LayerPayload] = field(default_factory=list)
    required_attributes: dict[str, list[str]] = field(default_factory=dict)
    # per-layer required property names, from source descriptor mapping
    planning_version: dict | None = None  # {approval_date, effective_from, effective_to}
    meta: dict = field(default_factory=dict)


@dataclass
class LayerPayload:
    name: str
    geometry_type: str | None
    expected_geometry_type: str | None
    features: list[FeaturePayload]


@dataclass
class FeaturePayload:
    key: str | None
    geometry: Any  # shapely geom or None
    properties: dict
    classification: str | None = None
    valid_from: Any = None
    valid_to: Any = None


_REGISTRY: dict[str, Rule] = {}


def rule(code: str, description: str, severity: str, applies_to: str = "feature"):
    def deco(fn: Callable[[ValidationContext], Iterable[Finding]]):
        _REGISTRY[code] = Rule(code, description, severity, fn, applies_to)
        return fn

    return deco


_RULE_MODULES = (
    "openquyhoach_quality.rules_geometry",
    "openquyhoach_quality.rules_meta",
)
_rules_loaded = False


def _ensure_rules() -> None:
    """Import rule modules once so ``@rule`` registrations land in _REGISTRY.

    Without this, callers who only import ``engine`` would see an empty
    registry and validation would silently pass everything.
    """
    global _rules_loaded
    if _rules_loaded:
        return
    import importlib

    for mod in _RULE_MODULES:
        importlib.import_module(mod)
    _rules_loaded = True


def rule_catalog() -> dict[str, dict[str, str]]:
    _ensure_rules()
    return {
        code: {
            "description": r.description,
            "default_severity": r.default_severity,
            "applies_to": r.applies_to,
        }
        for code, r in sorted(_REGISTRY.items())
    }


def run_rules(
    ctx: ValidationContext,
    *,
    only: list[str] | None = None,
    skip: list[str] | None = None,
) -> list[Finding]:
    _ensure_rules()
    findings: list[Finding] = []
    for code, r in sorted(_REGISTRY.items()):
        if only and code not in only:
            continue
        if skip and code in skip:
            continue
        try:
            findings.extend(r.check(ctx))
        except Exception as exc:
            findings.append(
                Finding(
                    rule_code="QH-RULE-ERROR",
                    severity=QualitySeverity.ERROR.value,
                    message=f"rule {code} crashed: {exc}",
                    target_type="dataset",
                    evidence={"rule": code},
                )
            )
    return findings


def summarize(findings: list[Finding]) -> dict:
    by_sev: dict[str, int] = {}
    by_rule: dict[str, int] = {}
    for f in findings:
        by_sev[f.severity] = by_sev.get(f.severity, 0) + 1
        by_rule[f.rule_code] = by_rule.get(f.rule_code, 0) + 1
    return {
        "total": len(findings),
        "by_severity": by_sev,
        "by_rule": by_rule,
        "has_errors": any(
            f.severity in (QualitySeverity.ERROR.value, QualitySeverity.CRITICAL.value)
            for f in findings
        ),
    }


def report_json(findings: list[Finding]) -> str:
    return json.dumps(
        {
            "summary": summarize(findings),
            "findings": [
                {
                    "rule_code": f.rule_code,
                    "severity": f.severity,
                    "message": f.message,
                    "target_type": f.target_type,
                    "target_ref": f.target_ref,
                    "geometry_wkt": f.geometry_wkt,
                    "evidence": f.evidence,
                }
                for f in findings
            ],
        },
        ensure_ascii=False,
        indent=2,
    )


def report_text(findings: list[Finding]) -> str:
    s = summarize(findings)
    lines = [
        f"Validation: {s['total']} finding(s) "
        f"({', '.join(f'{k}={v}' for k, v in sorted(s['by_severity'].items())) or 'clean'})"
    ]
    for f in findings:
        ref = f"[{f.target_type}:{f.target_ref}]" if f.target_ref else f"[{f.target_type}]"
        lines.append(f"  {f.severity.upper():8} {f.rule_code:24} {ref} {f.message}")
    return "\n".join(lines)

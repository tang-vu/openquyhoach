"""Attribute / temporal / provenance rules."""

from __future__ import annotations

import re
from collections.abc import Iterable
from datetime import date, datetime

from openquyhoach_core.enums import DerivationLevel, QualitySeverity

from .engine import Finding, ValidationContext, rule

_DATEISH = re.compile(r"^\d{4}(-\d{2})?(-\d{2})?")


def _parse_date(v) -> date | None:
    if v is None:
        return None
    if isinstance(v, date) and not isinstance(v, datetime):
        return v
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, str) and _DATEISH.match(v.strip()):
        try:
            return date.fromisoformat(v.strip()[:10])
        except ValueError:
            return None
    return None


def _all_features(ctx: ValidationContext):
    for layer in ctx.layers:
        for f in layer.features:
            yield layer, f


@rule(
    "QH-ATTR-REQUIRED",
    "Required attribute missing or empty (per source mapping)",
    QualitySeverity.ERROR.value,
)
def r_required(ctx: ValidationContext) -> Iterable[Finding]:
    for layer in ctx.layers:
        required = ctx.required_attributes.get(layer.name, [])
        if not required:
            continue
        for f in layer.features:
            missing = [
                k
                for k in required
                if f.properties.get(k) in (None, "", 0) and k not in f.properties
            ]
            missing += [k for k in required if k in f.properties and f.properties[k] in (None, "")]
            if missing:
                yield Finding(
                    "QH-ATTR-REQUIRED",
                    QualitySeverity.ERROR.value,
                    f"missing required attribute(s): {', '.join(sorted(set(missing)))}",
                    "feature",
                    f.key,
                    evidence={"layer": layer.name},
                )


@rule(
    "QH-TIME-INVALID",
    "Unparseable or impossible date value",
    QualitySeverity.ERROR.value,
)
def r_time_invalid(ctx: ValidationContext) -> Iterable[Finding]:
    for layer, f in _all_features(ctx):
        for field_name in ("valid_from", "valid_to"):
            v = getattr(f, field_name, None) or f.properties.get(field_name)
            if v is not None and _parse_date(v) is None:
                yield Finding(
                    "QH-TIME-INVALID",
                    QualitySeverity.ERROR.value,
                    f"unparseable {field_name}: {v!r}",
                    "feature",
                    f.key,
                    evidence={"layer": layer.name},
                )
    pv = ctx.planning_version or {}
    for field_name in ("approval_date", "effective_from", "effective_to", "signed_date"):
        v = pv.get(field_name)
        if v is not None and _parse_date(v) is None:
            yield Finding(
                "QH-TIME-INVALID",
                QualitySeverity.ERROR.value,
                f"planning version has unparseable {field_name}: {v!r}",
                "dataset",
                ctx.dataset_id,
            )


@rule(
    "QH-TIME-ORDER",
    "Temporal ordering is impossible (e.g. effective_to < effective_from)",
    QualitySeverity.ERROR.value,
)
def r_time_order(ctx: ValidationContext) -> Iterable[Finding]:
    pv = ctx.planning_version or {}
    ef, et = _parse_date(pv.get("effective_from")), _parse_date(pv.get("effective_to"))
    if ef and et and et < ef:
        yield Finding(
            "QH-TIME-ORDER",
            QualitySeverity.ERROR.value,
            f"effective_to {et} precedes effective_from {ef}",
            "dataset",
            ctx.dataset_id,
        )
    ad, efd = _parse_date(pv.get("approval_date")), ef
    if ad and efd and efd < ad:
        yield Finding(
            "QH-TIME-ORDER",
            QualitySeverity.WARNING.value,
            "effective_from precedes approval_date — verify",
            "dataset",
            ctx.dataset_id,
        )
    for layer, f in _all_features(ctx):
        vf, vt = _parse_date(f.valid_from), _parse_date(f.valid_to)
        if vf and vt and vt < vf:
            yield Finding(
                "QH-TIME-ORDER",
                QualitySeverity.ERROR.value,
                "feature valid_to precedes valid_from",
                "feature",
                f.key,
                evidence={"layer": layer.name},
            )


@rule(
    "QH-ARTIFACT-HASH-MISMATCH",
    "Current artifact bytes do not match the checksum recorded at download",
    QualitySeverity.CRITICAL.value,
    applies_to="dataset",
)
def r_hash(ctx: ValidationContext) -> Iterable[Finding]:
    if (
        ctx.artifact_sha256
        and ctx.artifact_recorded_sha256
        and (ctx.artifact_sha256 != ctx.artifact_recorded_sha256)
    ):
        yield Finding(
            "QH-ARTIFACT-HASH-MISMATCH",
            QualitySeverity.CRITICAL.value,
            "artifact content changed since download — provenance violated",
            "dataset",
            ctx.dataset_id,
            evidence={
                "recorded": ctx.artifact_recorded_sha256,
                "actual": ctx.artifact_sha256,
            },
        )


@rule(
    "QH-PROV-ORPHAN",
    "Derived/published data lacks provenance inputs",
    QualitySeverity.ERROR.value,
    applies_to="dataset",
)
def r_orphan(ctx: ValidationContext) -> Iterable[Finding]:
    derived = {
        DerivationLevel.DERIVED_HUMAN_REVIEWED.value,
        DerivationLevel.DERIVED_MACHINE_REVIEWED.value,
        DerivationLevel.DERIVED_MACHINE_UNREVIEWED.value,
    }
    if ctx.derivation_level in derived and not ctx.meta.get("has_provenance", False):
        yield Finding(
            "QH-PROV-ORPHAN",
            QualitySeverity.ERROR.value,
            f"dataset is {ctx.derivation_level} but records no provenance inputs",
            "dataset",
            ctx.dataset_id,
        )


@rule(
    "QH-AUTH-MISSING",
    "No issuing authority recorded for an official-level dataset",
    QualitySeverity.ERROR.value,
    applies_to="dataset",
)
def r_authority(ctx: ValidationContext) -> Iterable[Finding]:
    official = {
        DerivationLevel.OFFICIAL_VECTOR.value,
        DerivationLevel.OFFICIAL_RASTER.value,
        DerivationLevel.OFFICIAL_DOCUMENT.value,
    }
    if ctx.derivation_level in official and not ctx.meta.get("authority"):
        yield Finding(
            "QH-AUTH-MISSING",
            QualitySeverity.ERROR.value,
            "official-level dataset has no authority attribution",
            "dataset",
            ctx.dataset_id,
        )


@rule(
    "QH-META-CODE-MISMATCH",
    "Planning/file codes disagree across records and documents",
    QualitySeverity.WARNING.value,
    applies_to="dataset",
)
def r_code_mismatch(ctx: ValidationContext) -> Iterable[Finding]:
    pv = ctx.planning_version or {}
    rec_code = (pv.get("record_code") or "").strip()
    doc_code = (pv.get("document_number") or "").strip()
    dec = (pv.get("approval_decision_number") or "").strip()
    if dec and doc_code and dec != doc_code:
        yield Finding(
            "QH-META-CODE-MISMATCH",
            QualitySeverity.WARNING.value,
            f"decision number {dec!r} != document number {doc_code!r}",
            "dataset",
            ctx.dataset_id,
        )
    if rec_code and dec and rec_code == dec:
        yield Finding(
            "QH-META-CODE-MISMATCH",
            QualitySeverity.WARNING.value,
            "record code identical to decision number — verify extraction",
            "dataset",
            ctx.dataset_id,
        )


@rule(
    "QH-VN-GROUP-UNKNOWN",
    "Dataset group does not map onto the VN planning GIS groupings",
    QualitySeverity.INFO.value,
    applies_to="dataset",
)
def r_vn_group(ctx: ValidationContext) -> Iterable[Finding]:
    if ctx.dataset_group == "other":
        yield Finding(
            "QH-VN-GROUP-UNKNOWN",
            QualitySeverity.INFO.value,
            "dataset group is 'other' — map it to NenDiaHinh/HienTrang/QuyHoach/MocGioi "
            "for VN-framework compatibility",
            "dataset",
            ctx.dataset_id,
        )

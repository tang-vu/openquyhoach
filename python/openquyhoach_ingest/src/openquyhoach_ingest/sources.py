"""Source registry: YAML descriptors under sources/<jurisdiction>/<name>.yaml,
validated against a JSON Schema, synced into the `sources` table."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator
from openquyhoach_core.db import session_scope
from openquyhoach_core.logging import get_logger
from openquyhoach_core.models import Authority, Source
from openquyhoach_core.settings import get_settings
from openquyhoach_core.text import vn_normalize

from .connectors.base import SourceConfig

log = get_logger(__name__)

SCHEMA_PATH = (
    Path(__file__).resolve().parents[4] / "sources" / "_schema" / "source-descriptor.schema.json"
)


@dataclass
class DescriptorIssue:
    path: str
    message: str


def _schema() -> Draft202012Validator:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    return Draft202012Validator(schema)


def sources_root(root: str | Path | None = None) -> Path:
    if root:
        return Path(root)
    return Path(get_settings().sources_dir)


def load_descriptor(path: str | Path) -> dict:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path}: descriptor must be a mapping")
    return data


def validate_descriptor(path: str | Path) -> list[DescriptorIssue]:
    issues: list[DescriptorIssue] = []
    try:
        data = load_descriptor(path)
    except Exception as exc:
        return [DescriptorIssue(str(path), f"unparseable YAML: {exc}")]
    for err in _schema().iter_errors(data):
        issues.append(DescriptorIssue(str(path), f"{list(err.absolute_path)}: {err.message}"))
    key = data.get("key", "")
    expected = Path(key).name
    if expected and Path(path).stem != expected:
        issues.append(
            DescriptorIssue(str(path), f"filename {Path(path).name!r} should be {expected}.yaml")
        )
    return issues


def iter_descriptors(root: str | Path | None = None) -> list[Path]:
    r = sources_root(root)
    return sorted(p for p in r.rglob("*.yaml") if "_schema" not in p.parts)


def validate_all(root: str | Path | None = None) -> list[DescriptorIssue]:
    issues: list[DescriptorIssue] = []
    seen_keys: dict[str, Path] = {}
    for path in iter_descriptors(root):
        issues.extend(validate_descriptor(path))
        try:
            key = load_descriptor(path).get("key")
        except Exception:
            continue
        if not isinstance(key, str) or not key:
            continue
        if key in seen_keys:
            issues.append(
                DescriptorIssue(str(path), f"duplicate key {key!r} also in {seen_keys[key]}")
            )
        else:
            seen_keys[key] = path
    return issues


def to_config(key: str, data: dict) -> SourceConfig:
    _top = {
        "key", "name", "source_type", "base_url", "discovery", "parser",
        "crawl_policy", "allowed_formats", "jurisdiction", "authority",
        "rights", "enabled", "priority", "refresh", "rate_limit",
        "canonical_url",
    }
    return SourceConfig(
        key=key,
        name=data["name"],
        source_type=data["source_type"],
        base_url=data.get("base_url"),
        discovery=data.get("discovery") or {},
        parser=data.get("parser") or {},
        crawl_policy=data.get("crawl_policy") or {},
        allowed_formats=data.get("allowed_formats") or [],
        jurisdiction=data.get("jurisdiction"),
        authority=data.get("authority"),
        rights=data.get("rights") or {},
        enabled=data.get("enabled", True),
        priority=int(data.get("priority") or 100),
        refresh=data.get("refresh") or {},
        rate_limit=data.get("rate_limit") or {},
        canonical_url=data.get("canonical_url") or {},
        meta={k: v for k, v in data.items() if k not in _top},
    )


def load_config(path_or_key: str, root: str | Path | None = None) -> SourceConfig:
    """Load by descriptor path or registry key."""
    p = Path(path_or_key)
    if p.exists():
        data = load_descriptor(p)
        return to_config(data["key"], data)
    for d in iter_descriptors(root):
        data = load_descriptor(d)
        if data.get("key") == path_or_key:
            return to_config(data["key"], data)
    raise KeyError(f"no source descriptor for {path_or_key!r}")


def descriptor_hash(data: dict) -> str:
    return hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def _admin_unit_id(s, data: dict):
    """Best-effort link to an existing administrative_units row.

    Never fabricates units: admin_codes are matched against `official_code`
    first, then the jurisdiction label against `normalized_name`. A miss
    leaves the FK empty — coverage stays honest about what is unmapped.
    """
    from openquyhoach_core.models import AdministrativeUnit

    codes = data.get("admin_codes") or {}
    for key in ("commune", "district", "province"):
        code = (codes.get(key) or "").strip()
        if code:
            unit = (
                s.query(AdministrativeUnit)
                .filter(AdministrativeUnit.official_code == code)
                .order_by(AdministrativeUnit.valid_to.desc().nulls_first())
                .first()
            )
            if unit is not None:
                return unit.id
    jurisdiction = data.get("jurisdiction")
    if jurisdiction:
        unit = (
            s.query(AdministrativeUnit)
            .filter(AdministrativeUnit.normalized_name == vn_normalize(jurisdiction))
            .first()
        )
        if unit is not None:
            return unit.id
    return None


def upsert_descriptor_row(s, data: dict) -> tuple[Source, bool]:
    """Insert or update the `sources` row for one parsed descriptor.

    Returns (source_row, created?). The descriptor is the *definition*;
    runtime state lives in the crawl tables, never here.
    """
    key = data["key"]
    existing = s.query(Source).filter_by(source_key=key).one_or_none()
    authority_id = None
    if data.get("authority"):
        auth_name = data["authority"]
        auth = (
            s.query(Authority)
            .filter_by(normalized_name=vn_normalize(auth_name))
            .one_or_none()
        )
        if auth is None:
            auth = Authority(
                canonical_name=auth_name,
                normalized_name=vn_normalize(auth_name),
                authority_type=data.get("meta", {}).get("authority_type", "unknown"),
                jurisdiction=data.get("jurisdiction"),
            )
            s.add(auth)
            s.flush()
        authority_id = auth.id
    rights = data.get("rights") or {}
    row_data = dict(
        authority_id=authority_id,
        name=data["name"],
        source_type=data["source_type"],
        base_url=data.get("base_url"),
        jurisdiction=data.get("jurisdiction"),
        terms_url=data.get("terms_url"),
        rights_statement=rights.get("rights_statement"),
        license=rights.get("license"),
        redistribution_status=rights.get("redistribution_status", "unknown"),
        crawl_policy=data.get("crawl_policy") or {},
        descriptor=data,
        enabled=data.get("enabled", True),
        priority=int(data.get("priority") or 100),
        admin_unit_id=_admin_unit_id(s, data),
    )
    if existing is None:
        existing = Source(source_key=key, **row_data)
        s.add(existing)
        s.flush()
        return existing, True
    for k, v in row_data.items():
        setattr(existing, k, v)
    s.flush()
    return existing, False


def find_descriptor_path(source_key: str, root: str | Path | None = None) -> Path | None:
    for d in iter_descriptors(root):
        try:
            if load_descriptor(d).get("key") == source_key:
                return d
        except Exception:
            continue
    return None


def ensure_source_row(s, source_key: str, root: str | Path | None = None) -> Source | None:
    """Make sure the `sources` row for `source_key` exists — upserting from
    its descriptor when missing or stale. Returns None when no descriptor
    file exists for the key."""
    path = find_descriptor_path(source_key, root)
    if path is None:
        return s.query(Source).filter_by(source_key=source_key).one_or_none()
    row, _ = upsert_descriptor_row(s, load_descriptor(path))
    return row


def sync_sources(root: str | Path | None = None) -> dict:
    """Upsert descriptors into the DB. Returns counts."""
    created = updated = disabled = 0
    with session_scope() as s:
        for path in iter_descriptors(root):
            data = load_descriptor(path)
            _, was_created = upsert_descriptor_row(s, data)
            if was_created:
                created += 1
            else:
                updated += 1
                if not data.get("enabled", True):
                    disabled += 1
        log.info("sources.synced", created=created, updated=updated)
    return {"created": created, "updated": updated, "disabled": disabled}

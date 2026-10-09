import type { FeatureHit } from "./api";

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function textFields(
  value: Record<string, unknown>,
  required: string[],
  nullable: string[] = [],
) {
  return (
    required.every((key) => typeof value[key] === "string") &&
    nullable.every(
      (key) => value[key] === null || typeof value[key] === "string",
    )
  );
}

function optionalRecord(
  value: unknown,
  required: string[],
  nullable: string[] = [],
) {
  return (
    value == null || (isRecord(value) && textFields(value, required, nullable))
  );
}

function isFeatureHit(value: unknown): value is FeatureHit {
  if (
    !isRecord(value) ||
    !textFields(
      value,
      [
        "feature_id",
        "layer",
        "dataset_id",
        "derivation_level",
        "review_status",
      ],
      ["classification"],
    ) ||
    !isRecord(value.properties) ||
    typeof value.distance_m !== "number" ||
    !Number.isFinite(value.distance_m) ||
    !isRecord(value.provenance)
  )
    return false;

  const p = value.provenance;
  return (
    optionalRecord(p.dataset, ["id"], ["name"]) &&
    optionalRecord(p.layer, ["id", "name"]) &&
    (p.derivation_level == null || typeof p.derivation_level === "string") &&
    (p.review_status == null || typeof p.review_status === "string") &&
    optionalRecord(
      p.planning_version,
      ["id", "legal_status"],
      ["label", "approval_decision_number", "approval_date"],
    ) &&
    optionalRecord(
      p.artifact,
      ["id", "sha256"],
      ["filename", "retrieved_at", "canonical_url"],
    ) &&
    optionalRecord(p.source, ["key", "name"], ["base_url"])
  );
}

/** An unavailable/malformed response must never become a coverage claim. */
export function isPointQueryResponse(
  value: unknown,
): value is { hits: FeatureHit[] } {
  return (
    isRecord(value) &&
    Array.isArray(value.hits) &&
    value.hits.every(isFeatureHit)
  );
}

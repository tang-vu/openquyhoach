import type { api } from "./api";

export type RecordDetail = Awaited<ReturnType<typeof api.recordDetail>>;
export type VersionMetadata = Awaited<ReturnType<typeof api.versionDetail>>;
export const object = (value: unknown): value is Record<string, unknown> =>
  value !== null && typeof value === "object" && !Array.isArray(value);
const text = (value: unknown) => typeof value === "string" && value.length > 0;
const identifier = (value: unknown) => typeof value === "string" && /^[a-zA-Z0-9][a-zA-Z0-9_-]*$/.test(value);
const nullableText = (value: unknown) => value === null || typeof value === "string";
const strings = (value: Record<string, unknown>, keys: string[]) => keys.every(key => text(value[key]));
const nullable = (value: Record<string, unknown>, keys: string[]) => keys.every(key => nullableText(value[key]));
function entries(value: unknown, valid: (entry: Record<string, unknown>) => boolean) {
  if (!Array.isArray(value)) return false;
  const ids = new Set<string>();
  return value.every(entry => {
    if (!object(entry) || !identifier(entry.id) || ids.has(entry.id as string) || !valid(entry)) return false;
    ids.add(entry.id as string);
    return true;
  });
}
function version(value: Record<string, unknown>, recordId: string) {
  return identifier(value.id) && identifier(value.planning_record_id) && strings(value, ["version_kind", "legal_status"]) &&
    value.planning_record_id === recordId &&
    nullable(value, ["version_label", "approval_decision_number", "approval_date"]);
}

export function assertRecordDetail(value: unknown, recordId: string): asserts value is RecordDetail {
  if (!object(value) || !identifier(recordId) || value.id !== recordId || !strings(value, ["title", "status"]) ||
    !nullable(value, ["planning_type", "scale", "jurisdiction"]) ||
    !entries(value.versions, entry => version(entry, recordId)))
    throw new Error("Invalid record metadata or record identity does not match the selection.");
}

export function assertVersionMetadata(value: unknown, recordId: string, versionId: string): asserts value is VersionMetadata {
  if (!object(value) || value.id !== versionId || !version(value, recordId) ||
    (value.record !== undefined && (!object(value.record) || value.record.id !== recordId)) ||
    !entries(value.datasets, entry => strings(entry, ["dataset_group", "dataset_type", "derivation_level", "review_status", "quality_state"]) &&
      nullableText(entry.name) && typeof entry.published === "boolean" &&
      (entry.planning_version_id === undefined || entry.planning_version_id === versionId)) ||
    !entries(value.documents, entry => entry.planning_version_id === versionId &&
      nullable(entry, ["document_type", "document_number", "title", "signed_date", "issuing_authority", "artifact_id"]) &&
      (entry.page_count === null || (Number.isInteger(entry.page_count) && Number(entry.page_count) >= 0))) ||
    !entries(value.publications, entry => strings(entry, ["status"]) &&
      nullable(entry, ["published_at", "checksum_sha256"]) &&
      (entry.planning_version_id === undefined || entry.planning_version_id === versionId)))
    throw new Error("Invalid version metadata or version identity does not match the selection.");
}

export function assertManifest(value: unknown, recordId: string, versionId: string): asserts value is Record<string, unknown> {
  if (!object(value) || value.schema_version !== "oqh.manifest/1" ||
    value.planning_record !== recordId || value.planning_version !== versionId ||
    ![value.sources, value.datasets, value.artifacts].every(items => Array.isArray(items) && items.every(object)) ||
    !text(value.disclaimer))
    throw new Error("Invalid manifest structure, schema, or record/version identity.");
}

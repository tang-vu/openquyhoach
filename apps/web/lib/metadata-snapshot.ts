import { assertManifest, assertRecordDetail, assertVersionMetadata } from "./metadata-snapshot-validation";

const copy = <T,>(value: T): T => JSON.parse(JSON.stringify(value));
export type MetadataSnapshot = Awaited<ReturnType<typeof prepareMetadataSnapshot>>;

/** Capture metadata values only; no source files, tiles or provider requests. */
export async function prepareMetadataSnapshot(
  recordId: string, versionId: string, record: unknown, version: unknown,
  loadManifest: (publicationId: string) => Promise<unknown>,
  capturedAt = new Date().toISOString(),
) {
  assertRecordDetail(record, recordId);
  assertVersionMetadata(version, recordId, versionId);
  if (!record.versions.some(item => item.id === versionId))
    throw new Error("Version identity does not match the selected record's versions.");
  // Freeze the input values before any asynchronous manifest request completes.
  const recordValue = copy(record), versionValue = copy(version);
  const manifests = await Promise.all(versionValue.publications.map(async publication => {
    try {
      const value = await loadManifest(publication.id);
      assertManifest(value, recordId, versionId);
      return { publication_id: publication.id, status: "available" as const, value: copy(value), error: null };
    } catch (error) {
      return { publication_id: publication.id, status: "unavailable" as const, value: null,
        error: error instanceof Error ? error.message : String(error) };
    }
  }));
  const availability = {
    data_class: recordValue.data_class ?? "unknown",
    publication_manifests: manifests.length === 0 ? "none" as const :
      manifests.some(item => item.status === "unavailable") ? "incomplete" as const : "available" as const,
  };
  const limitations = [
    "Metadata captured from API responses; not a verified or complete provenance graph. Sources were not rechecked.",
    "captured_at is the start of local preparation, not source freshness. Separate API responses may have been retrieved at different times; this is not an atomic server snapshot.",
    "Missing fields remain absent and nulls remain null; missing provenance must not be inferred.",
    "Manifest JSON values are preserved, not original bytes or signatures. Publication checksum_sha256 refers to PMTiles bytes, not this snapshot or manifest JSON.",
    "Source document and tile payloads are not fetched. Unrelated map and point-query/location state is not added to these API metadata values.",
  ];
  if (availability.publication_manifests === "none") limitations.push("No publication manifests are available for this version.");
  if (availability.publication_manifests === "incomplete") limitations.push("Some publication manifests are unavailable; each failure is listed explicitly.");
  if (availability.data_class === "synthetic" || availability.data_class === "mixed")
    limitations.push("This record includes synthetic/demo material with no real-world meaning.");
  return {
    schema_version: 1,
    captured_at: capturedAt,
    description: "OpenQuyHoach record/version metadata captured from API responses.",
    disclaimer: "OpenQuyHoach does not certify the legal validity of any plan. Confirm with the responsible authority and original documents.",
    selection: { record_id: recordId, version_id: versionId },
    record: recordValue, version: versionValue, manifests, availability, limitations,
  };
}

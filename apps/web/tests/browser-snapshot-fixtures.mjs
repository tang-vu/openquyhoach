import { dataset, detail, publication, record, recordDetail } from "./browser-fixtures.mjs";

// Deliberately rich synthetic metadata; none of these values is legal evidence.
export function snapshotRecord(id = "A") {
  return {
    ...recordDetail(id),
    metadata_origin: "derived_machine",
    license: null,
    redistribution_status: "unknown",
    source_metadata: { canonical_url: "https://synthetic.invalid/record", unknown: null },
    extra_record_field: { retained: true, values: [null, 0, false, ""] },
  };
}

export function snapshotVersion(id = "A1", { unpublished = false } = {}) {
  const base = detail(id);
  return {
    ...base,
    record: record(id[0]),
    effective_from: "2020-01-01",
    effective_to: null,
    supersedes_version_id: id === "A2" ? "A1" : null,
    metadata_origin: "unknown",
    source_disclaimer: "Synthetic metadata only; verify legal meaning with the authority.",
    extra_version_field: ["preserve me", { unknown: null }],
    datasets: [
      { ...dataset(id, "vector"), derivation_level: "official_vector", review_status: "approved",
        planning_version_id: id, source_artifact_id: `artifact-${id}-vector`,
        original_format: "GPKG", original_crs: "EPSG:4326",
        source: { license: "synthetic-license", redistribution_status: "restricted" },
        metadata_origin: "official" },
      { ...dataset(id, "raster"), derivation_level: "derived_manual", review_status: "unreviewed",
        planning_version_id: id, source_artifact_id: `artifact-${id}-raster`,
        original_format: "GeoTIFF", original_crs: null,
        source: { license: null, redistribution_status: "unknown" },
        metadata_origin: null, extra_dataset_field: false },
      { ...dataset(id, "metadata"), name: null, published: false,
        planning_version_id: id, source_artifact_id: null, original_format: null, original_crs: null,
        derivation_level: "derived_machine", review_status: "unknown" },
    ],
    documents: [
      { ...base.documents[0], artifact_id: `artifact-${id}`, metadata_origin: "derived_machine",
        field_origins: { title: "derived_machine", document_number: "unknown", signed_date: null },
        candidate_codes: [{ code: "DEMO", confidence: null }],
        source_url: "https://synthetic.invalid/do-not-download.pdf", rights: "restricted" },
      { ...base.documents[0], id: `document-${id}-unknown`, title: null,
        document_number: null, metadata_origin: null, license: null,
        field_origins: null,
        source: { redistribution_status: "unknown" }, extra_document_field: [0, false, null] },
    ],
    publications: unpublished ? [] : [
      { ...publication(id), extra_publication_field: { retained: true } },
      { ...publication(id), id: `publication-${id}-second`, checksum_sha256: null,
        published_at: null, extra_publication_field: null },
    ],
  };
}

export function snapshotManifest(id = "A1", marker = "primary") {
  return {
    schema_version: "oqh.manifest/1",
    planning_record: id[0],
    planning_version: id,
    sources: [
      { key: "synthetic-source", base_url: "https://synthetic.invalid/",
        license: "synthetic-license", redistribution_status: "restricted" },
      { key: "unknown-source", license: null, redistribution_status: "unknown" },
    ],
    datasets: [
      { id: `vector-${id}`, derivation_level: "official_vector", review_status: "approved" },
      { id: `raster-${id}`, derivation_level: "derived_manual", review_status: "unreviewed" },
    ],
    artifacts: [{ id: `artifact-${id}`, sha256: "a".repeat(64), canonical_url: null,
      retrieved_at: null, filename: "synthetic.pdf", license: null }],
    disclaimer: "Synthetic fixture, not authoritative legal advice or source redistribution permission.",
    pmtiles_sha256: "0".repeat(64),
    arbitrary_manifest_field: { marker, null_value: null, unknown: "unknown", nested: [false, 0] },
  };
}

export const publicationManifestPath = (id) => `/v1/publications/${id}/manifest.json`;

import { describe, expect, it, vi } from "vitest";
import { prepareMetadataSnapshot } from "@/lib/metadata-snapshot";
import { detail, recordDetail } from "./navigation-support";

const manifest = (record = "A", version = "A1") => ({
  schema_version: "oqh.manifest/1", planning_record: record, planning_version: version,
  sources: [{ key: "demo/snapshot", rights_statement: "Synthetic only", license: null }],
  datasets: [], artifacts: [{ sha256: "0".repeat(64), canonical_url: null }],
  disclaimer: "Synthetic fixture; no real-world meaning.", pmtiles_sha256: null,
});

describe("metadata captured from the selected API responses", () => {
  it("keeps every returned entry and metadata value, including unknowns and caveats", async () => {
    const record = { ...recordDetail("A"), title: "Fresh record metadata", data_class: "mixed" as const };
    const version = { ...detail("A1"), metadata_origin: "derived_machine",
      field_origins: { approval_date: "unknown" }, rights: { redistribution_status: "unknown" } };
    version.datasets.push({ ...version.datasets[0], id: "unpublished", published: false });
    version.documents.push({ ...version.documents[0], id: "second-document" });
    version.publications.push({ ...version.publications[0], id: "second-publication" });
    const value = manifest();
    const load = vi.fn(async (_publicationId: string) => value);
    const snapshot = await prepareMetadataSnapshot("A", "A1", record, version, load, "2026-10-09T00:00:00.000Z");
    expect(snapshot.record).toEqual(record);
    expect(snapshot.version).toEqual(version);
    expect(snapshot.selection).toEqual({ record_id: "A", version_id: "A1" });
    expect(snapshot.captured_at).toBe("2026-10-09T00:00:00.000Z");
    expect(snapshot.availability.publication_manifests).toBe("available");
    expect(snapshot.manifests.map(x => x.publication_id)).toEqual(["publication-A1", "second-publication"]);
    expect(snapshot.manifests.every(x => x.status === "available" && x.error === null)).toBe(true);
    expect(snapshot.manifests[0].value).toEqual(value);
    expect(load.mock.calls.map(x => x[0])).toEqual(["publication-A1", "second-publication"]);
    expect(snapshot.description).toContain("API responses");
    expect(snapshot.disclaimer).toContain("legal");
    expect(snapshot.limitations.join(" ")).toContain("provenance graph");
    record.title = "Later change";
    value.disclaimer = "Later change";
    expect(snapshot.record.title).toBe("Fresh record metadata");
    expect(snapshot.manifests[0].value?.disclaimer).toBe("Synthetic fixture; no real-world meaning.");
  });

  it("represents no publications and absent data class explicitly without guessing sources", async () => {
    const record = { ...recordDetail("A"), data_class: undefined };
    const version = { ...detail("A1"), publications: [] };
    const load = vi.fn();
    const snapshot = await prepareMetadataSnapshot("A", "A1", record, version, load);
    expect(snapshot.availability).toMatchObject({ publication_manifests: "none", data_class: "unknown" });
    expect(snapshot.manifests).toEqual([]);
    expect(load).not.toHaveBeenCalled();
    expect(snapshot.limitations.join(" ")).toContain("No publication manifests");
  });

  it("retains per-publication failure alongside available manifests", async () => {
    const version = detail("A1");
    version.publications.push({ ...version.publications[0], id: "unavailable" });
    const snapshot = await prepareMetadataSnapshot("A", "A1", recordDetail("A"), version,
      async id => { if (id === "unavailable") throw new Error("Manifest unavailable"); return manifest(); });
    expect(snapshot.availability.publication_manifests).toBe("incomplete");
    expect(snapshot.manifests[1]).toEqual({ publication_id: "unavailable", status: "unavailable", value: null, error: "Manifest unavailable" });
    expect(snapshot.manifests[0].value).toEqual(manifest());
  });

  it.each([
    null, [], {}, { ...manifest(), planning_record: "B" },
    { ...manifest(), planning_version: "A2" }, { ...manifest(), schema_version: "unknown" },
    { ...manifest(), artifacts: null }, { ...manifest(), disclaimer: null },
  ])("marks invalid manifest metadata unavailable: %j", async value => {
    const snapshot = await prepareMetadataSnapshot("A", "A1", recordDetail("A"), detail("A1"), async () => value);
    expect(snapshot.availability.publication_manifests).toBe("incomplete");
    expect(snapshot.manifests[0]).toMatchObject({ status: "unavailable", value: null });
    expect(snapshot.manifests[0].error).toContain("Invalid manifest");
  });

  it.each([
    [null, detail("A1")], [recordDetail("B"), detail("A1")],
    [recordDetail("A"), detail("B1")],
    [recordDetail("A"), { ...detail("A1"), documents: null }],
    [recordDetail("A"), { ...detail("A1"), datasets: [null] }],
    [recordDetail("A"), { ...detail("A1"), publications: [{}] }],
    [recordDetail("A"), { ...detail("A1"), documents: [{ ...detail("A1").documents[0], planning_version_id: "B1" }] }],
  ])("rejects missing, malformed or mismatched selection before fetching: %j", async (record, version) => {
    const load = vi.fn();
    await expect(prepareMetadataSnapshot("A", "A1", record, version, load)).rejects.toThrow(/Invalid|match/);
    expect(load).not.toHaveBeenCalled();
  });

  it.each(["../documents/doc/download?ignored=", "..", "%2f", "bad#id", "bad\\id"])(
    "rejects unsafe publication identifiers before any request: %s", async id => {
      const version = detail("A1");
      version.publications[0].id = id;
      const load = vi.fn();
      await expect(prepareMetadataSnapshot("A", "A1", recordDetail("A"), version, load)).rejects.toThrow("Invalid version metadata");
      expect(load).not.toHaveBeenCalled();
    },
  );
});

import { beforeEach, expect, it, vi } from "vitest";
import { deferred, detail, recordDetail, setup } from "./navigation-support";
import { api } from "@/lib/api";
import { downloadMetadataSnapshot } from "@/lib/download-metadata-snapshot";

vi.mock("@/lib/download-metadata-snapshot", () => ({ downloadMetadataSnapshot: vi.fn() }));
const ui = setup();
const start = () => ui.click("Prepare metadata snapshot (JSON)", "button");
const manifest = (version = "A1") => ({
  schema_version: "oqh.manifest/1", planning_record: version[0], planning_version: version,
  sources: [], datasets: [], artifacts: [], disclaimer: "Synthetic metadata; no real-world meaning.",
});
beforeEach(() => {
  vi.mocked(api.manifest).mockImplementation(async id => manifest(id.replace("publication-", "")));
});

it("prepares from owned response metadata and requires a second deliberate download", async () => {
  vi.mocked(api.recordDetail).mockResolvedValueOnce({ ...recordDetail("A"), title: "Fresh record response" });
  await ui.click("Synthetic record A");
  expect(api.manifest).not.toHaveBeenCalled();
  await start();
  expect(ui.text()).toContain("Metadata snapshot ready");
  expect(downloadMetadataSnapshot).not.toHaveBeenCalled();
  await ui.click("Download snapshot", "button");
  expect(downloadMetadataSnapshot).toHaveBeenCalledTimes(1);
  const value = vi.mocked(downloadMetadataSnapshot).mock.calls[0][0];
  expect(value.record.title).toBe("Fresh record response");
  expect(value.selection).toEqual({ record_id: "A", version_id: "A1" });
  expect(value.version).toEqual(detail("A1"));
  await ui.click("Download snapshot", "button");
  expect(downloadMetadataSnapshot).toHaveBeenCalledTimes(1);
  expect(api.recordDetail).toHaveBeenCalledTimes(1);
});

it("deduplicates preparation and ignores its completion after cancellation and retry", async () => {
  await ui.click("Synthetic record A");
  const old = deferred<Record<string, unknown>>();
  vi.mocked(api.manifest).mockReturnValueOnce(old.promise);
  await start(); await start();
  expect(api.manifest).toHaveBeenCalledTimes(1);
  await ui.click("Cancel preparation", "button");
  await start();
  await ui.reject(old, "CANCELLED MANIFEST FAILURE");
  expect(ui.text()).not.toContain("CANCELLED MANIFEST FAILURE");
  expect(ui.text()).toContain("Metadata snapshot ready");
  expect(downloadMetadataSnapshot).not.toHaveBeenCalled();
});

it.each(["success", "failure"])("ignores pending manifest %s after A→B→A", async outcome => {
  await ui.click("Synthetic record A");
  const old = deferred<Record<string, unknown>>();
  vi.mocked(api.manifest).mockReturnValueOnce(old.promise);
  await start();
  await ui.click("Synthetic record B"); await ui.click("Synthetic record A");
  if (outcome === "success") await ui.settle(old, { ...manifest(), disclaimer: "STALE CAPTURE" });
  else await ui.reject(old, "STALE CAPTURE");
  expect(ui.text()).not.toContain("STALE CAPTURE");
  expect(ui.text()).not.toContain("Metadata snapshot ready");
  expect(downloadMetadataSnapshot).not.toHaveBeenCalled();
  await start(); await ui.click("Download snapshot", "button");
  expect(downloadMetadataSnapshot).toHaveBeenCalledTimes(1);
});

it("invalidates a ready snapshot when changing versions or leaving the records tab", async () => {
  await ui.click("Synthetic record A"); await start();
  await ui.click("Synthetic version A2");
  expect(ui.text()).not.toContain("Metadata snapshot ready");
  await start();
  await ui.click("sources", ".tabs button"); await ui.click("records", ".tabs button");
  expect(ui.text()).not.toContain("Metadata snapshot ready");
  expect(downloadMetadataSnapshot).not.toHaveBeenCalled();
});

it("does not download when preparation completes after unmount", async () => {
  await ui.click("Synthetic record A");
  const old = deferred<Record<string, unknown>>();
  vi.mocked(api.manifest).mockReturnValueOnce(old.promise);
  await start(); await ui.hide(); await ui.settle(old, manifest());
  expect(ui.text()).toBe(""); expect(downloadMetadataSnapshot).not.toHaveBeenCalled();
});

it("shows manifest failures and only allows an explicitly incomplete download", async () => {
  await ui.click("Synthetic record A");
  vi.mocked(api.manifest).mockRejectedValueOnce(new Error("CURRENT MANIFEST FAILURE"));
  await start();
  expect(ui.text()).toContain("CURRENT MANIFEST FAILURE");
  expect(ui.text()).toContain("Incomplete metadata snapshot");
  expect(downloadMetadataSnapshot).not.toHaveBeenCalled();
  await ui.click("Download incomplete snapshot", "button");
  expect(vi.mocked(downloadMetadataSnapshot).mock.calls[0][0].availability.publication_manifests).toBe("incomplete");
  await start();
  expect(ui.text()).not.toContain("CURRENT MANIFEST FAILURE");
  expect(ui.text()).toContain("Metadata snapshot ready");
});

it.each(["record", "version"])("fails clearly on mismatched %s metadata before preparing", async target => {
  if (target === "record") vi.mocked(api.recordDetail).mockResolvedValueOnce(recordDetail("B"));
  else vi.mocked(api.versionDetail).mockResolvedValue(detail("B1"));
  await ui.click("Synthetic record A");
  expect(ui.text()).toContain("does not match the selection");
  expect(ui.text()).not.toContain("Prepare metadata snapshot (JSON)");
  expect(api.manifest).not.toHaveBeenCalled();
});

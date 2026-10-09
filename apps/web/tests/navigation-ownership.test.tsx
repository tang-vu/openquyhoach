import { bbox, deferred, detail, publication, recordDetail, setup } from "./navigation-support";
import { expect, it, vi } from "vitest";
import { api } from "@/lib/api";

const ui = setup();

async function startComparison() {
  await ui.click("Synthetic record A");
  await ui.click("compare", ".tabs button");
  vi.mocked(api.versionDetail).mockImplementation(async id => ({ ...detail(id), datasets: [{
    id: `vector-${id}`, name: "Synthetic vector", dataset_group: "synthetic",
    dataset_type: "vector", derivation_level: "derived_manual", review_status: "approved",
    quality_state: "synthetic", published: true,
  }] }));
  vi.mocked(api.dataset).mockImplementation(async id => ({
    id, name: "Synthetic vector", dataset_group: "synthetic", dataset_type: "vector",
    derivation_level: "derived_manual", review_status: "approved", quality_state: "synthetic",
    published: true, layers: [{ id: `layer-${id}`, canonical_name: "land_use", feature_count: 0 }],
  }));
  const pending = deferred<Awaited<ReturnType<typeof api.compare>>>();
  vi.mocked(api.compare).mockReturnValueOnce(pending.promise);
  await ui.choose(0, "A1"); await ui.choose(1, "A2");
  await ui.click("Compare", "button.primary");
  expect(api.compare).toHaveBeenCalledWith("layer-vector-A1", "layer-vector-A2");
  return pending;
}

const comparison = { id: "synthetic-compare", from_layer_id: "layer-vector-A1",
  to_layer_id: "layer-vector-A2", algorithm: "synthetic", summary: {}, entries: [] };

it("control: normal record selection displays the matching source and publication", async () => {
  await ui.click("Synthetic record B");
  expect(ui.selected("Synthetic record B")).toBe(true);
  expect.soft(ui.text()).toContain("Synthetic version B1");
  expect.soft(ui.text()).toContain("Synthetic source document B1");
  expect.soft(ui.sources()).toEqual(["pub-publication-B1"]);
  expect(ui.lastBounds()).toEqual([[9, 10], [11, 12]]);
});

it("newer record keeps its versions, provenance and publication after older detail succeeds", async () => {
  const old = deferred<Awaited<ReturnType<typeof api.recordDetail>>>();
  vi.mocked(api.recordDetail).mockReturnValueOnce(old.promise);
  await ui.click("Synthetic record A");
  await ui.click("Synthetic record B");
  await ui.settle(old, recordDetail("A"));
  expect(ui.selected("Synthetic record B")).toBe(true);
  expect.soft(ui.text()).toContain("Synthetic version B1");
  expect.soft(ui.text()).toContain("Synthetic source document B1");
  expect.soft(ui.sources()).toEqual(["pub-publication-B1"]);
});

it("older record errors cannot contaminate a newer successful selection", async () => {
  const old = deferred<Awaited<ReturnType<typeof api.recordDetail>>>();
  vi.mocked(api.recordDetail).mockReturnValueOnce(old.promise);
  await ui.click("Synthetic record A");
  await ui.click("Synthetic record B");
  await ui.reject(old, "OLD RECORD FAILURE");
  expect(ui.text()).not.toContain("OLD RECORD FAILURE");
});

it("a record with no versions clears the previous publication and raster overlay", async () => {
  await ui.click("Synthetic record A");
  await ui.raster();
  expect(ui.sources()).toEqual(["pub-publication-A1", "raster-overlay"]);
  await ui.click("Synthetic record E");
  expect(ui.selected("Synthetic record E")).toBe(true);
  expect(ui.text()).not.toContain("Synthetic version A1");
  expect(ui.sources()).toEqual([]);
});

it("pending new record selection immediately stops displaying the previous record detail and layer", async () => {
  await ui.click("Synthetic record A");
  const pending = deferred<Awaited<ReturnType<typeof api.recordDetail>>>();
  vi.mocked(api.recordDetail).mockReturnValueOnce(pending.promise);
  await ui.click("Synthetic record B");
  expect(ui.selected("Synthetic record B")).toBe(true);
  expect.soft(ui.text()).not.toContain("Synthetic source document A1");
  expect.soft(ui.sources()).toEqual([]);
  await ui.settle(pending, recordDetail("B"));
});

it("older version extent cannot reframe the map after selecting a newer version", async () => {
  const old = deferred<{ bbox: number[] }>();
  vi.mocked(api.versionExtent).mockReturnValueOnce(old.promise);
  await ui.click("Synthetic record A");
  await ui.click("Synthetic version A2");
  expect(ui.lastBounds()).toEqual([[5, 6], [7, 8]]);
  await ui.settle(old, { bbox: bbox.A1 });
  expect(ui.selected("Synthetic version A2")).toBe(true);
  expect(ui.lastBounds()).toEqual([[5, 6], [7, 8]]);
});

it("older version detail cannot replace a newer version's source document or raster choices", async () => {
  const old = deferred<Awaited<ReturnType<typeof api.versionDetail>>>();
  vi.mocked(api.versionDetail).mockReturnValueOnce(old.promise);
  await ui.click("Synthetic record A");
  await ui.click("Synthetic version A2");
  expect(ui.text()).toContain("Synthetic source document A2");
  await ui.settle(old, detail("A1"));
  expect(ui.selected("Synthetic version A2")).toBe(true);
  expect(ui.text()).toContain("Synthetic source document A2");
  expect(ui.text()).not.toContain("Synthetic raster A1");
});

it("a new version recovers after the prior version detail failed", async () => {
  vi.mocked(api.versionDetail).mockImplementation(async id => {
    if (id === "A1") throw new Error("OLD VERSION FAILURE");
    return detail(id);
  });
  await ui.click("Synthetic record A");
  expect(ui.text()).toContain("OLD VERSION FAILURE");
  await ui.click("Synthetic version A2");
  expect(ui.text()).toContain("Synthetic source document A2");
  expect(ui.text()).not.toContain("OLD VERSION FAILURE");
});

it("an old manifest cannot appear below the newer version's publication", async () => {
  await ui.click("Synthetic record A");
  const old = deferred<Record<string, unknown>>();
  vi.mocked(api.manifest).mockReturnValueOnce(old.promise);
  await ui.click("view manifest", "button");
  await ui.click("Synthetic version A2");
  await ui.settle(old, { fixture: "synthetic", publication: "OLD-A1-MANIFEST" });
  expect(ui.text()).toContain("Synthetic source document A2");
  expect(ui.text()).not.toContain("OLD-A1-MANIFEST");
});

it("an A→B→A revisit has new ownership even when the record ID repeats", async () => {
  const old = deferred<Awaited<ReturnType<typeof api.recordDetail>>>();
  vi.mocked(api.recordDetail).mockReturnValueOnce(old.promise);
  await ui.click("Synthetic record A");
  await ui.click("Synthetic record B");
  await ui.click("Synthetic record A");
  await ui.click("Synthetic version A2");
  await ui.settle(old, recordDetail("A"));
  expect(ui.selected("Synthetic version A2")).toBe(true);
  expect(ui.text()).toContain("Synthetic source document A2");
});

it("a comparison finishing after record navigation cannot restore an old record overlay", async () => {
  const old = await startComparison();
  await ui.click("records", ".tabs button");
  await ui.click("Synthetic record B");
  await ui.settle(old, comparison);
  expect(ui.selected("Synthetic record B")).toBe(true);
  expect(ui.sources()).toEqual(["pub-publication-B1"]);
});

it("control: an explicit historical comparison survives same-record tab and version navigation", async () => {
  const pending = await startComparison();
  await ui.settle(pending, comparison);
  expect(ui.text()).toContain("Geometric difference is not a legal interpretation");
  expect(ui.sources()).toEqual(["pub-publication-A1", "pub-publication-A2"]);
  await ui.click("records", ".tabs button");
  await ui.click("Synthetic version A2");
  await ui.click("Synthetic version A1");
  expect(ui.sources()).toEqual(["pub-publication-A1", "pub-publication-A2"]);
});

it("new record navigation clears a completed comparison belonging to the old record", async () => {
  const pending = await startComparison();
  await ui.settle(pending, comparison);
  await ui.click("records", ".tabs button");
  await ui.click("Synthetic record B");
  expect(ui.sources()).toEqual(["pub-publication-B1"]);
});

it("control: queued map-load callbacks finish on the newest publication", async () => {
  ui.deferMapLoad();
  await ui.click("Synthetic record A");
  await ui.click("Synthetic record B");
  expect(ui.sources()).toEqual([]);
  await ui.loadMap();
  expect(ui.sources()).toEqual(["pub-publication-B1"]);
});

it("empty record selection also clears publication callbacks queued before map load", async () => {
  ui.deferMapLoad();
  await ui.click("Synthetic record A");
  await ui.click("Synthetic record E");
  await ui.loadMap();
  expect(ui.selected("Synthetic record E")).toBe(true);
  expect(ui.sources()).toEqual([]);
});

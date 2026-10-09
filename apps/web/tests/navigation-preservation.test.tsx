import { deferred, publication, recordDetail, detail, bbox, setup } from "./navigation-support";
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

it("search-driven record navigation resets a mounted comparison form", async () => {
  const old = await startComparison();
  await ui.pickRecord("B");
  expect(ui.values()).toEqual(["", ""]);
  await ui.settle(old, comparison);
  expect(ui.sources()).toEqual(["pub-publication-B1"]);
  expect(api.compare).toHaveBeenCalledTimes(1);
});

it("pending comparison remains valid through same-record tab and version navigation", async () => {
  const pending = await startComparison();
  await ui.click("records", ".tabs button");
  await ui.click("Synthetic version A2");
  await ui.click("Synthetic version A1");
  await ui.settle(pending, comparison);
  expect(ui.sources()).toEqual(["pub-publication-A1", "pub-publication-A2"]);
});

it("a late publication catalog preserves the raster and does not reframe the map", async () => {
  const pending = deferred<Awaited<ReturnType<typeof api.publications>>>();
  vi.mocked(api.publications).mockReturnValue(pending.promise);
  await ui.remount();
  await ui.click("Synthetic record A");
  await ui.raster();
  const fits = ui.boundsCount();
  await ui.settle(pending, { items: [publication("A1")] });
  expect(ui.sources()).toEqual(["pub-publication-A1", "raster-overlay"]);
  expect(ui.boundsCount()).toBe(fits);
});

it("new coordinate focus supersedes an older pending version extent", async () => {
  const old = deferred<{ bbox: number[] }>();
  vi.mocked(api.versionExtent).mockReturnValueOnce(old.promise);
  await ui.click("Synthetic record A");
  await ui.pickCoordinate(0, 0);
  await ui.settle(old, { bbox: bbox.A1 });
  expect(ui.lastBounds()).toEqual([[-0.02, -0.02], [0.02, 0.02]]);
});

it("re-clicking the same record preserves the selected historical version and raster", async () => {
  await ui.click("Synthetic record A");
  await ui.click("Synthetic version A2");
  await ui.raster();
  await ui.click("Synthetic record A");
  expect(ui.selected("Synthetic version A2")).toBe(true);
  expect(ui.sources()).toEqual(["pub-publication-A2", "raster-overlay"]);
});

it("an old comparison cannot clear a new comparison after an A→B→A revisit", async () => {
  const old = await startComparison();
  await ui.pickRecord("B");
  await ui.click("records", ".tabs button");
  const current = await startComparison();
  await ui.settle(current, comparison);
  expect(ui.sources()).toEqual(["pub-publication-A1", "pub-publication-A2"]);
  vi.mocked(api.publications).mockResolvedValueOnce({ items: [] });
  await ui.settle(old, comparison);
  expect(ui.sources()).toEqual(["pub-publication-A1", "pub-publication-A2"]);
});

it("coordinate focus also supersedes framing that an older pending record has not started", async () => {
  const old = deferred<Awaited<ReturnType<typeof api.recordDetail>>>();
  vi.mocked(api.recordDetail).mockReturnValueOnce(old.promise);
  await ui.click("Synthetic record A");
  await ui.pickCoordinate(0, 0);
  await ui.settle(old, recordDetail("A"));
  expect(ui.text()).toContain("Synthetic source document A1");
  expect(ui.sources()).toEqual(["pub-publication-A1"]);
  expect(ui.lastBounds()).toEqual([[-0.02, -0.02], [0.02, 0.02]]);
  await ui.click("Synthetic version A2");
  expect(ui.lastBounds()).toEqual([[5, 6], [7, 8]]);
});

it("a later coordinate in the same update owns focus before the extent effect starts", async () => {
  await ui.click("Synthetic record A");
  await ui.versionThenCoordinate("Synthetic version A2", 0, 0);
  expect(ui.selected("Synthetic version A2")).toBe(true);
  expect(ui.lastBounds()).toEqual([[-0.02, -0.02], [0.02, 0.02]]);
});

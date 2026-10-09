import assert from "node:assert/strict";
import { comparison, publications } from "./browser-fixtures.mjs";
import { navigationUI } from "./browser-navigation-support.mjs";

export async function oldRecordComparison(harness) {
  const { page } = harness;
  const ui = navigationUI(harness);
  await harness.open();
  await ui.record("A"); await ui.loaded("A1");
  const oldCatalog = harness.hold("/v1/publications");
  await ui.compare(); await oldCatalog.requested();
  await page.getByText("synthetic_changes", { exact: true }).waitFor();
  // Search navigates records while ComparePanel remains mounted.
  const search = page.getByPlaceholder("Search records, units, '105.9, 20.9'…");
  await search.fill("B"); await search.press("Enter");
  await page.getByText("Search synthetic B", { exact: true }).click();
  await page.locator("select").first().locator('option[value="B1"]').waitFor({ state: "attached" });
  oldCatalog.release({ json: { items: publications } });
  await ui.settle();
  assert.deepEqual(await page.locator("select").evaluateAll((nodes) => nodes.map((node) => node.value)), ["", ""]);
  await ui.absent("Synthetic version A1", "synthetic_changes", "Geometric difference is not a legal interpretation");
  await ui.tab("records"); await ui.loaded("B1");
  await ui.sources(["publication-B1"], "late-old-record-comparison-cannot-return");
  const call = harness.requests.find((entry) => entry.path === "/v1/compare");
  assert.deepEqual(call.query, { from_layer: "layer-A1", to_layer: "layer-A2" });
  await harness.capture("B-ignores-old-comparison");
}

export async function sameRecordComparison(harness) {
  const ui = navigationUI(harness);
  await harness.open();
  await ui.record("A"); await ui.loaded("A1");
  const pending = harness.hold("/v1/compare");
  await ui.compare(); await pending.requested();
  await ui.tab("records");
  await ui.version("A3"); await ui.loaded("A3");
  pending.release({ json: comparison });
  await ui.settle();
  await ui.sources(["publication-A3", "publication-A2"], "same-record-pending-comparison-survives");
  await harness.capture("A3-preserves-intended-A2-comparison");
  await ui.tab("compare"); await ui.tab("records");
  await ui.loaded("A3");
  await ui.version("A2"); await ui.loaded("A2");
  await ui.sources(["publication-A2"], "comparison-and-main-share-one-publication");
  await ui.version("A1"); await ui.loaded("A1");
  await ui.record("A");
  await ui.sources(["publication-A1", "publication-A2"], "completed-comparison-survives-tabs-and-versions");
  await ui.record("B"); await ui.loaded("B1");
  await ui.sources(["publication-B1"], "new-record-clears-completed-comparison");
  await harness.capture("B-clears-completed-comparison");
}

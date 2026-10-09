import assert from "node:assert/strict";
import { recordDetail } from "./browser-fixtures.mjs";
import { failure, navigationUI, recordPath } from "./browser-navigation-support.mjs";

export async function recordReversal(harness) {
  const ui = navigationUI(harness);
  await harness.open();
  const old = harness.hold(recordPath("A"));
  await ui.record("A"); await old.requested();
  await ui.record("B"); await ui.loaded("B1");
  old.release({ json: recordDetail("A") });
  await ui.settle();
  await ui.selected("Synthetic record B");
  await ui.loaded("B1");
  await ui.absent("Synthetic version A1", "Synthetic source document A1");
  await ui.sources(["publication-B1"], "older-record-response-ignored");
  await harness.capture("B-owns-reversed-responses");
}

export async function emptyRecord(harness) {
  const { page } = harness;
  const ui = navigationUI(harness);
  await harness.open();
  await ui.record("A"); await ui.loaded("A1");
  await ui.raster().check();
  await ui.sources(["publication-A1", "raster-A1"], "loaded-publication-and-raster");
  const next = harness.hold(recordPath("B"));
  await ui.record("B"); await next.requested();
  await page.getByRole("status").filter({ hasText: "Loading versions" }).waitFor();
  await ui.absent("Synthetic source document A1", "Synthetic raster A1");
  await ui.sources([], "pending-record-clears-layers");
  next.release({ json: recordDetail("B") });
  await ui.loaded("B1");
  await ui.raster().check();
  await ui.sources(["publication-B1", "raster-B1"], "replacement-publication-and-raster");
  await ui.record("E");
  await page.getByText("No versions available for this record.", { exact: true }).waitFor();
  await ui.selected("Synthetic record E");
  await ui.absent("Synthetic version B1", "Synthetic source document B1", "Synthetic raster B1");
  assert.equal(await ui.raster().count(), 0);
  await ui.sources([], "empty-record-clears-publication-and-raster");
  await harness.capture("empty-record");
}

export async function recordRevisit(harness) {
  const ui = navigationUI(harness);
  await harness.open();
  const oldA = harness.hold(recordPath("A"));
  const oldB = harness.hold(recordPath("B"));
  await ui.record("A"); await oldA.requested();
  await ui.record("B"); await oldB.requested();
  await ui.record("A"); await ui.loaded("A1");
  await ui.version("A2"); await ui.loaded("A2");
  await ui.raster().check();
  await ui.sources(["publication-A2", "raster-A2"], "revisited-record-control");
  oldB.release(failure("OLD-B-FAILURE"));
  oldA.release({ json: recordDetail("A") });
  await ui.settle();
  await ui.loaded("A2");
  await ui.absent("OLD-B-FAILURE", "Synthetic source document A1");
  const calls = harness.requests.filter((entry) => entry.path === recordPath("A")).length;
  await ui.record("A"); await ui.settle();
  await ui.loaded("A2");
  assert.equal(await ui.raster().isChecked(), true);
  assert.equal(harness.requests.filter((entry) => entry.path === recordPath("A")).length, calls);
  await ui.sources(["publication-A2", "raster-A2"], "A-B-A-and-repeated-A-preserve-current-owner");
  await harness.capture("revisited-A2");
}

export async function recordRecovery(harness) {
  const { page } = harness;
  const ui = navigationUI(harness);
  await harness.open();
  harness.reply(recordPath("A"), failure("CURRENT-RECORD-FAILURE"));
  await ui.record("A");
  await page.getByRole("alert").filter({ hasText: "CURRENT-RECORD-FAILURE" }).waitFor();
  await ui.sources([], "record-error-has-no-layers");
  await ui.record("B"); await ui.loaded("B1");
  await ui.absent("CURRENT-RECORD-FAILURE");
  const old = harness.hold(recordPath("A"));
  await ui.record("A"); await old.requested();
  await ui.record("B"); await ui.loaded("B1");
  old.release(failure("STALE-RECORD-FAILURE"));
  await ui.settle();
  await ui.absent("STALE-RECORD-FAILURE");
  await ui.record("A"); await ui.loaded("A1");
  await ui.sources(["publication-A1"], "record-recovery");
  await harness.capture("recovered-record");
}

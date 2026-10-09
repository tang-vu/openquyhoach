import assert from "node:assert/strict";
import { until } from "./browser-harness.mjs";
import { detailPath, navigationUI, recordPath } from "./browser-navigation-support.mjs";
import { publicationManifestPath, snapshotManifest, snapshotRecord, snapshotVersion } from "./browser-snapshot-fixtures.mjs";

export const START = "Prepare metadata snapshot (JSON)";
export const COMPLETE = "Download snapshot";
export const INCOMPLETE = "Download incomplete snapshot";

export function snapshotUI(harness) {
  const ui = navigationUI(harness);
  const { page } = harness;
  const downloads = [];
  page.on("download", (download) => downloads.push(download));
  const button = (name) => page.getByRole("button", { name, exact: true });
  return {
    ...ui, button, downloads,
    async open(record = snapshotRecord(), version = snapshotVersion()) {
      harness.reply(recordPath(record.id), { json: record });
      harness.reply(detailPath(version.id), { json: version });
      await harness.open();
      await ui.record(record.id);
      await ui.loaded(version.id);
      await button(START).waitFor();
    },
    prepare: () => button(START).click(),
    async ready(complete = true) {
      await button(complete ? COMPLETE : INCOMPLETE).waitFor();
      assert.equal(await button(complete ? INCOMPLETE : COMPLETE).count(), 0);
      assert.equal(await button("Cancel preparation").count(), 0);
    },
    async noReady() {
      assert.equal(await button(COMPLETE).count(), 0);
      assert.equal(await button(INCOMPLETE).count(), 0);
    },
    async download(complete = true, { keyboard = false } = {}) {
      const choice = button(complete ? COMPLETE : INCOMPLETE);
      if (keyboard) assert.ok(await choice.evaluate((element) => document.activeElement === element),
        "Enter must activate the focused snapshot choice");
      const [download] = await Promise.all([
        page.waitForEvent("download"), keyboard ? page.keyboard.press("Enter") : choice.click(),
      ]);
      assert.equal(await download.failure(), null);
      assert.match(download.url(), /^blob:/, "Snapshot must be a local Blob download");
      assert.match(download.suggestedFilename(), /\.json$/);
      const bytes = await harness.recordDownload(download);
      return JSON.parse(bytes.toString("utf8"));
    },
    assertNoDownloads() { assert.equal(downloads.length, 0, "Preparation must never download automatically"); },
  };
}

export function heldManifests(harness, version = snapshotVersion()) {
  const gates = version.publications.map((publication) => harness.hold(publicationManifestPath(publication.id)));
  return {
    gates,
    requested: () => Promise.all(gates.map((gate) => gate.requested())),
    release(marker = "current") {
      gates.forEach((gate, index) => gate.release({ json: snapshotManifest(version.id, `${marker}-${index}`) }));
    },
  };
}

export function replyManifests(harness, version = snapshotVersion(), marker = "current") {
  const manifests = version.publications.map((publication, index) => {
    const value = snapshotManifest(version.id, `${marker}-${index}`);
    harness.reply(publicationManifestPath(publication.id), { json: value });
    return { publication_id: publication.id, status: "available", value, error: null };
  });
  return manifests;
}

export function assertSnapshot(snapshot, { record, version, manifests, availability, since }) {
  assert.equal(snapshot.schema_version, 1);
  assert.deepEqual(snapshot.selection, { record_id: record.id, version_id: version.id });
  assert.deepEqual(snapshot.record, record, "Every returned record field and version must survive");
  assert.deepEqual(snapshot.version, version, "Every dataset, document, publication and unknown field must survive");
  assert.deepEqual(snapshot.manifests, manifests, "Manifest JSON values and explicit absence must survive");
  assert.equal(snapshot.availability.publication_manifests, availability);
  assert.match(snapshot.captured_at, /^\d{4}-\d\d-\d\dT.*Z$/);
  const captured = Date.parse(snapshot.captured_at);
  assert.ok(Number.isFinite(captured) && captured >= since && captured <= Date.now());
  assert.equal(typeof snapshot.description, "string");
  assert.match(snapshot.description, /metadata/i);
  assert.equal(typeof snapshot.disclaimer, "string");
  assert.ok(snapshot.disclaimer.length > 0);
  assert.ok(Array.isArray(snapshot.limitations) && snapshot.limitations.length > 0);
  assert.ok(snapshot.limitations.every((limitation) => typeof limitation === "string" && limitation.length > 0));
}

export function assertMetadataRequestsOnly(harness, start) {
  const requests = harness.requests.slice(start).filter((entry) => entry.kind === "synthetic-api");
  assert.ok(requests.every((entry) => entry.method === "GET"));
  assert.ok(requests.every((entry) => /\/manifest\.json$|\/tiles\//.test(entry.path)),
    `Snapshot preparation must use owned metadata and manifests only: ${requests.map((entry) => entry.path)}`);
}

export async function settledManifestReplies(harness, start) {
  await until(() => harness.requests.slice(start)
    .filter((entry) => entry.path.endsWith("/manifest.json"))
    .every((entry) => entry.completion), "Synthetic manifest replies did not complete");
  // Let the real client consume completed responses before checking stale UI.
  await harness.page.waitForTimeout(100);
}

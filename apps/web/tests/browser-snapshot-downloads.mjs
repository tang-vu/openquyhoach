import assert from "node:assert/strict";
import { failure } from "./browser-navigation-support.mjs";
import { publicationManifestPath, snapshotManifest, snapshotRecord, snapshotVersion } from "./browser-snapshot-fixtures.mjs";
import {
  COMPLETE, INCOMPLETE, START, assertMetadataRequestsOnly, assertSnapshot,
  heldManifests, replyManifests, snapshotUI,
} from "./browser-snapshot-support.mjs";

export async function completeSnapshot(harness) {
  const ui = snapshotUI(harness);
  const record = snapshotRecord(), version = snapshotVersion();
  await ui.open(record, version);
  const held = heldManifests(harness, version);
  const start = harness.requests.length, since = Date.now();
  harness.phase("prepare-complete-snapshot");
  // Two synchronous DOM activations model rapid keyboard/click re-entry without
  // exposing component state or changing product behavior.
  await ui.button(START).evaluate((button) => { button.click(); button.click(); });
  await held.requested();
  assert.equal(await ui.button(START).isDisabled(), true);
  await ui.button("Cancel preparation").waitFor();
  await ui.noReady(); ui.assertNoDownloads();
  const values = [snapshotManifest("A1", "first"), snapshotManifest("A1", "second")];
  held.gates[1].release({ json: values[1] });
  await harness.page.waitForTimeout(100);
  await ui.noReady(); ui.assertNoDownloads();
  held.gates[0].release({ json: values[0] });
  await ui.ready();
  ui.assertNoDownloads();
  assert.equal(harness.requests.slice(start).filter((entry) => entry.path.endsWith("/manifest.json")).length, 2,
    "Repeated preparation must not request a second set of manifests");
  await harness.capture("ready-with-explicit-download");
  assertSnapshot(await ui.download(), {
    record, version, since, availability: "available",
    manifests: version.publications.map((publication, index) => ({
      publication_id: publication.id, status: "available", value: values[index], error: null,
    })),
  });
  assert.equal(await ui.button(COMPLETE).isDisabled(), true);
  assertMetadataRequestsOnly(harness, start);
}

export async function incompleteSnapshotRecovery(harness) {
  const ui = snapshotUI(harness);
  const record = snapshotRecord(), version = snapshotVersion();
  await ui.open(record, version);
  const good = snapshotManifest("A1", "available-on-first-attempt");
  harness.reply(publicationManifestPath(version.publications[0].id), { json: good });
  harness.reply(publicationManifestPath(version.publications[1].id), failure("SYNTHETIC-MANIFEST-UNAVAILABLE"));
  const start = harness.requests.length, since = Date.now();
  harness.phase("incomplete-snapshot-requires-choice");
  await ui.prepare(); await ui.ready(false); ui.assertNoDownloads();
  const content = await ui.text();
  assert.ok(content.includes(version.publications[1].id), "Failed publication must be identified");
  assert.ok(content.includes("SYNTHETIC-MANIFEST-UNAVAILABLE"), "Manifest failure must be explained");
  await harness.capture("explicit-incomplete-choice");
  const result = await ui.download(false);
  assert.equal(result.manifests[1].status, "unavailable");
  assert.equal(result.manifests[1].value, null);
  assert.match(result.manifests[1].error, /SYNTHETIC-MANIFEST-UNAVAILABLE/);
  assertSnapshot(result, {
    record, version, since, availability: "incomplete",
    manifests: [
      { publication_id: version.publications[0].id, status: "available", value: good, error: null },
      { publication_id: version.publications[1].id, status: "unavailable", value: null, error: result.manifests[1].error },
    ],
  });
  assert.equal(await ui.button(INCOMPLETE).isDisabled(), true);
  const manifests = replyManifests(harness, version, "recovered");
  const retrySince = Date.now();
  await ui.prepare(); await ui.ready();
  await ui.absent("SYNTHETIC-MANIFEST-UNAVAILABLE");
  assert.equal(ui.downloads.length, 1, "Retry must wait for another explicit download");
  assertSnapshot(await ui.download(), { record, version, manifests, since: retrySince, availability: "available" });
  assert.equal(ui.downloads.length, 2);
  assertMetadataRequestsOnly(harness, start);
  await harness.capture("recovered-complete-snapshot");
}

export async function unpublishedSnapshot(harness) {
  const ui = snapshotUI(harness);
  const record = snapshotRecord(), version = snapshotVersion("A1", { unpublished: true });
  await ui.open(record, version);
  const start = harness.requests.length, since = Date.now();
  harness.phase("no-publication-provenance");
  await ui.prepare(); await ui.ready(false); ui.assertNoDownloads();
  assert.match(await ui.text(), /publication provenance.*unavailable|unavailable.*publication provenance|no publication manifests are available|no publications/i);
  assertSnapshot(await ui.download(false), {
    record, version, manifests: [], since, availability: "none",
  });
  assert.equal(harness.requests.slice(start).filter((entry) => entry.path.endsWith("/manifest.json")).length, 0);
  assertMetadataRequestsOnly(harness, start);
  await harness.capture("no-publications-explicitly-incomplete");
}

export async function invalidManifestSnapshot(harness) {
  const ui = snapshotUI(harness);
  const record = snapshotRecord(), version = snapshotVersion();
  await ui.open(record, version);
  const cases = [
    { ...snapshotManifest(), planning_record: "B", planning_version: "B1" },
    { ...snapshotManifest(), planning_record: "A", planning_version: "A2" },
    { ...snapshotManifest(), schema_version: "unknown-schema" },
    { ...snapshotManifest(), artifacts: null },
    { ...snapshotManifest(), planning_version: undefined },
  ];
  for (const [index, invalid] of cases.entries()) {
    const good = snapshotManifest("A1", `valid-companion-${index}`);
    harness.reply(publicationManifestPath(version.publications[0].id), { json: good });
    harness.reply(publicationManifestPath(version.publications[1].id), { json: invalid });
    const since = Date.now();
    await ui.prepare(); await ui.ready(false);
    assert.equal(ui.downloads.length, index, "Rejected manifest must not trigger a download");
    const result = await ui.download(false);
    const unavailable = result.manifests[1];
    assert.equal(unavailable.status, "unavailable");
    assert.equal(unavailable.value, null);
    assert.equal(typeof unavailable.error, "string");
    assert.ok(unavailable.error.length > 0);
    assertSnapshot(result, { record, version, since, availability: "incomplete", manifests: [
      { publication_id: version.publications[0].id, status: "available", value: good, error: null },
      { publication_id: version.publications[1].id, status: "unavailable", value: null, error: unavailable.error },
    ] });
  }
  await harness.capture("invalid-manifests-are-unavailable");
}

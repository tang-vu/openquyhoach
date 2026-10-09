import assert from "node:assert/strict";
import { detailPath, failure, recordPath } from "./browser-navigation-support.mjs";
import { snapshotRecord, snapshotVersion } from "./browser-snapshot-fixtures.mjs";
import {
  COMPLETE, START, assertSnapshot, heldManifests, replyManifests,
  settledManifestReplies, snapshotUI,
} from "./browser-snapshot-support.mjs";

export async function cancelledSnapshot(harness) {
  const ui = snapshotUI(harness);
  const record = snapshotRecord(), version = snapshotVersion();
  await ui.open(record, version);
  const old = heldManifests(harness, version), oldStart = harness.requests.length;
  await ui.prepare(); await old.requested();
  await ui.button("Cancel preparation").click();
  await ui.noReady(); ui.assertNoDownloads();
  assert.equal(await ui.button(START).isEnabled(), true);

  const manifests = replyManifests(harness, version, "after-explicit-cancel");
  const since = Date.now();
  await ui.prepare(); await ui.ready();
  old.release("cancelled-response-must-not-win");
  await settledManifestReplies(harness, oldStart);
  await ui.ready(); ui.assertNoDownloads();
  assertSnapshot(await ui.download(), { record, version, manifests, since, availability: "available" });
  await ui.button(COMPLETE).evaluate((button) => { button.click(); button.click(); });
  await harness.page.waitForTimeout(100);
  assert.equal(ui.downloads.length, 1, "A consumed snapshot must not download again on repeated activation");
  await harness.capture("cancelled-work-cannot-replace-retry");
}

export async function recordSnapshotRevisit(harness) {
  const ui = snapshotUI(harness);
  const record = snapshotRecord(), version = snapshotVersion();
  await ui.open(record, version);
  const old = heldManifests(harness, version), oldStart = harness.requests.length;
  await ui.prepare(); await old.requested();
  await ui.record("B"); await ui.loaded("B1");
  await ui.noReady(); ui.assertNoDownloads();

  harness.reply(recordPath("A"), { json: record });
  harness.reply(detailPath("A1"), { json: version });
  await ui.record("A"); await ui.loaded("A1");
  await ui.noReady();
  const manifests = replyManifests(harness, version, "new-A-after-A-B-A");
  const since = Date.now();
  await ui.prepare(); await ui.ready();
  old.release("old-A-before-A-B-A");
  await settledManifestReplies(harness, oldStart);
  await ui.ready(); ui.assertNoDownloads();
  assertSnapshot(await ui.download(), { record, version, manifests, since, availability: "available" });

  // A prepared result is discarded by the same ownership transition too.
  replyManifests(harness, version, "undownloaded-before-record-change");
  await ui.prepare(); await ui.ready();
  await ui.record("B"); await ui.loaded("B1");
  await ui.noReady();
  assert.equal(ui.downloads.length, 1);
  await harness.capture("record-revisit-keeps-only-new-generation");
}

export async function versionSnapshotOwnership(harness) {
  const ui = snapshotUI(harness);
  const record = snapshotRecord(), first = snapshotVersion(), version = snapshotVersion("A2");
  await ui.open(record, first);
  const old = heldManifests(harness, first), oldStart = harness.requests.length;
  await ui.prepare(); await old.requested();
  harness.reply(detailPath("A2"), { json: version });
  await ui.version("A2"); await ui.loaded("A2");
  await ui.noReady();
  const manifests = replyManifests(harness, version, "current-A2");
  const since = Date.now();
  await ui.prepare(); await ui.ready();
  old.gates.forEach((gate) => gate.release(failure("STALE-A1-SNAPSHOT-FAILURE")));
  await settledManifestReplies(harness, oldStart);
  await ui.absent("STALE-A1-SNAPSHOT-FAILURE");
  ui.assertNoDownloads();
  assertSnapshot(await ui.download(), { record, version, manifests, since, availability: "available" });
  replyManifests(harness, version, "undownloaded-before-version-change");
  await ui.prepare(); await ui.ready();
  await ui.version("A3"); await ui.loaded("A3");
  await ui.noReady();
  assert.equal(ui.downloads.length, 1);
  await harness.capture("version-change-clears-ready-snapshot");
}

export async function tabSnapshotOwnership(harness) {
  const ui = snapshotUI(harness);
  const record = snapshotRecord(), version = snapshotVersion();
  await ui.open(record, version);
  const old = heldManifests(harness, version), oldStart = harness.requests.length;
  await ui.prepare(); await old.requested();
  await ui.tab("compare");
  await ui.noReady();
  harness.reply(detailPath("A1"), { json: version });
  await ui.tab("records"); await ui.loaded("A1");
  old.release("unmounted-snapshot-response");
  await settledManifestReplies(harness, oldStart);
  await ui.noReady(); ui.assertNoDownloads();

  replyManifests(harness, version, "ready-before-tab-change");
  await ui.prepare(); await ui.ready(); ui.assertNoDownloads();
  await ui.tab("compare");
  harness.reply(detailPath("A1"), { json: version });
  await ui.tab("records"); await ui.loaded("A1");
  await ui.noReady(); ui.assertNoDownloads();
  assert.equal(await ui.button(START).isEnabled(), true);
  await harness.capture("tab-unmount-discards-pending-and-ready-snapshots");
}

import assert from "node:assert/strict";
import { detailPath, recordPath } from "./browser-navigation-support.mjs";
import { snapshotRecord, snapshotVersion } from "./browser-snapshot-fixtures.mjs";
import { START, snapshotUI } from "./browser-snapshot-support.mjs";

export async function invalidSnapshotMetadata(harness) {
  const ui = snapshotUI(harness);
  await harness.open();
  const invalidRecords = [
    { ...snapshotRecord(), id: "B" },
    { ...snapshotRecord(), versions: null },
    { ...snapshotRecord(), versions: [{ ...snapshotRecord().versions[0], planning_record_id: "B" }] },
  ];
  for (const record of invalidRecords) {
    harness.reply(recordPath("A"), { json: record });
    await ui.record("A");
    await harness.page.getByRole("alert").waitFor();
    await ui.noReady(); ui.assertNoDownloads();
    assert.equal(await ui.button(START).count(), 0);
    await ui.record("B"); await ui.loaded("B1");
  }

  harness.reply(recordPath("A"), { json: snapshotRecord() });
  const invalidVersions = [
    { ...snapshotVersion(), id: "B1" },
    { ...snapshotVersion(), planning_record_id: "B" },
    { ...snapshotVersion(), documents: null },
    { ...snapshotVersion(), datasets: null },
    { ...snapshotVersion(), publications: null },
    { ...snapshotVersion(), documents: [{ ...snapshotVersion().documents[0], planning_version_id: "B1" }] },
    { ...snapshotVersion(), publications: [{
      ...snapshotVersion().publications[0], id: "../documents/doc/download?ignored=",
    }] },
  ];
  harness.reply(detailPath("A1"), { json: invalidVersions[0] });
  await ui.record("A");
  for (const [index, version] of invalidVersions.entries()) {
    if (index > 0) {
      harness.reply(detailPath("A1"), { json: version });
      await ui.version("A1");
    }
    await harness.page.getByRole("alert").waitFor();
    await ui.noReady(); ui.assertNoDownloads();
    assert.equal(await ui.button(START).count(), 0);
    await ui.version("A2"); await ui.loaded("A2");
  }
  assert.equal(harness.requests.filter((entry) => entry.path.endsWith("/manifest.json")).length, 0,
    "Invalid owned metadata must never start manifest preparation");
  assert.equal(harness.requests.filter((entry) => /\/documents\/.*\/download/.test(entry.path)).length, 0,
    "Unsafe publication identity must never become a source document request");
  await harness.capture("malformed-and-foreign-metadata-recover-cleanly");
}

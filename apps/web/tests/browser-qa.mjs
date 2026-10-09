import { chromium } from "playwright";
import { mkdir, writeFile } from "node:fs/promises";
import { execFileSync, spawn } from "node:child_process";
import { join } from "node:path";
import assert from "node:assert/strict";
import { createHarness } from "./browser-harness.mjs";
import { runPointQueries } from "./browser-point-query.mjs";
import { emptyRecord, recordRecovery, recordReversal, recordRevisit } from "./browser-navigation-records.mjs";
import { manifestOwnership, versionOwnership, versionRecovery } from "./browser-navigation-versions.mjs";
import { oldRecordComparison, sameRecordComparison } from "./browser-navigation-comparison.mjs";
import { completeSnapshot, incompleteSnapshotRecovery, invalidManifestSnapshot, unpublishedSnapshot } from "./browser-snapshot-downloads.mjs";
import { cancelledSnapshot, recordSnapshotRevisit, tabSnapshotOwnership, versionSnapshotOwnership } from "./browser-snapshot-races.mjs";
import { invalidSnapshotMetadata } from "./browser-snapshot-validation.mjs";

const base = "http://127.0.0.1:3917";
const evidence = join(process.cwd(), ".browser-evidence");
await mkdir(evidence, { recursive: true });
const report = {
  passed: false,
  sourceCommit: execFileSync("git", ["rev-parse", "HEAD"], { encoding: "utf8" }).trim(),
  sourceTree: execFileSync("git", ["rev-parse", "HEAD^{tree}"], { encoding: "utf8" }).trim(),
  scenarios: [],
  pointQueryChecks: ["loading", "failed lookup", "successful empty", "successful hit with badges",
    "late failure ignored", "malformed payload", "mobile error state"],
  mapEvidence: "Real MapLibre canvas, center-point query coordinates and fresh zoom tile requests; no private map state or product instrumentation",
  pageErrors: [], routeErrors: [], blocked: [], requestLedger: [], snapshots: [], downloads: [], completions: 0,
};
const scenarios = [
  ["point-query", runPointQueries, false],
  ["record-response-reversal", recordReversal, true],
  ["pending-and-empty-record-clearing", emptyRecord, true],
  ["interrupted-and-repeated-record-navigation", recordRevisit, true],
  ["record-error-recovery", recordRecovery, true],
  ["version-detail-and-extent-ownership", versionOwnership, true],
  ["manifest-and-raster-ownership", manifestOwnership, true],
  ["version-and-extent-error-recovery", versionRecovery, true],
  ["late-old-record-comparison", oldRecordComparison, true],
  ["same-record-comparison-preservation", sameRecordComparison, true],
  ["metadata-snapshot-complete-download", completeSnapshot, true],
  ["metadata-snapshot-incomplete-recovery", incompleteSnapshotRecovery, true],
  ["metadata-snapshot-no-publications", unpublishedSnapshot, true],
  ["metadata-snapshot-invalid-manifests", invalidManifestSnapshot, true],
  ["metadata-snapshot-cancel-and-retry", cancelledSnapshot, true],
  ["metadata-snapshot-record-revisit", recordSnapshotRevisit, true],
  ["metadata-snapshot-version-ownership", versionSnapshotOwnership, true],
  ["metadata-snapshot-tab-unmount", tabSnapshotOwnership, true],
  ["metadata-snapshot-invalid-owned-metadata", invalidSnapshotMetadata, true],
];
const server = spawn("python3", ["-m", "http.server", "3917", "--bind", "127.0.0.1", "--directory", "out"], { stdio: "ignore" });
let browser;
let page;
try {
  for (let attempt = 0; attempt < 100; attempt++) {
    try {
      if ((await fetch(base)).ok) break;
    } catch {}
    if (attempt === 99) throw new Error("Static build server did not start");
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  browser = await chromium.launch({
    headless: true,
    ...(process.env.OQH_BROWSER_EXECUTABLE ? { executablePath: process.env.OQH_BROWSER_EXECUTABLE } : {}),
  });
  report.browserVersion = browser.version();
  report.browserExecutable = process.env.OQH_BROWSER_EXECUTABLE ?? "playwright-managed";
  for (const [name, run, navigation] of scenarios) {
    const harness = await createHarness(browser, { base, evidence, report, name, navigation });
    page = harness.page;
    report.currentScenario = name;
    await run(harness);
    await harness.finish();
    assert.deepEqual(report.pageErrors, []);
    assert.deepEqual(report.routeErrors, []);
    assert.deepEqual(report.blocked, []);
    await page.close();
    console.log(`Browser QA passed: ${name}`);
  }
  report.passed = true;
  report.syntheticPointRequests = report.requestLedger.filter((entry) => entry.path === "/v1/features/query").length;
  report.syntheticTileRequests = report.requestLedger.filter((entry) => entry.path.includes("/tiles/")).length;
  report.externalRequests = report.blocked.length;
  delete report.currentScenario;
  await writeFile(join(evidence, "browser-results.json"), JSON.stringify(report, null, 2));
  console.log("Browser QA passed: seven point-query checks, nine navigation scenarios and nine metadata snapshot scenarios; zero external requests; zero page errors");
} catch (error) {
  await page?.screenshot({ path: join(evidence, "failed-state.png"), fullPage: true }).catch(() => {});
  await writeFile(join(evidence, "failure.json"), JSON.stringify({ ...report, message: error.message }, null, 2));
  throw error;
} finally {
  await browser?.close();
  server.kill();
}

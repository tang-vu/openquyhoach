import assert from "node:assert/strict";
import { bounds, detail } from "./browser-fixtures.mjs";
import { detailPath, extentPath, failure, manifestPath, navigationUI, sameCenter } from "./browser-navigation-support.mjs";

export async function versionOwnership(harness) {
  const ui = navigationUI(harness);
  await harness.open();
  const oldDetail = harness.hold(detailPath("A1"));
  const oldExtent = harness.hold(extentPath("A1"));
  await ui.record("A");
  await oldDetail.requested(); await oldExtent.requested();
  await ui.version("A2"); await ui.loaded("A2");
  const center = await ui.center("new-version-extent-control");
  sameCenter(center, [20, 10]);
  oldDetail.release({ json: detail("A1") });
  oldExtent.release({ json: { bbox: bounds.A1 } });
  await ui.settle();
  await ui.loaded("A2");
  await ui.absent("Synthetic raster A1", "Synthetic source document A1");
  sameCenter(await ui.center("old-extent-cannot-reframe"), center);
  await ui.sources(["publication-A2"], "old-version-cannot-replace-publication");
  await harness.capture("A2-owns-detail-and-extent");
}

export async function manifestOwnership(harness) {
  const { page } = harness;
  const ui = navigationUI(harness);
  await harness.open();
  await ui.record("A"); await ui.loaded("A1");
  await ui.raster().check();
  await ui.sources(["publication-A1", "raster-A1"], "old-version-raster-control");
  const old = harness.hold(manifestPath("A1"));
  await ui.manifest(); await old.requested();
  await ui.version("A2"); await ui.loaded("A2");
  assert.equal(await ui.raster().isChecked(), false);
  old.release({ json: { fixture: "OLD-A1-MANIFEST" } });
  await ui.settle(); await ui.absent("OLD-A1-MANIFEST");
  await ui.sources(["publication-A2"], "new-version-clears-old-raster");

  const first = harness.hold(manifestPath("A2"));
  await ui.manifest(); await first.requested();
  await ui.manifest();
  await page.locator("pre").filter({ hasText: "publication-A2" }).waitFor();
  first.release(failure("OLD-MANIFEST-FAILURE"));
  await ui.settle(); await ui.absent("OLD-MANIFEST-FAILURE");
  assert.ok((await page.locator("pre").innerText()).includes("publication-A2"));

  harness.reply(manifestPath("A2"), failure("CURRENT-MANIFEST-FAILURE"));
  await ui.manifest();
  await page.getByRole("alert").filter({ hasText: "CURRENT-MANIFEST-FAILURE" }).waitFor();
  await ui.manifest();
  await page.locator("pre").filter({ hasText: "publication-A2" }).waitFor();
  await ui.absent("CURRENT-MANIFEST-FAILURE");
  await harness.capture("latest-manifest-recovers");
}

export async function versionRecovery(harness) {
  const { page } = harness;
  const ui = navigationUI(harness);
  await harness.open();
  harness.reply(detailPath("A1"), failure("CURRENT-VERSION-FAILURE"));
  harness.reply(extentPath("A1"), failure("CURRENT-EXTENT-FAILURE"));
  await ui.record("A");
  await page.locator(".error").filter({ hasText: "CURRENT-VERSION-FAILURE" }).waitFor();
  await ui.settle();
  await ui.version("A2"); await ui.loaded("A2");
  await ui.absent("CURRENT-VERSION-FAILURE");
  sameCenter(await ui.center("recovered-version-extent"), [20, 10]);
  const oldDetail = harness.hold(detailPath("A3"));
  const oldExtent = harness.hold(extentPath("A3"));
  await ui.version("A3"); await oldDetail.requested(); await oldExtent.requested();
  await ui.version("A2"); await ui.loaded("A2");
  const center = await ui.center("newer-version-before-stale-errors");
  oldDetail.release(failure("STALE-VERSION-FAILURE"));
  oldExtent.release(failure("STALE-EXTENT-FAILURE"));
  await ui.settle(); await ui.absent("STALE-VERSION-FAILURE", "STALE-EXTENT-FAILURE");
  sameCenter(await ui.center("stale-extent-failure-ignored"), center);
  await ui.sources(["publication-A2"], "version-error-recovery");
  await harness.capture("recovered-version");
}

import assert from "node:assert/strict";

// Preserve the original production-browser point-query checks verbatim.
export async function runPointQueries(harness) {
  const { page } = harness;
  const path = "/v1/features/query";
  const responses = { push: (response) => harness.reply(path, response) };
  const hold = () => {
    const pending = harness.hold(path);
    return (response) => pending.release(response);
  };
  const text = () => page.locator(".rightbar").innerText();
  const capture = (name) => harness.capture(name);
  const click = (x = 250, y = 300) =>
    page.locator(".maplibregl-canvas").click({ position: { x, y } });
  await harness.open();
  const hint = page.locator(".click-hint");
  assert.ok(await hint.isVisible());
  const hintBox = await hint.boundingBox();
  const mapBox = await page.locator(".maplibregl-canvas").boundingBox();
  assert.ok(
    hintBox.height < mapBox.height / 2,
    "The hint must not cover the map",
  );
  assert.equal(
    await hint.evaluate((element) => getComputedStyle(element).pointerEvents),
    "none",
  );
  await page.getByRole("button", { name: "Zoom in", exact: true }).click();
  await page.getByRole("button", { name: "Zoom out", exact: true }).click();
  await capture("initial-map");
  const first = hold();
  await click();
  await page
    .getByRole("status")
    .filter({ hasText: "Looking up this point" })
    .waitFor();
  assert.ok(!(await text()).includes("feature(s)"));
  await capture("loading");
  first({ status: 503, body: "Synthetic failure" });
  await page.getByRole("alert").filter({ hasText: "Lookup failed" }).waitFor();
  assert.ok(!(await text()).includes("No published planning geometry"));
  assert.ok(!(await text()).includes("0 feature(s)"));
  await capture("failure");

  responses.push({ json: { hits: [] } });
  await click(260, 310);
  await page.getByRole("status").filter({ hasText: "0 feature(s)" }).waitFor();
  assert.ok(
    (await text()).includes("No published planning geometry at this point"),
  );
  await capture("successful-empty");

  const hit = {
    feature_id: "synthetic-feature",
    layer: "land_use",
    dataset_id: "synthetic-dataset",
    derivation_level: "derived_manual",
    review_status: "approved",
    classification: "synthetic-class",
    properties: { fixture: "synthetic only" },
    distance_m: 0,
    provenance: {
      planning_version: {
        id: "synthetic-version",
        label: "Synthetic v1",
        approval_decision_number: "SYNTHETIC-ONLY",
        approval_date: null,
        legal_status: "unknown",
      },
      artifact: {
        id: "synthetic-artifact",
        sha256: "0".repeat(64),
        filename: "synthetic.json",
        retrieved_at: null,
        canonical_url: null,
      },
      source: {
        key: "demo/offline-test",
        name: "Synthetic test",
        base_url: null,
      },
    },
  };
  responses.push({ json: { hits: [hit] } });
  await click(270, 320);
  await page.getByRole("status").filter({ hasText: "1 feature(s)" }).waitFor();
  assert.equal(
    await page.locator(".badge.derived").innerText(),
    "derived_manual",
  );
  assert.ok((await text()).includes("SYNTHETIC-ONLY"));
  await capture("successful-hit");

  const old = hold();
  await click(280, 330);
  await page
    .getByRole("status")
    .filter({ hasText: "Looking up this point" })
    .waitFor();
  responses.push({ json: { hits: [] } });
  await click(290, 340);
  await page.getByRole("status").filter({ hasText: "0 feature(s)" }).waitFor();
  const latest = await text();
  old({ status: 503, body: "Old synthetic failure" });
  await page.waitForLoadState("networkidle");
  assert.equal(await text(), latest);

  responses.push({ json: { hits: null } });
  await click(300, 350);
  await page.getByRole("alert").filter({ hasText: "Lookup failed" }).waitFor();
  assert.ok(!(await text()).includes("No published planning geometry"));
  await page.setViewportSize({ width: 390, height: 844 });
  await capture("failure-mobile");
}

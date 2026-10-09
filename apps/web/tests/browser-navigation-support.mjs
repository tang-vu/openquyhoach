import assert from "node:assert/strict";
import { until } from "./browser-harness.mjs";

export const recordPath = (id) => `/v1/planning-records/${id}`;
export const detailPath = (id) => `/v1/planning-versions/${id}`;
export const extentPath = (id) => `/v1/versions/${id}/extent`;
export const manifestPath = (id) => `/v1/publications/publication-${id}/manifest.json`;
export const failure = (body) => ({ status: 503, body });

export function navigationUI(harness) {
  const { page, requests } = harness;
  const sidebar = page.locator(".sidebar");
  const item = (title) => sidebar.locator(".item").filter({ hasText: title });
  const text = () => sidebar.innerText();
  // fitBounds uses a 600 ms ease. Waiting also lets real MapLibre tile work settle;
  // networkidle cannot be used while an intentionally deferred request is open.
  const settle = () => page.waitForTimeout(800);
  async function selected(title) {
    assert.equal(await item(title).evaluate((el) => el.style.borderColor), "var(--accent)");
  }
  return {
    text, settle, selected,
    record: (id) => item(`Synthetic record ${id}`).click(),
    version: (id) => item(`Synthetic version ${id}`).click(),
    tab: (name) => page.locator(".tabs").getByRole("button", { name, exact: true }).click(),
    async loaded(id) {
      await sidebar.locator(".title").filter({ hasText: `Synthetic source document ${id}` }).waitFor();
      await selected(`Synthetic version ${id}`);
      await settle();
    },
    async absent(...values) {
      const content = await text();
      for (const value of values) assert.ok(!content.includes(value), `Unexpected stale content: ${value}`);
    },
    raster: () => page.getByLabel("show scanned map overlay"),
    manifest: () => page.getByRole("button", { name: "view manifest", exact: true }).click(),
    async sources(expected, label) {
      await settle();
      const start = requests.length;
      harness.phase(label);
      await page.getByRole("button", { name: "Zoom in", exact: true }).click();
      await settle();
      const owners = () => [...new Set(requests.slice(start).flatMap((entry) => {
        const match = entry.path.match(/^\/v1\/(?:publications|rasters)\/([^/]+)\/tiles\//);
        return match ? [match[1]] : [];
      }))].sort();
      if (expected.length) await until(() => owners().length >= expected.length, "Expected fresh synthetic tile requests");
      assert.deepEqual(owners(), [...expected].sort(), `Tile ownership after ${label}`);
    },
    async center(label) {
      await settle();
      const start = requests.length;
      harness.phase(label);
      const canvas = page.locator(".maplibregl-canvas");
      const box = await canvas.boundingBox();
      await canvas.click({ position: { x: box.width / 2, y: box.height / 2 } });
      await until(() => requests.slice(start).some((entry) => entry.path === "/v1/features/query"), "Center-point query missing");
      const query = requests.slice(start).find((entry) => entry.path === "/v1/features/query").query;
      return [Number(query.lon), Number(query.lat)];
    },
    async compare() {
      await this.tab("compare");
      await sidebar.locator("select").nth(0).selectOption("A1");
      await sidebar.locator("select").nth(1).selectOption("A2");
      await page.getByRole("button", { name: "Compare", exact: true }).click();
    },
  };
}

export function sameCenter(actual, expected) {
  assert.ok(actual.every((value, index) => Math.abs(value - expected[index]) < 0.01),
    `Expected center ${expected.join(", ")}; received ${actual.join(", ")}`);
}

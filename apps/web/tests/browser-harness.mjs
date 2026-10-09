import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { readFile, writeFile } from "node:fs/promises";
import { join } from "node:path";
import { fixtureResponse } from "./browser-fixtures.mjs";

export async function until(check, message) {
  const deadline = Date.now() + 10000;
  while (Date.now() < deadline) {
    if (await check()) return;
    await new Promise((resolve) => setTimeout(resolve, 25));
  }
  assert.fail(message);
}

export async function createHarness(browser, options) {
  const { base, evidence, report, name, navigation = false } = options;
  const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
  page.setDefaultTimeout(10000);
  const queues = new Map();
  const gates = [];
  const requests = [];
  let downloadSequence = 0;
  let phase = "initial";
  const enqueue = (path, response) => {
    if (!queues.has(path)) queues.set(path, []);
    queues.get(path).push(response);
  };
  page.on("pageerror", (error) => report.pageErrors.push({ scenario: name, message: error.message }));
  await page.route("**/*", async (route) => {
    const url = new URL(route.request().url());
    const entry = {
      scenario: name, phase, path: url.pathname,
      query: Object.fromEntries(url.searchParams), method: route.request().method(),
      kind: url.origin === base ? "local-static" : "synthetic-api",
    };
    report.requestLedger.push(entry); requests.push(entry);
    if (url.origin === base) return route.continue();
    if (url.origin !== "http://localhost:8000") {
      entry.kind = "blocked"; report.blocked.push(url.href);
      return route.abort();
    }
    try {
      const queued = queues.get(url.pathname)?.shift();
      queued?.seen?.();
      const response = queued ? await queued.response : fixtureResponse(url, navigation);
      assert.ok(response, `Unexpected synthetic API request: ${url.pathname}`);
      entry.status = response.status ?? 200;
      await route.fulfill({ headers: { "access-control-allow-origin": base }, ...response });
      entry.completion = ++report.completions;
    } catch (error) {
      report.routeErrors.push({ scenario: name, path: url.pathname, message: error.message });
      await route.abort().catch(() => {});
    }
  });
  return {
    page, requests,
    phase(value) { phase = value; },
    reply(path, response) { enqueue(path, { response }); },
    hold(path) {
      let release;
      const state = { seen: false, released: false };
      const response = new Promise((resolve) => { release = resolve; });
      enqueue(path, { response, seen: () => { state.seen = true; } });
      gates.push(state);
      return {
        requested: () => until(() => state.seen, `Request did not start: ${path}`),
        release(value) { state.released = true; release(value); },
      };
    },
    async open() {
      await page.goto(base);
      await page.locator(".maplibregl-canvas").waitFor();
      await page.waitForLoadState("networkidle");
    },
    async capture(label, { fullPage = true } = {}) {
      await page.screenshot({ path: join(evidence, `${name}-${label}.png`), fullPage });
      report.snapshots.push({ scenario: name, phase: label, viewport: page.viewportSize(), fullPage,
        sidebar: await page.locator(".sidebar").innerText() });
    },
    async recordDownload(download) {
      const path = await download.path();
      assert.ok(path, "A completed browser download must have a readable file");
      const bytes = await readFile(path);
      const file = `${name}-download-${String(++downloadSequence).padStart(2, "0")}.json`;
      await writeFile(join(evidence, file), bytes);
      report.downloads.push({
        scenario: name, phase, file, viewport: page.viewportSize(), suggestedFilename: download.suggestedFilename(),
        bytes: bytes.length, sha256: createHash("sha256").update(bytes).digest("hex"),
      });
      return bytes;
    },
    async finish() {
      assert.ok(gates.every((gate) => gate.seen && gate.released), "All held requests must be exercised and released");
      assert.ok([...queues.values()].every((queue) => queue.length === 0), "All queued responses must be consumed");
      await page.waitForLoadState("networkidle");
      report.scenarios.push(name);
    },
  };
}

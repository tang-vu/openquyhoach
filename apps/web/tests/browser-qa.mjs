import { chromium } from "playwright";
import { mkdir, writeFile } from "node:fs/promises";
import { execFileSync, spawn } from "node:child_process";
import { join } from "node:path";
import assert from "node:assert/strict";

const base = "http://127.0.0.1:3917";
const evidence = join(process.cwd(), ".browser-evidence");
await mkdir(evidence, { recursive: true });
const server = spawn(
  "python3",
  ["-m", "http.server", "3917", "--bind", "127.0.0.1", "--directory", "out"],
  { stdio: "ignore" },
);
let browser;
try {
  for (let attempt = 0; attempt < 100; attempt++) {
    try {
      const response = await fetch(base);
      if (response.ok) break;
    } catch {}
    if (attempt === 99) throw new Error("Static build server did not start");
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({
    viewport: { width: 1280, height: 900 },
  });
  const errors = [];
  const blocked = [];
  const responses = [];
  const calls = [];
  const requestLedger = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.route("**/*", async (route) => {
    const url = new URL(route.request().url());
    if (url.origin === base) {
      requestLedger.push({ kind: "local-static", path: url.pathname });
      return route.continue();
    }
    if (url.origin === "http://localhost:8000") {
      requestLedger.push({ kind: "synthetic-api", path: url.pathname });
      if (["/v1/planning-records", "/v1/publications"].includes(url.pathname))
        return route.fulfill({ json: { items: [] } });
      if (url.pathname === "/v1/features/query") {
        calls.push(url.href);
        const response = responses.shift();
        assert.ok(
          response,
          "Point query must have an explicit synthetic response",
        );
        return route.fulfill(await response);
      }
    }
    blocked.push(url.href);
    await route.abort();
  });

  function hold() {
    let resolve;
    const response = new Promise((done) => {
      resolve = done;
    });
    responses.push(response);
    return resolve;
  }
  async function text() {
    return page.locator(".rightbar").innerText();
  }
  async function capture(name) {
    await page.screenshot({
      path: join(evidence, `${name}.png`),
      fullPage: true,
    });
  }
  async function click(x = 250, y = 300) {
    await page.locator(".maplibregl-canvas").click({ position: { x, y } });
  }

  await page.goto(base);
  await page.locator(".maplibregl-canvas").waitFor();
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
  assert.deepEqual(errors, []);
  assert.deepEqual(blocked, []);
  await writeFile(
    join(evidence, "browser-results.json"),
    JSON.stringify(
      {
        passed: true,
        sourceCommit: execFileSync("git", ["rev-parse", "HEAD"], {
          encoding: "utf8",
        }).trim(),
        sourceTree: execFileSync("git", ["rev-parse", "HEAD^{tree}"], {
          encoding: "utf8",
        }).trim(),
        scenarios: [
          "loading",
          "failed lookup",
          "successful empty",
          "successful hit with badges",
          "late failure ignored",
          "malformed payload",
          "mobile error state",
        ],
        syntheticPointRequests: calls.length,
        externalRequests: 0,
        pageErrors: errors,
        requestLedger,
      },
      null,
      2,
    ),
  );
  console.log(
    "Browser QA passed: seven synthetic scenarios; zero external requests; zero page errors",
  );
} finally {
  await browser?.close();
  server.kill();
}

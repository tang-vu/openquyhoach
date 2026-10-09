import { act } from "react";
import { expect, it, vi } from "vitest";
import { API } from "@/lib/api";
import {
  deferred,
  json,
  setupHarness,
  syntheticHit,
} from "./point-query-support";

const ui = setupHarness();

it("reports a failed lookup instead of claiming no geometry exists", async () => {
  vi.mocked(fetch).mockRejectedValueOnce(
    new Error("Synthetic offline failure"),
  );
  await ui.click();
  expect(ui.text()).not.toContain("No published planning geometry");
  expect(ui.text()).toContain("Lookup failed");
  expect(ui.text()).not.toContain("0 feature(s)");
  expect(ui.element('[role="alert"]')?.textContent).toContain(
    "Click the map to try again",
  );
});

it("announces loading for the current point and clears stale results", async () => {
  vi.mocked(fetch).mockResolvedValueOnce(json({ hits: [syntheticHit] }));
  await ui.click();
  const response = deferred<Response>();
  vi.mocked(fetch).mockReturnValueOnce(response.promise);
  const { pending } = await ui.startClick(3, 4);
  expect(ui.element('[role="status"]')?.textContent).toContain(
    "Looking up this point",
  );
  expect(ui.text()).toContain("4.00000, 3.00000");
  expect(ui.text()).not.toContain("SYNTHETIC-ONLY");
  expect(ui.text()).not.toContain("feature(s)");
  expect(ui.text()).not.toContain("No published planning geometry");
  await act(async () => {
    response.resolve(json({ hits: [] }));
    await pending;
  });
});

it("shows the coverage disclaimer only after a successful empty lookup", async () => {
  expect(ui.text()).toContain("Click the map to inspect a point");
  vi.mocked(fetch).mockResolvedValueOnce(json({ hits: [] }));
  await ui.click();
  expect(ui.text()).toContain("No published planning geometry at this point");
  expect(ui.text()).toContain("That is a coverage statement, not a legal one");
  expect(ui.text()).toContain("0 feature(s)");
  expect(ui.element('[role="alert"]')).toBeNull();
});

it("recovers on the next click and preserves provenance, badges and query parameters", async () => {
  await ui.click();
  vi.mocked(fetch).mockResolvedValueOnce(json({ hits: [syntheticHit] }));
  await ui.click(-1.5, 2.25);
  expect(ui.text()).not.toContain("Lookup failed");
  for (const text of [
    "1 feature(s)",
    "Synthetic v1",
    "SYNTHETIC-ONLY",
    "synthetic.json",
    "demo/offline-test",
    "DEMO",
  ])
    expect(ui.text()).toContain(text);
  expect(ui.element(".badge.derived")?.textContent).toBe("derived_manual");
  expect(ui.text()).toContain("approved");
  expect(ui.text()).toContain("0".repeat(24));
  const url = new URL(vi.mocked(fetch).mock.calls[1][0] as string);
  expect(url.origin).toBe(new URL(API).origin);
  expect(url.pathname).toBe("/v1/features/query");
  expect(Object.fromEntries(url.searchParams)).toEqual({
    lon: "-1.5",
    lat: "2.25",
    buffer_m: "60",
  });
});

it.each([
  ["official_vector", "pending", "official"],
  ["derived_machine_unreviewed", "pending", "unreviewed"],
])(
  "preserves %s review badges",
  async (derivation_level, review_status, css) => {
    vi.mocked(fetch).mockResolvedValueOnce(
      json({ hits: [{ ...syntheticHit, derivation_level, review_status }] }),
    );
    await ui.click();
    expect(ui.element(`.badge.${css}`)?.textContent).toBe(derivation_level);
    expect(ui.text()).toContain(review_status);
  },
);

it.each([
  null,
  {},
  { hits: null },
  { hits: "invalid" },
  { hits: [null] },
  { hits: [{ ...syntheticHit, derivation_level: null }] },
  { hits: [{ ...syntheticHit, properties: null }] },
  { hits: [{ ...syntheticHit, provenance: null }] },
  { hits: [{ ...syntheticHit, provenance: { source: { key: 1 } } }] },
  { hits: [{ ...syntheticHit, provenance: { artifact: { sha256: {} } } }] },
  {
    hits: [
      { ...syntheticHit, provenance: { planning_version: { label: {} } } },
    ],
  },
])(
  "treats a malformed successful payload as a failed lookup: %j",
  async (payload) => {
    vi.mocked(fetch).mockResolvedValueOnce(json(payload));
    await ui.click();
    expect(ui.element('[role="alert"]')?.textContent).toContain(
      "Lookup failed",
    );
    expect(ui.text()).not.toContain("No published planning geometry");
  },
);

it.each([
  new Response("Synthetic 503", { status: 503 }),
  new Response("not JSON"),
])(
  "reports HTTP and JSON errors without a coverage conclusion",
  async (response) => {
    vi.mocked(fetch).mockResolvedValueOnce(response);
    await ui.click();
    expect(ui.text()).toContain("Lookup failed");
    expect(ui.text()).not.toContain("No published planning geometry");
    expect(ui.text()).not.toContain("Synthetic 503");
  },
);

it.each([
  {},
  {
    dataset: null,
    layer: null,
    artifact: null,
    source: null,
    planning_version: null,
    derivation_level: null,
    review_status: null,
  },
  {
    dataset: { id: "synthetic-dataset", name: null },
    planning_version: {
      id: "synthetic-version",
      label: null,
      approval_decision_number: null,
      approval_date: null,
      legal_status: "unknown",
    },
    artifact: {
      id: "synthetic-artifact",
      sha256: "0".repeat(64),
      filename: null,
      retrieved_at: null,
      canonical_url: null,
    },
    source: {
      key: "demo/offline-test",
      name: "Synthetic test",
      base_url: null,
    },
  },
])(
  "accepts optional/null provenance without inventing evidence",
  async (provenance) => {
    vi.mocked(fetch).mockResolvedValueOnce(
      json({ hits: [{ ...syntheticHit, classification: null, provenance }] }),
    );
    await ui.click();
    expect(ui.text()).toContain("1 feature(s)");
    expect(ui.text()).not.toContain("Lookup failed");
    expect(ui.text()).not.toContain("SYNTHETIC-ONLY");
  },
);

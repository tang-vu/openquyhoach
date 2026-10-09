import { deferred, detail, publication, recordDetail, setup } from "./navigation-support";
import { expect, it, vi } from "vitest";
import { api } from "@/lib/api";

const ui = setup();

it.each(["success", "failure"])("ignores old record %s while the new record is pending", async outcome => {
  const old = deferred<Awaited<ReturnType<typeof api.recordDetail>>>();
  const next = deferred<Awaited<ReturnType<typeof api.recordDetail>>>();
  vi.mocked(api.recordDetail).mockReturnValueOnce(old.promise).mockReturnValueOnce(next.promise);
  await ui.click("Synthetic record A");
  await ui.click("Synthetic record B");
  if (outcome === "success") await ui.settle(old, recordDetail("A"));
  else await ui.reject(old, "OLD RECORD FAILURE");
  expect(ui.text()).toContain("Loading versions");
  expect(ui.text()).not.toContain("Synthetic version A1");
  expect(ui.text()).not.toContain("OLD RECORD FAILURE");
  expect(ui.sources()).toEqual([]);
  await ui.settle(next, recordDetail("B"));
  expect(ui.text()).toContain("Synthetic source document B1");
});

it.each(["success", "failure"])("ignores old version %s after an A1→A2→A1 revisit", async outcome => {
  const old = deferred<Awaited<ReturnType<typeof api.versionDetail>>>();
  vi.mocked(api.versionDetail).mockImplementation(id => id === "A1" ? old.promise : Promise.resolve(detail(id)));
  await ui.click("Synthetic record A");
  await ui.click("Synthetic version A2");
  vi.mocked(api.versionDetail).mockImplementation(async id => detail(id));
  await ui.click("Synthetic version A1");
  if (outcome === "success") {
    const stale = detail("A1"); stale.documents[0].title = "OLD A1 DOCUMENT";
    await ui.settle(old, stale);
  } else await ui.reject(old, "OLD VERSION FAILURE");
  expect(ui.text()).toContain("Synthetic source document A1");
  expect(ui.text()).not.toContain("OLD A1 DOCUMENT");
  expect(ui.text()).not.toContain("OLD VERSION FAILURE");
});

it.each(["success", "failure"])("latest manifest request owns the same publication after old %s", async outcome => {
  await ui.click("Synthetic record A");
  const old = deferred<Record<string, unknown>>();
  vi.mocked(api.manifest).mockReturnValueOnce(old.promise).mockResolvedValueOnce({ fixture: "NEW MANIFEST" });
  await ui.click("view manifest", "button");
  await ui.click("view manifest", "button");
  if (outcome === "success") await ui.settle(old, { fixture: "OLD MANIFEST" });
  else await ui.reject(old, "OLD MANIFEST FAILURE");
  expect(ui.text()).toContain("NEW MANIFEST");
  expect(ui.text()).not.toContain("OLD MANIFEST");
});

it("failed and empty records keep the camera, clear layers, and recover on a new record", async () => {
  await ui.click("Synthetic record A");
  const bounds = ui.lastBounds();
  vi.mocked(api.recordDetail).mockRejectedValueOnce(new Error("CURRENT RECORD FAILURE"));
  await ui.click("Synthetic record B");
  expect(ui.text()).toContain("CURRENT RECORD FAILURE");
  expect(ui.sources()).toEqual([]);
  expect(ui.lastBounds()).toEqual(bounds);
  await ui.click("Synthetic record E");
  expect(ui.text()).not.toContain("CURRENT RECORD FAILURE");
  expect(ui.text()).toContain("No versions available");
  expect(ui.lastBounds()).toEqual(bounds);
  await ui.click("Synthetic record B");
  expect(ui.text()).toContain("Synthetic source document B1");
});

it("a publication catalog completing after an empty-record selection cannot restore layers", async () => {
  const pending = deferred<Awaited<ReturnType<typeof api.publications>>>();
  vi.mocked(api.publications).mockReturnValue(pending.promise);
  await ui.remount();
  await ui.click("Synthetic record A");
  await ui.click("Synthetic record E");
  await ui.settle(pending, { items: [publication("A1")] });
  expect(ui.sources()).toEqual([]);
});

it.each(["success", "failure"])("ignores old version %s while a newer version detail is pending", async outcome => {
  const old = deferred<Awaited<ReturnType<typeof api.versionDetail>>>();
  const next = deferred<Awaited<ReturnType<typeof api.versionDetail>>>();
  vi.mocked(api.versionDetail).mockImplementation(id => id === "A1" ? old.promise : next.promise);
  await ui.click("Synthetic record A");
  await ui.click("Synthetic version A2");
  if (outcome === "success") await ui.settle(old, detail("A1"));
  else await ui.reject(old, "OLD VERSION FAILURE");
  expect(ui.text()).toContain("loading…");
  expect(ui.text()).not.toContain("Synthetic source document A1");
  expect(ui.text()).not.toContain("OLD VERSION FAILURE");
  await ui.settle(next, detail("A2"));
  expect(ui.text()).toContain("Synthetic source document A2");
});

it("record navigation preserves the explicit point-query coordinate and its pending result", async () => {
  const point = deferred<Awaited<ReturnType<typeof api.pointQuery>>>();
  vi.mocked(api.pointQuery).mockReturnValueOnce(point.promise);
  const { pending } = await ui.clickMap(1, 2);
  await ui.click("Synthetic record A");
  await ui.click("Synthetic record B");
  expect(ui.text()).toContain("2.00000, 1.00000");
  expect(ui.text()).toContain("Looking up this point");
  await ui.settle(point, { hits: [] });
  await pending;
  expect(ui.text()).toContain("2.00000, 1.00000");
  expect(ui.text()).toContain("0 feature(s)");
  expect(api.pointQuery).toHaveBeenCalledExactlyOnceWith(1, 2);
});

it.each(["success", "failure"])("record %s after Page unmount cannot start version work", async outcome => {
  const record = deferred<Awaited<ReturnType<typeof api.recordDetail>>>();
  vi.mocked(api.recordDetail).mockReturnValueOnce(record.promise);
  await ui.click("Synthetic record A");
  await ui.hide();
  if (outcome === "success") await ui.settle(record, recordDetail("A"));
  else await ui.reject(record, "UNMOUNTED RECORD FAILURE");
  expect(ui.text()).toBe("");
  expect(api.versionDetail).not.toHaveBeenCalled();
  expect(api.versionExtent).not.toHaveBeenCalled();
});

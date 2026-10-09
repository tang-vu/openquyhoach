import { act } from "react";
import { expect, it, vi } from "vitest";
import {
  deferred,
  json,
  maps,
  setupHarness,
  syntheticHit,
} from "./point-query-support";

const ui = setupHarness();

it.each(["success", "failure"])(
  "ignores an older %s while the latest point is loading",
  async (outcome) => {
    const old = deferred<Response>();
    const latest = deferred<Response>();
    vi.mocked(fetch)
      .mockReturnValueOnce(old.promise)
      .mockReturnValueOnce(latest.promise);
    const first = await ui.startClick(1, 2);
    const second = await ui.startClick(3, 4);
    await act(async () => {
      if (outcome === "success") old.resolve(json({ hits: [syntheticHit] }));
      else old.reject(new Error("Old synthetic failure"));
      await first.pending;
    });
    expect(ui.element('[role="status"]')).not.toBeNull();
    expect(ui.text()).toContain("4.00000, 3.00000");
    expect(ui.text()).not.toContain("SYNTHETIC-ONLY");
    expect(ui.text()).not.toContain("Lookup failed");
    await act(async () => {
      latest.resolve(json({ hits: [] }));
      await second.pending;
    });
  },
);

it.each([
  ["success", "success"],
  ["failure", "success"],
  ["success", "failure"],
  ["failure", "failure"],
])("ignores old %s after the newer %s settles", async (older, newer) => {
  const old = deferred<Response>();
  vi.mocked(fetch).mockReturnValueOnce(old.promise);
  const first = await ui.startClick(1, 2);
  if (newer === "success")
    vi.mocked(fetch).mockResolvedValueOnce(json({ hits: [] }));
  else
    vi.mocked(fetch).mockRejectedValueOnce(new Error("New synthetic failure"));
  await ui.click(3, 4);
  const settled = ui.text();
  await act(async () => {
    if (older === "success") old.resolve(json({ hits: [syntheticHit] }));
    else old.reject(new Error("Old synthetic failure"));
    await first.pending;
  });
  expect(ui.text()).toBe(settled);
  expect(ui.text()).toContain("4.00000, 3.00000");
});

it.each([false, true])(
  "gives repeated A→B→A clicks independent ownership (middle click: %s)",
  async (middle) => {
    const old = deferred<Response>();
    vi.mocked(fetch).mockReturnValueOnce(old.promise);
    const first = await ui.startClick();
    if (middle) {
      vi.mocked(fetch).mockResolvedValueOnce(json({ hits: [] }));
      await ui.click(3, 4);
    }
    vi.mocked(fetch).mockResolvedValueOnce(json({ hits: [syntheticHit] }));
    await ui.click();
    await act(async () => {
      old.reject(new Error("Old failure"));
      await first.pending;
    });
    expect(ui.text()).toContain("SYNTHETIC-ONLY");
    expect(ui.text()).not.toContain("Lookup failed");
  },
);

it.each(["success", "failure"])(
  "does not publish a late %s after map unmount",
  async (outcome) => {
    const notify = vi.fn();
    await ui.render({ notify });
    const response = deferred<Response>();
    vi.mocked(fetch).mockReturnValueOnce(response.promise);
    const { pending } = await ui.startClick();
    const oldMap = maps.current!;
    expect(notify).toHaveBeenCalledWith({ lon: 1, lat: 2, status: "loading" });
    await ui.render({ visible: false, notify });
    expect(oldMap.removed).toBe(true);
    notify.mockClear();
    const requests = vi.mocked(fetch).mock.calls.length;
    await act(async () => {
      await oldMap.click(7, 8);
    });
    expect(fetch).toHaveBeenCalledTimes(requests);
    await act(async () => {
      if (outcome === "success") response.resolve(json({ hits: [] }));
      else response.reject(new Error("Unmounted failure"));
      await pending;
    });
    expect(notify).not.toHaveBeenCalled();
  },
);

it("does not let a previous map instance overwrite a remounted selection", async () => {
  const old = deferred<Response>();
  vi.mocked(fetch).mockReturnValueOnce(old.promise);
  const first = await ui.startClick();
  await ui.render({ visible: false });
  await ui.render({ visible: true });
  vi.mocked(fetch).mockResolvedValueOnce(json({ hits: [syntheticHit] }));
  await ui.click(3, 4);
  await act(async () => {
    old.resolve(json({ hits: [] }));
    await first.pending;
  });
  expect(ui.text()).toContain("SYNTHETIC-ONLY");
  expect(ui.text()).toContain("4.00000, 3.00000");
});

it("invalidates pending work when the selection callback changes", async () => {
  const oldNotify = vi.fn();
  await ui.render({ notify: oldNotify });
  const old = deferred<Response>();
  vi.mocked(fetch).mockReturnValueOnce(old.promise);
  const first = await ui.startClick();
  const notify = vi.fn();
  await ui.render({ notify });
  oldNotify.mockClear();
  await act(async () => {
    old.resolve(json({ hits: [] }));
    await first.pending;
  });
  expect(oldNotify).not.toHaveBeenCalled();
  expect(notify).not.toHaveBeenCalled();
  vi.mocked(fetch).mockResolvedValueOnce(json({ hits: [] }));
  await ui.click();
  expect(notify).toHaveBeenLastCalledWith({
    lon: 1,
    lat: 2,
    status: "success",
    hits: [],
  });
});

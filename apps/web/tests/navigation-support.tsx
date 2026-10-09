import { act, StrictMode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, vi } from "vitest";
import Page from "@/app/page";
import { api, type PlanningRecord, type PlanningVersion, type Publication } from "@/lib/api";

const maps = vi.hoisted(() => ({ current: null as any }));
const search = vi.hoisted(() => ({ pick: null as null | ((hit: import("@/lib/api").SearchHit) => void) }));
vi.mock("maplibre-gl", () => ({ default: {
  Map: class {
    sources: Record<string, unknown> = {};
    layers: { id: string }[] = [];
    fits: unknown[] = [];
    loaded = true;
    loadListeners: (() => void)[] = [];
    loadHandlers: (() => void)[] = [];
    busyAfterSourceChange = false;
    clickListener: ((event: { lngLat: { lng: number; lat: number } }) => Promise<void>) | null = null;
    constructor() { maps.current = this; }
    on(event: string, callback: any) {
      if (event === "click") this.clickListener = callback;
      if (event === "load") this.loadHandlers.push(callback);
    }
    async click(lng: number, lat: number) { await this.clickListener!({ lngLat: { lng, lat } }); }
    once(event: string, callback: () => void) {
      if (event !== "load") throw new Error("Unexpected synthetic map event");
      this.loadListeners.push(callback);
    }
    off(event: string, callback: () => void) {
      if (event === "load") this.loadListeners = this.loadListeners.filter(fn => fn !== callback);
    }
    addControl() {}
    remove() {}
    isStyleLoaded() { return this.loaded; }
    getStyle() { return { sources: this.sources, layers: this.layers }; }
    getSource(id: string) { return this.sources[id]; }
    getLayer(id: string) { return this.layers.find(x => x.id === id); }
    addSource(id: string, source: unknown) {
      this.sources[id] = source;
      if (this.busyAfterSourceChange) this.loaded = false;
    }
    addLayer(layer: { id: string }) { this.layers.push(layer); }
    removeSource(id: string) { delete this.sources[id]; }
    removeLayer(id: string) { this.layers = this.layers.filter(x => x.id !== id); }
    fitBounds(bounds: unknown) { this.fits.push(bounds); }
    load() {
      this.loaded = true;
      const listeners = this.loadListeners; this.loadListeners = [];
      for (const handler of this.loadHandlers) handler();
      for (const listener of listeners) listener();
    }
  },
  NavigationControl: class {},
}}));
vi.mock("@/components/SearchBox", () => ({ default: ({ onPick }: { onPick: typeof search.pick }) => {
  search.pick = onPick; return null;
} }));
vi.mock("@/components/AdminPanel", () => ({ default: () => null }));
vi.mock("@/components/SourcesPanel", () => ({ default: () => null }));
vi.mock("@/lib/api", async (importOriginal) => {
  const original = await importOriginal<typeof import("@/lib/api")>();
  return { ...original, api: { ...original.api,
    records: vi.fn(), publications: vi.fn(), recordDetail: vi.fn(),
    versionDetail: vi.fn(), versionExtent: vi.fn(), manifest: vi.fn(),
    compare: vi.fn(), dataset: vi.fn(),
    pointQuery: vi.fn(),
  }};
});

export function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}

export function record(id: string): PlanningRecord {
  return { id, title: `Synthetic record ${id}`, planning_type: null,
    scale: null, jurisdiction: null, status: "unknown", data_class: "synthetic" };
}
export function version(id: string, recordId = id.slice(0, 1)): PlanningVersion {
  return { id, planning_record_id: recordId, version_kind: "synthetic",
    version_label: `Synthetic version ${id}`, approval_decision_number: `DEMO-${id}`,
    approval_date: null, legal_status: "unknown" };
}
export const versions = { A: [version("A1"), version("A2")], B: [version("B1")], E: [] };
export function publication(id: string): Publication {
  return { id: `publication-${id}`, planning_version_id: id,
    status: "synthetic", checksum_sha256: null, bbox: null,
    min_zoom: null, max_zoom: null, published_at: null };
}
export function detail(id: string): Awaited<ReturnType<typeof api.versionDetail>> {
  return { ...version(id), datasets: [{
    id: `raster-${id}`, name: `Synthetic raster ${id}`, dataset_group: "synthetic",
    dataset_type: "raster", derivation_level: "derived_manual", review_status: "approved",
    quality_state: "synthetic", published: true,
  }], documents: [{
    id: `document-${id}`, document_type: "synthetic", document_number: `DEMO-${id}`,
    title: `Synthetic source document ${id}`, signed_date: null,
    issuing_authority: null, metadata_origin: "derived_machine", page_count: null,
    artifact_id: null, planning_version_id: id,
  }], publications: [publication(id)] };
}
export const bbox = { A1: [1, 2, 3, 4], A2: [5, 6, 7, 8], B1: [9, 10, 11, 12] };
export function recordDetail(id: keyof typeof versions) {
  return { ...record(id), versions: versions[id] };
}

export function setup() {
  let root: Root;
  let container: HTMLDivElement;
  beforeEach(async () => {
    vi.resetAllMocks();
    vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);
    vi.stubGlobal("fetch", vi.fn(() => { throw new Error("Unexpected network request"); }));
    vi.mocked(api.records).mockResolvedValue({ items: [record("A"), record("B"), record("E")] });
    vi.mocked(api.publications).mockResolvedValue({ items: [publication("A1"), publication("A2"), publication("B1")] });
    vi.mocked(api.recordDetail).mockImplementation(async id => recordDetail(id as keyof typeof versions));
    vi.mocked(api.versionDetail).mockImplementation(async id => detail(id));
    vi.mocked(api.versionExtent).mockImplementation(async id => ({ bbox: bbox[id as keyof typeof bbox] }));
    vi.mocked(api.manifest).mockImplementation(async id => ({ fixture: "synthetic", publication: id }));
    vi.mocked(api.compare).mockRejectedValue(new Error("Comparison must be explicitly mocked"));
    vi.mocked(api.dataset).mockRejectedValue(new Error("Dataset must be explicitly mocked"));
    vi.mocked(api.pointQuery).mockResolvedValue({ hits: [] });
    container = document.createElement("div"); document.body.append(container);
    root = createRoot(container);
    await act(async () => root.render(<StrictMode><Page /></StrictMode>));
  });
  afterEach(async () => {
    await act(async () => root.unmount());
    expect(fetch).not.toHaveBeenCalled();
    container.remove(); vi.unstubAllGlobals();
  });
  function find(text: string, selector: string) {
    const element = [...container.querySelectorAll<HTMLElement>(selector)]
      .find(el => el.textContent?.includes(text));
    if (!element) throw new Error(`Missing synthetic element: ${text}`);
    return element;
  }
  return {
    text: () => container.textContent ?? "",
    async click(text: string, selector = ".item") {
      await act(async () => find(text, selector).click());
    },
    selected: (text: string) => find(text, ".item").style.borderColor === "var(--accent)",
    async raster() { await act(async () => container.querySelector<HTMLInputElement>("input[type=checkbox]")!.click()); },
    sources: () => Object.keys(maps.current.sources).sort(),
    lastBounds: () => maps.current.fits.at(-1),
    deferMapLoad: () => { maps.current.loaded = false; },
    async loadMap() { await act(async () => maps.current.load()); },
    busyAfterSourceChange: () => { maps.current.busyAfterSourceChange = true; },
    async pickRecord(id: string) {
      await act(async () => search.pick!({ kind: "planning_record", id, title: `Synthetic record ${id}` }));
    },
    async pickCoordinate(lon: number, lat: number) {
      await act(async () => search.pick!({ kind: "coordinate", id: null, title: "Synthetic coordinate", lon, lat }));
    },
    async versionThenCoordinate(title: string, lon: number, lat: number) {
      await act(async () => {
        find(title, ".item").click();
        search.pick!({ kind: "coordinate", id: null, title: "Synthetic coordinate", lon, lat });
      });
    },
    async remount() {
      await act(async () => root.unmount());
      root = createRoot(container);
      await act(async () => root.render(<StrictMode><Page /></StrictMode>));
    },
    async hide() { await act(async () => root.render(null)); },
    async clickMap(lon: number, lat: number) {
      let pending!: Promise<void>;
      await act(async () => { pending = maps.current.click(lon, lat); });
      return { pending };
    },
    boundsCount: () => maps.current.fits.length,
    values: () => [...container.querySelectorAll<HTMLSelectElement>("select")].map(el => el.value),
    async settle<T>(pending: ReturnType<typeof deferred<T>>, value: T) {
      await act(async () => { pending.resolve(value); await pending.promise; });
    },
    async reject<T>(pending: ReturnType<typeof deferred<T>>, error: string) {
      await act(async () => { pending.reject(new Error(error)); await pending.promise.catch(() => {}); });
    },
    async choose(index: number, value: string) {
      await act(async () => {
        const select = container.querySelectorAll<HTMLSelectElement>("select")[index];
        select.value = value; select.dispatchEvent(new Event("change", { bubbles: true }));
      });
    },
  };
}

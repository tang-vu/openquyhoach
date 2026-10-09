import { act, StrictMode, useState } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, vi } from "vitest";
import MapView, { type MapSelection } from "@/components/MapView";
import ProvenanceDrawer from "@/components/ProvenanceDrawer";
import type { FeatureHit } from "@/lib/api";

const mapState = vi.hoisted(() => ({
  current: null as null | {
    click: (lon: number, lat: number) => Promise<void>;
    removed: boolean;
  },
}));

export const maps = mapState;

vi.mock("maplibre-gl", () => ({
  default: {
    Map: class {
      removed = false;
      listeners: Record<
        string,
        (event: { lngLat: { lng: number; lat: number } }) => Promise<void>
      > = {};
      constructor() {
        mapState.current = this;
      }
      on(name: string, listener: (typeof this.listeners)[string]) {
        this.listeners[name] = listener;
      }
      async click(lon: number, lat: number) {
        await this.listeners.click({ lngLat: { lng: lon, lat } });
      }
      addControl() {}
      remove() {
        this.removed = true;
      }
      isStyleLoaded() {
        return true;
      }
      getStyle() {
        return { layers: [], sources: {} };
      }
      getLayer() {
        return undefined;
      }
      getSource() {
        return undefined;
      }
    },
    NavigationControl: class {},
  },
}));

export const syntheticHit: FeatureHit = {
  feature_id: "synthetic-feature",
  layer: "land_use",
  dataset_id: "synthetic-dataset",
  derivation_level: "derived_manual",
  review_status: "approved",
  classification: "synthetic-class",
  properties: { fixture: "synthetic only" },
  distance_m: 0,
  provenance: {
    dataset: { id: "synthetic-dataset", name: "synthetic dataset" },
    layer: { id: "synthetic-layer", name: "land_use" },
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

export function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((yes, no) => {
    resolve = yes;
    reject = no;
  });
  return { promise, resolve, reject };
}

export function json(value: unknown) {
  return new Response(JSON.stringify(value));
}

function Harness({
  visible = true,
  notify,
}: {
  visible?: boolean;
  notify?: (selection: MapSelection) => void;
}) {
  const [selection, setSelection] = useState<MapSelection | null>(null);
  return (
    <>
      {visible && (
        <MapView
          publicationId={null}
          comparePublicationId={null}
          rasterDatasetId={null}
          focusBbox={null}
          onSelect={notify ?? setSelection}
        />
      )}
      <ProvenanceDrawer selection={selection} />
    </>
  );
}

export function setupHarness() {
  let container: HTMLDivElement;
  let root: Root;
  beforeEach(async () => {
    vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);
    // No real fetch implementation is reachable; every response is synthetic.
    vi.stubGlobal(
      "fetch",
      vi.fn(() => Promise.reject(new Error("External requests are blocked"))),
    );
    container = document.createElement("div");
    document.body.append(container);
    root = createRoot(container);
    await act(async () =>
      root.render(
        <StrictMode>
          <Harness />
        </StrictMode>,
      ),
    );
  });
  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
    vi.unstubAllGlobals();
  });
  return {
    text: () => container.textContent,
    element: (selector: string) => container.querySelector(selector),
    render: async (props: {
      visible?: boolean;
      notify?: (selection: MapSelection) => void;
    }) => {
      await act(async () =>
        root.render(
          <StrictMode>
            <Harness {...props} />
          </StrictMode>,
        ),
      );
    },
    click: async (lon = 1, lat = 2) => {
      await act(async () => {
        await maps.current!.click(lon, lat);
      });
    },
    startClick: async (lon = 1, lat = 2) => {
      let pending!: Promise<void>;
      await act(async () => {
        pending = maps.current!.click(lon, lat);
      });
      return { pending };
    },
  };
}

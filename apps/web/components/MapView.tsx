"use client";

import { useEffect, useRef } from "react";
import maplibregl, { Map as MLMap } from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { api, type FeatureHit } from "@/lib/api";

export interface MapSelection {
  lon: number;
  lat: number;
  hits: FeatureHit[];
}

const LAYER_COLORS: Record<string, string> = {
  land_use: "#3fa7ff",
  transport: "#e8b13f",
  boundary: "#c46bd8",
};

/** Vector tiles for one published version; the MVT carries `layer` attr
 * per feature so a single source can expose multiple paint layers. */
function addPublicationSource(map: MLMap, pubId: string, variant: "main" | "cmp") {
  const srcId = `pub-${pubId}`;
  if (map.getSource(srcId)) return;
  map.addSource(srcId, {
    type: "vector",
    tiles: [api.tilesUrl(pubId)],
    minzoom: 0,
    maxzoom: 14,
  });
  const opacity = variant === "cmp" ? 0.2 : 0.35;
  for (const [canonical, color] of Object.entries(LAYER_COLORS)) {
    map.addLayer({
      id: `${srcId}-${canonical}-fill`,
      type: "fill",
      source: srcId,
      "source-layer": "planning",
      filter: ["==", ["get", "layer"], canonical],
      paint: { "fill-color": color, "fill-opacity": opacity },
    });
    map.addLayer({
      id: `${srcId}-${canonical}-line`,
      type: "line",
      source: srcId,
      "source-layer": "planning",
      filter: ["==", ["get", "layer"], canonical],
      paint: {
        "line-color": color,
        "line-width": 1.6,
        ...(variant === "cmp" ? { "line-dasharray": [2, 2] } : {}),
      },
    });
  }
}

/** Remove all pub-* sources and their layers (keeps the map in sync with
 * the selected version). */
function clearPublicationSources(map: MLMap) {
  for (const lyr of [...map.getStyle().layers ?? []]) {
    if (lyr.id.startsWith("pub-")) map.removeLayer(lyr.id);
  }
  for (const [id] of Object.entries(map.getStyle().sources ?? {})) {
    if (id.startsWith("pub-")) map.removeSource(id);
  }
}

const RASTER_SRC = "raster-overlay";
const RASTER_LYR = "raster-overlay-lyr";

function setRasterOverlay(map: MLMap, datasetId: string | null) {
  if (map.getLayer(RASTER_LYR)) map.removeLayer(RASTER_LYR);
  if (map.getSource(RASTER_SRC)) map.removeSource(RASTER_SRC);
  if (!datasetId) return;
  map.addSource(RASTER_SRC, {
    type: "raster",
    tiles: [api.rasterTilesUrl(datasetId)],
    tileSize: 256,
  });
  map.addLayer({
    id: RASTER_LYR,
    type: "raster",
    source: RASTER_SRC,
    paint: { "raster-opacity": 0.7 },
  });
}

export default function MapView({
  publicationId,
  comparePublicationId,
  rasterDatasetId,
  onSelect,
  focusBbox,
}: {
  publicationId: string | null;
  comparePublicationId: string | null;
  rasterDatasetId: string | null;
  onSelect: (sel: MapSelection) => void;
  focusBbox: number[] | null;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const mapRef = useRef<MLMap | null>(null);

  useEffect(() => {
    if (!ref.current || mapRef.current) return;
    const map = new maplibregl.Map({
      container: ref.current,
      style: {
        version: 8,
        sources: {},
        layers: [
          {
            id: "bg",
            type: "background",
            paint: { "background-color": "#0c1015" },
          },
        ],
      },
      center: [105.9, 20.95],
      zoom: 10,
      attributionControl: false,
    });
    map.addControl(new maplibregl.NavigationControl(), "top-right");
    map.on("click", async (e) => {
      const { lng, lat } = e.lngLat;
      try {
        const res = await api.pointQuery(lng, lat);
        onSelect({ lon: lng, lat, hits: res.hits });
      } catch {
        onSelect({ lon: lng, lat, hits: [] });
      }
    });
    mapRef.current = map;
    return () => {
      map.remove();
      mapRef.current = null;
    };
  }, [onSelect]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    const attach = () => {
      clearPublicationSources(map);
      if (publicationId) addPublicationSource(map, publicationId, "main");
      if (comparePublicationId)
        addPublicationSource(map, comparePublicationId, "cmp");
    };
    if (map.isStyleLoaded()) attach();
    else map.once("load", attach);
  }, [publicationId, comparePublicationId]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    const apply = () => setRasterOverlay(map, rasterDatasetId);
    if (map.isStyleLoaded()) apply();
    else map.once("load", apply);
  }, [rasterDatasetId]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !focusBbox) return;
    map.fitBounds(
      [
        [focusBbox[0], focusBbox[1]],
        [focusBbox[2], focusBbox[3]],
      ],
      { padding: 40, duration: 600 },
    );
  }, [focusBbox]);

  return (
    <div className="mapwrap">
      <div ref={ref} />
      <div className="click-hint">
        Click the map to query planned land use at a point — every result
        carries its provenance chain.
      </div>
    </div>
  );
}

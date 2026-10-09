import { deflateSync } from "node:zlib";

// Generated metadata and tile bytes only; these fixtures have no legal meaning.
export const record = (id) => ({
  id, title: `Synthetic record ${id}`, planning_type: "synthetic",
  scale: null, jurisdiction: null, status: "unknown", data_class: "synthetic",
});
export const version = (id) => ({
  id, planning_record_id: id[0], version_kind: "synthetic",
  version_label: `Synthetic version ${id}`, approval_decision_number: `DEMO-${id}`,
  approval_date: null, legal_status: "unknown",
});
export const versions = { A: ["A1", "A2", "A3"], B: ["B1"], E: [] };
export const bounds = {
  A1: [-1, -1, 1, 1], A2: [19, 9, 21, 11],
  A3: [39, 19, 41, 21], B1: [-41, 19, -39, 21],
};
export const publication = (id) => ({
  id: `publication-${id}`, planning_version_id: id, status: "synthetic",
  checksum_sha256: "0".repeat(64), bbox: bounds[id], min_zoom: 0,
  max_zoom: 14, published_at: null,
});
export const publications = Object.values(versions).flat().map(publication);
export const recordDetail = (id) => ({
  ...record(id), versions: versions[id].map(version),
});
export const dataset = (id, type) => ({
  id: `${type}-${id}`, name: `Synthetic ${type} ${id}`, dataset_group: "synthetic",
  dataset_type: type, derivation_level: "derived_manual", review_status: "approved",
  quality_state: "synthetic", published: true,
  layers: type === "vector"
    ? [{ id: `layer-${id}`, canonical_name: "land_use", feature_count: 0 }] : [],
});
export const detail = (id) => ({
  ...version(id), datasets: [dataset(id, "vector"), dataset(id, "raster")],
  documents: [{
    id: `document-${id}`, title: `Synthetic source document ${id}`,
    document_type: "synthetic", document_number: `DEMO-${id}`, signed_date: null,
    issuing_authority: null, metadata_origin: "derived_machine", page_count: null,
    artifact_id: null, planning_version_id: id,
  }],
  publications: [publication(id)],
});
export const comparison = {
  id: "synthetic-comparison", from_layer_id: "layer-A1", to_layer_id: "layer-A2",
  algorithm: "synthetic", summary: { synthetic_changes: 0 }, entries: [],
};

// A valid empty MVT with a named layer, extent 4096 and version 2.
const vectorTile = Buffer.from([
  0x1a, 15, 0x0a, 8, ...Buffer.from("planning"), 0x28, 0x80, 0x20, 0x78, 2,
]);
function chunk(type, data) {
  const bytes = Buffer.concat([Buffer.from(type), data]);
  let crc = 0xffffffff;
  for (const byte of bytes) {
    crc ^= byte;
    for (let bit = 0; bit < 8; bit++)
      crc = (crc >>> 1) ^ (crc & 1 ? 0xedb88320 : 0);
  }
  const length = Buffer.alloc(4), checksum = Buffer.alloc(4);
  length.writeUInt32BE(data.length);
  checksum.writeUInt32BE((crc ^ 0xffffffff) >>> 0);
  return Buffer.concat([length, bytes, checksum]);
}
const pngHeader = Buffer.alloc(13);
pngHeader.writeUInt32BE(256, 0); pngHeader.writeUInt32BE(256, 4);
pngHeader[8] = 8; pngHeader[9] = 6;
const rasterTile = Buffer.concat([
  Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]), chunk("IHDR", pngHeader),
  chunk("IDAT", deflateSync(Buffer.alloc(256 * (1 + 256 * 4)))),
  chunk("IEND", Buffer.alloc(0)),
]);

export function fixtureResponse(url, navigation) {
  const path = url.pathname;
  if (path === "/v1/planning-records")
    return { json: { items: navigation ? Object.keys(versions).map(record) : [] } };
  if (path === "/v1/publications")
    return { json: { items: navigation ? publications : [] } };
  if (!navigation) return null;
  if (path === "/v1/features/query") return { json: { hits: [] } };
  if (path === "/v1/compare") return { json: comparison };
  if (path === "/v1/search") return { json: { results: [{
    kind: "planning_record", id: "B", title: "Search synthetic B",
  }] } };
  let match;
  if ((match = path.match(/^\/v1\/planning-records\/([ABE])$/)))
    return { json: recordDetail(match[1]) };
  if ((match = path.match(/^\/v1\/planning-versions\/([AB]\d)$/)))
    return { json: detail(match[1]) };
  if ((match = path.match(/^\/v1\/versions\/([AB]\d)\/extent$/)))
    return { json: { bbox: bounds[match[1]] } };
  if ((match = path.match(/^\/v1\/datasets\/vector-([AB]\d)$/)))
    return { json: dataset(match[1], "vector") };
  if ((match = path.match(/^\/v1\/publications\/(publication-[AB]\d)\/manifest\.json$/)))
    return { json: { fixture: "synthetic", publication: match[1] } };
  if (/^\/v1\/publications\/publication-[AB]\d\/tiles\/\d+\/\d+\/\d+\.pbf$/.test(path))
    return { contentType: "application/vnd.mapbox-vector-tile", body: vectorTile };
  if (/^\/v1\/rasters\/raster-[AB]\d\/tiles\/\d+\/\d+\/\d+\.png$/.test(path))
    return { contentType: "image/png", body: rasterTile };
  return null;
}

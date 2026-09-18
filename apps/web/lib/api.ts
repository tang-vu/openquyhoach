/** Typed client for the OpenQuyHoach API. Server-side fetch uses
 * OQH_API_INTERNAL_URL (docker) when set; the browser uses the public URL. */

export const API =
  process.env.NEXT_PUBLIC_OQH_API_URL ?? "http://localhost:8000";

export interface SearchHit {
  kind: "planning_record" | "admin_unit" | "document" | "coordinate";
  id: string | null;
  title: string;
  subtitle?: string | null;
  lon?: number | null;
  lat?: number | null;
  meta?: Record<string, unknown>;
}

export interface FeatureHit {
  feature_id: string;
  layer: string;
  dataset_id: string;
  derivation_level: string;
  review_status: string;
  classification: string | null;
  properties: Record<string, unknown>;
  distance_m: number;
  provenance: {
    dataset?: { id: string; name: string | null } | null;
    layer?: { id: string; name: string } | null;
    derivation_level?: string | null;
    review_status?: string | null;
    planning_version?: {
      id: string;
      label: string | null;
      approval_decision_number: string | null;
      approval_date: string | null;
      legal_status: string;
    } | null;
    artifact?: {
      id: string;
      sha256: string;
      filename: string | null;
      retrieved_at: string | null;
      canonical_url: string | null;
    } | null;
    source?: { key: string; name: string; base_url: string | null } | null;
  };
}

export interface PlanningRecord {
  id: string;
  title: string;
  planning_type: string | null;
  scale: string | null;
  jurisdiction: string | null;
  status: string;
}

export interface PlanningVersion {
  id: string;
  planning_record_id: string;
  version_kind: string;
  version_label: string | null;
  approval_decision_number: string | null;
  approval_date: string | null;
  legal_status: string;
}

export interface DatasetInfo {
  id: string;
  name: string | null;
  dataset_group: string;
  dataset_type: string;
  derivation_level: string;
  review_status: string;
  quality_state: string;
  published: boolean;
  layers?: { id: string; canonical_name: string; feature_count: number }[];
}

export interface Publication {
  id: string;
  planning_version_id: string;
  status: string;
  checksum_sha256: string | null;
  bbox: number[] | null;
  min_zoom: number | null;
  max_zoom: number | null;
  published_at: string | null;
}

export interface ChangesetEntry {
  change_type: string;
  match_key: string | null;
  delta_area_m2: number | null;
  detail: Record<string, unknown>;
}

export interface Changeset {
  id: string;
  from_layer_id: string;
  to_layer_id: string;
  algorithm: string;
  summary: Record<string, number>;
  entries: ChangesetEntry[];
}

export interface DocumentInfo {
  id: string;
  document_type: string | null;
  document_number: string | null;
  title: string | null;
  signed_date: string | null;
  issuing_authority: string | null;
  page_count: number | null;
  artifact_id: string | null;
  planning_version_id: string;
  candidate_codes?: unknown;
}

export interface ReviewTask {
  id: string;
  target_type: string;
  target_id: string;
  task_type: string;
  priority: number;
  status: string;
  reason?: string | null;
  evidence?: Record<string, unknown> | null;
  created_at?: string | null;
}

async function get<T>(path: string, params?: Record<string, string>): Promise<T> {
  const url = new URL(path, API + "/");
  if (params) for (const [k, v] of Object.entries(params)) url.searchParams.set(k, v);
  const r = await fetch(url.toString(), { cache: "no-store" });
  if (!r.ok) throw new Error(`${r.status} ${await r.text()}`);
  return (await r.json()) as T;
}

async function post<T>(path: string, body: unknown, adminKey?: string): Promise<T> {
  const r = await fetch(new URL(path, API + "/").toString(), {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...(adminKey ? { "X-Admin-Key": adminKey } : {}),
    },
    body: JSON.stringify(body),
  });
  if (!r.ok) throw new Error(`${r.status} ${await r.text()}`);
  return (await r.json()) as T;
}

export const api = {
  search: (q: string) =>
    get<{ results: SearchHit[] }>("/v1/search", { q }),
  pointQuery: (lon: number, lat: number, bufferM = 60) =>
    get<{ hits: FeatureHit[] }>("/v1/features/query", {
      lon: String(lon),
      lat: String(lat),
      buffer_m: String(bufferM),
    }),
  records: () => get<{ items: PlanningRecord[] }>("/v1/planning-records"),
  version: (id: string) => get<PlanningVersion>(`/v1/planning-versions/${id}`),
  versionExtent: (id: string) =>
    get<{ bbox: number[] }>(`/v1/versions/${id}/extent`),
  publications: () => get<{ items: Publication[] }>("/v1/publications"),
  manifest: (pubId: string) =>
    get<Record<string, unknown>>(`/v1/publications/${pubId}/manifest.json`),
  compare: (fromLayer: string, toLayer: string) =>
    get<Changeset>("/v1/compare", { from_layer: fromLayer, to_layer: toLayer }),
  dataset: (id: string) => get<DatasetInfo>(`/v1/datasets/${id}`),
  documents: (versionId?: string) =>
    get<{ items: DocumentInfo[] }>(
      "/v1/documents",
      versionId ? { version_id: versionId } : undefined,
    ),
  documentDownloadUrl: (docId: string) =>
    `${API}/v1/documents/${docId}/download`,
  versionDetail: (versionId: string) =>
    get<
      PlanningVersion & {
        datasets: DatasetInfo[];
        documents: DocumentInfo[];
        publications: {
          id: string;
          status: string;
          published_at: string | null;
          checksum_sha256: string | null;
        }[];
      }
    >(`/v1/planning-versions/${versionId}`),
  recordDetail: (recordId: string) =>
    get<PlanningRecord & { versions: PlanningVersion[] }>(
      `/v1/planning-records/${recordId}`,
    ),
  reviewTasks: (status = "pending") =>
    get<{ items: ReviewTask[] }>("/v1/review/tasks", { status }),
  resolveTask: (
    taskId: string,
    approve: boolean,
    adminKey: string,
    reviewer: string,
    resolution: string,
  ) =>
    post(`/v1/review/tasks/${taskId}/resolve`,
      { approve, reviewer, resolution }, adminKey),
  publish: (versionId: string, adminKey: string, maxZoom = 14) =>
    post<{ publication_id: string }>("/v1/publish",
      { planning_version_id: versionId, max_zoom: maxZoom }, adminKey),
  tilesUrl: (pubId: string) =>
    `${API}/v1/publications/${pubId}/tiles/{z}/{x}/{y}.pbf`,
  rasterTilesUrl: (datasetId: string) =>
    `${API}/v1/rasters/${datasetId}/tiles/{z}/{x}/{y}.png`,
};

"use client";

import { useEffect, useState } from "react";
import { api, type DatasetInfo, type DocumentInfo } from "@/lib/api";

type Detail = Awaited<ReturnType<typeof api.versionDetail>>;

export default function VersionDetail({
  versionId,
  onRasterToggle,
  rasterOn,
}: {
  versionId: string;
  rasterOn: string | null;
  onRasterToggle: (datasetId: string | null) => void;
}) {
  const [d, setD] = useState<Detail | null>(null);
  const [manifest, setManifest] = useState<Record<string, unknown> | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    setD(null);
    setManifest(null);
    api
      .versionDetail(versionId)
      .then(setD)
      .catch((e) => setErr(String(e)));
  }, [versionId]);

  if (err) return <div className="error">{err}</div>;
  if (!d) return <div className="muted">loading…</div>;

  const rasters = d.datasets.filter(
    (x) => x.dataset_type === "raster" && x.published,
  );
  const datasets = d.datasets.filter((x) => x.dataset_type !== "raster");

  return (
    <div>
      <h2>Datasets</h2>
      {datasets.map((x) => (
        <DatasetRow key={x.id} d={x} />
      ))}
      {rasters.map((x) => (
        <div className="item" key={x.id} style={{ cursor: "default" }}>
          <div className="title">
            {x.name ?? "raster"}{" "}
            <span className="badge derived">{x.derivation_level}</span>
          </div>
          <div className="sub">
            raster · {x.review_status} · {x.published ? "published" : "unpublished"}
          </div>
          <label style={{ display: "block", marginTop: 6, fontSize: 12 }}>
            <input
              type="checkbox"
              checked={rasterOn === x.id}
              onChange={(e) => onRasterToggle(e.target.checked ? x.id : null)}
            />{" "}
            show scanned map overlay
          </label>
        </div>
      ))}

      {d.documents.length > 0 && (
        <>
          <h2>Official documents</h2>
          {d.documents.map((doc) => (
            <DocRow key={doc.id} doc={doc} />
          ))}
        </>
      )}

      {d.publications.length > 0 && (
        <>
          <h2>Publications</h2>
          {d.publications.map((p) => (
            <div className="item" key={p.id} style={{ cursor: "default" }}>
              <div className="title mono" style={{ fontSize: 11 }}>
                {p.id.slice(0, 8)}… <span className="badge official">{p.status}</span>
              </div>
              <div className="sub">
                {p.published_at?.slice(0, 10) ?? "—"} · sha{" "}
                {p.checksum_sha256?.slice(0, 12)}…
              </div>
              <button
                style={{ marginTop: 6, fontSize: 12 }}
                onClick={async () => {
                  setManifest(null);
                  try {
                    setManifest(await api.manifest(p.id));
                  } catch (e) {
                    setErr(String(e));
                  }
                }}
              >
                view manifest
              </button>
            </div>
          ))}
          {manifest && (
            <details open style={{ marginTop: 8 }}>
              <summary className="muted" style={{ cursor: "pointer" }}>
                manifest.json
              </summary>
              <pre className="mono" style={{ whiteSpace: "pre-wrap", maxHeight: 320, overflow: "auto" }}>
                {JSON.stringify(manifest, null, 1)}
              </pre>
            </details>
          )}
        </>
      )}
    </div>
  );
}

function DatasetRow({ d }: { d: DatasetInfo }) {
  const cls = d.derivation_level.startsWith("official")
    ? "official"
    : d.review_status === "approved"
      ? "derived"
      : "unreviewed";
  return (
    <div className="item" style={{ cursor: "default" }}>
      <div className="title">
        {d.name ?? d.dataset_type}{" "}
        <span className={`badge ${cls}`}>{d.derivation_level}</span>
      </div>
      <div className="sub">
        {d.dataset_type} · {d.review_status} ·{" "}
        {d.published ? "published" : "unpublished"} · q:{d.quality_state}
      </div>
    </div>
  );
}

function DocRow({ doc }: { doc: DocumentInfo }) {
  return (
    <div className="item" style={{ cursor: "default" }}>
      <div className="title">{doc.title ?? doc.document_number ?? "document"}</div>
      <div className="sub">
        {doc.document_type ?? "—"} · {doc.document_number ?? "—"} ·{" "}
        {doc.signed_date ?? "—"} · {doc.page_count ?? "?"}p
      </div>
      <div className="sub muted">{doc.issuing_authority ?? ""}</div>
      {doc.artifact_id && (
        <a
          className="mono"
          style={{ fontSize: 12, color: "var(--accent)" }}
          href={api.documentDownloadUrl(doc.id)}
          target="_blank"
          rel="noreferrer"
        >
          download source artifact ↓
        </a>
      )}
    </div>
  );
}

"use client";

import type { FeatureHit } from "@/lib/api";
import type { MapSelection } from "./MapView";

function LevelBadge({ level, review }: { level: string; review: string }) {
  const cls =
    level.startsWith("official")
      ? "official"
      : review === "approved"
        ? "derived"
        : "unreviewed";
  return (
    <>
      <span className={`badge ${cls}`}>{level}</span>{" "}
      <span className="badge">{review}</span>
    </>
  );
}

function FeatureCard({ hit }: { hit: FeatureHit }) {
  const p = hit.provenance;
  return (
    <div className="item" style={{ cursor: "default" }}>
      <div className="title">
        {hit.layer} · {hit.classification ?? "—"}
      </div>
      <div className="sub" style={{ marginBottom: 6 }}>
        <LevelBadge level={hit.derivation_level} review={hit.review_status} />{" "}
        <span className="muted">{hit.distance_m} m away</span>
      </div>
      <dl className="kv">
        <dt>decision</dt>
        <dd>{p.planning_version?.approval_decision_number ?? "—"}</dd>
        <dt>version</dt>
        <dd>{p.planning_version?.label ?? "—"}</dd>
        <dt>legal status</dt>
        <dd>{p.planning_version?.legal_status ?? "—"}</dd>
        <dt>source file</dt>
        <dd>{p.artifact?.filename ?? "—"}</dd>
        <dt>sha256</dt>
        <dd className="mono">{p.artifact?.sha256?.slice(0, 24)}…</dd>
        <dt>source</dt>
        <dd>{p.source?.key ?? "—"}</dd>
      </dl>
      {Object.keys(hit.properties).length > 0 && (
        <details>
          <summary className="muted" style={{ cursor: "pointer" }}>
            properties
          </summary>
          <pre className="mono" style={{ whiteSpace: "pre-wrap" }}>
            {JSON.stringify(hit.properties, null, 1)}
          </pre>
        </details>
      )}
    </div>
  );
}

export default function ProvenanceDrawer({
  selection,
}: {
  selection: MapSelection | null;
}) {
  if (!selection)
    return <div className="muted">Click the map to inspect a point.</div>;
  return (
    <div>
      <div className="mono muted" style={{ marginBottom: 8 }}>
        {selection.lat.toFixed(5)}, {selection.lon.toFixed(5)} —{" "}
        {selection.hits.length} feature(s)
      </div>
      {selection.hits.length === 0 && (
        <div className="notice">
          No published planning geometry at this point. That is a coverage
          statement, not a legal one — check with the responsible authority.
        </div>
      )}
      {selection.hits.map((h) => (
        <FeatureCard key={h.feature_id} hit={h} />
      ))}
    </div>
  );
}

"use client";

import { useCallback, useEffect, useState } from "react";
import MapView, { type MapSelection } from "@/components/MapView";
import SearchBox from "@/components/SearchBox";
import ProvenanceDrawer from "@/components/ProvenanceDrawer";
import ComparePanel from "@/components/ComparePanel";
import AdminPanel from "@/components/AdminPanel";
import SourcesPanel from "@/components/SourcesPanel";
import VersionDetail from "@/components/VersionDetail";
import { DataClassBadge } from "@/components/badges";
import { usePlanningSelection } from "@/lib/use-planning-selection";
import {
  api,
  type PlanningRecord,
  type Publication,
  type SearchHit,
} from "@/lib/api";

type Tab = "records" | "sources" | "compare" | "admin";

export default function Page() {
  const [tab, setTab] = useState<Tab>("records");
  const [records, setRecords] = useState<PlanningRecord[]>([]);
  const [pubs, setPubs] = useState<Publication[]>([]);
  const selection = usePlanningSelection(pubs);
  const { recordId, versionId, versions, selectRecord, selectVersion, focusBbox } = selection;
  const [sel, setSel] = useState<MapSelection | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    api
      .records()
      .then((r) => setRecords(r.items))
      .catch((e) => setErr(String(e)));
    api
      .publications()
      .then((r) => setPubs(r.items))
      .catch(() => {});
  }, []);

  const onSearchPick = useCallback(
    (hit: SearchHit) => {
      if (hit.kind === "planning_record" && hit.id) selectRecord(hit.id);
      if (hit.lon != null && hit.lat != null)
        focusBbox([hit.lon - 0.02, hit.lat - 0.02, hit.lon + 0.02, hit.lat + 0.02]);
    },
    [selectRecord, focusBbox],
  );

  return (
    <div className="shell">
      <aside className="sidebar">
        <h1>OpenQuyHoach</h1>
        <div className="muted" style={{ fontSize: 12, marginBottom: 10 }}>
          provenance-first Vietnamese planning evidence
        </div>
        <SearchBox onPick={onSearchPick} />
        <div className="tabs" style={{ marginTop: 14 }}>
          {(["records", "sources", "compare", "admin"] as Tab[]).map((t) => (
            <button
              key={t}
              className={tab === t ? "active" : ""}
              onClick={() => setTab(t)}
            >
              {t}
            </button>
          ))}
        </div>

        {tab === "records" && (
          <div>
            {records.map((r) => (
              <div
                className="item"
                key={r.id}
                onClick={() => selectRecord(r.id)}
                style={
                  r.id === recordId ? { borderColor: "var(--accent)" } : {}
                }
              >
                <div className="title">
                  {r.title} <DataClassBadge dataClass={r.data_class} />
                </div>
                <div className="sub">
                  {r.planning_type ?? ""} · {r.scale ?? ""} ·{" "}
                  {r.jurisdiction ?? ""}
                </div>
              </div>
            ))}
            {selection.loading && <div className="muted" role="status">Loading versions…</div>}
            {recordId && !selection.loading && !selection.error && versions.length === 0 && (
              <div className="muted">No versions available for this record.</div>
            )}
            {versions.length > 0 && (
              <>
                <h2>Versions</h2>
                {versions.map((v) => (
                  <div
                    className="item"
                    key={v.id}
                    onClick={() => selectVersion(v.id)}
                    style={
                      v.id === versionId ? { borderColor: "var(--accent)" } : {}
                    }
                  >
                    <div className="title">
                      {v.version_label ?? "—"}{" "}
                      <span className="badge">{v.version_kind}</span>
                    </div>
                    <div className="sub">
                      {v.approval_decision_number ?? ""} ·{" "}
                      {v.legal_status}
                    </div>
                  </div>
                ))}
                {versionId && (
                  <VersionDetail
                    key={selection.versionKey}
                    versionId={versionId}
                    rasterOn={selection.rasterId}
                    onRasterToggle={selection.onRasterToggle}
                  />
                )}
              </>
            )}
          </div>
        )}

        {tab === "sources" && <SourcesPanel />}
        {tab === "compare" && (
          <ComparePanel key={selection.recordKey} versions={versions} onCompare={selection.onCompare} />
        )}
        {tab === "admin" && <AdminPanel />}
        {err && <div className="error" style={{ marginTop: 8 }}>{err}</div>}
        {selection.error && <div className="error" role="alert" style={{ marginTop: 8 }}>{selection.error}</div>}
      </aside>

      <MapView
        publicationId={selection.pubId}
        comparePublicationId={selection.comparePubId}
        rasterDatasetId={selection.rasterId}
        onSelect={setSel}
        focusBbox={selection.bbox}
      />

      <aside className="rightbar">
        <h2>Point query</h2>
        <ProvenanceDrawer selection={sel} />
      </aside>
    </div>
  );
}

"use client";

import { useCallback, useEffect, useState } from "react";
import MapView, { type MapSelection } from "@/components/MapView";
import SearchBox from "@/components/SearchBox";
import ProvenanceDrawer from "@/components/ProvenanceDrawer";
import ComparePanel from "@/components/ComparePanel";
import AdminPanel from "@/components/AdminPanel";
import VersionDetail from "@/components/VersionDetail";
import {
  api,
  type PlanningRecord,
  type PlanningVersion,
  type Publication,
  type SearchHit,
} from "@/lib/api";

type Tab = "records" | "compare" | "admin";

export default function Page() {
  const [tab, setTab] = useState<Tab>("records");
  const [records, setRecords] = useState<PlanningRecord[]>([]);
  const [versions, setVersions] = useState<PlanningVersion[]>([]);
  const [pubs, setPubs] = useState<Publication[]>([]);
  const [recordId, setRecordId] = useState<string | null>(null);
  const [versionId, setVersionId] = useState<string | null>(null);
  const [pubId, setPubId] = useState<string | null>(null);
  const [comparePubId, setComparePubId] = useState<string | null>(null);
  const [rasterId, setRasterId] = useState<string | null>(null);
  const [bbox, setBbox] = useState<number[] | null>(null);
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

  useEffect(() => {
    if (!recordId) return;
    api
      .recordDetail(recordId)
      .then((r) => {
        setVersions(r.versions);
        const first = r.versions[0]?.id;
        if (first) setVersionId(first);
      })
      .catch((e) => setErr(String(e)));
  }, [recordId]);

  // map selected version → its publication; fetch extent for framing
  useEffect(() => {
    if (!versionId) return;
    const pub = pubs.find((p) => p.planning_version_id === versionId);
    setPubId(pub?.id ?? null);
    setRasterId(null);
    api
      .versionExtent(versionId)
      .then((e) => setBbox(e.bbox))
      .catch(() => setBbox(null));
  }, [versionId, pubs]);

  const onSearchPick = useCallback(
    (hit: SearchHit) => {
      if (hit.kind === "planning_record" && hit.id) setRecordId(hit.id);
      if (hit.lon != null && hit.lat != null)
        setBbox([hit.lon - 0.02, hit.lat - 0.02, hit.lon + 0.02, hit.lat + 0.02]);
    },
    [],
  );

  return (
    <div className="shell">
      <aside className="sidebar">
        <h1>OpenQuyHoach</h1>
        <div className="muted" style={{ fontSize: 12, marginBottom: 10 }}>
          provenance-first planning data — demo fixture
        </div>
        <SearchBox onPick={onSearchPick} />
        <div className="tabs" style={{ marginTop: 14 }}>
          {(["records", "compare", "admin"] as Tab[]).map((t) => (
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
                onClick={() => setRecordId(r.id)}
                style={
                  r.id === recordId ? { borderColor: "var(--accent)" } : {}
                }
              >
                <div className="title">{r.title}</div>
                <div className="sub">
                  {r.planning_type ?? ""} · {r.scale ?? ""} ·{" "}
                  {r.jurisdiction ?? ""}
                </div>
              </div>
            ))}
            {versions.length > 0 && (
              <>
                <h2>Versions</h2>
                {versions.map((v) => (
                  <div
                    className="item"
                    key={v.id}
                    onClick={() => setVersionId(v.id)}
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
                    versionId={versionId}
                    rasterOn={rasterId}
                    onRasterToggle={setRasterId}
                  />
                )}
              </>
            )}
          </div>
        )}

        {tab === "compare" && (
          <ComparePanel versions={versions} onCompare={setComparePubId} />
        )}
        {tab === "admin" && <AdminPanel />}
        {err && <div className="error" style={{ marginTop: 8 }}>{err}</div>}
      </aside>

      <MapView
        publicationId={pubId}
        comparePublicationId={comparePubId}
        rasterDatasetId={rasterId}
        onSelect={setSel}
        focusBbox={bbox}
      />

      <aside className="rightbar">
        <h2>Point query</h2>
        <ProvenanceDrawer selection={sel} />
      </aside>
    </div>
  );
}

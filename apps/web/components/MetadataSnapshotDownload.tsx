"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "@/lib/api";
import { prepareMetadataSnapshot, type MetadataSnapshot } from "@/lib/metadata-snapshot";
import { downloadMetadataSnapshot } from "@/lib/download-metadata-snapshot";
import type { RecordDetail, VersionMetadata } from "@/lib/metadata-snapshot-validation";

type Owner = { record: RecordDetail; version: VersionMetadata };
const empty = { pending: false, snapshot: null as MetadataSnapshot | null, error: null as string | null, downloaded: false };

export default function MetadataSnapshotDownload({ record, version }: {
  record: RecordDetail; version: VersionMetadata;
}) {
  const owner = useMemo(() => ({ record, version }), [record, version]);
  const latest = useRef(owner);
  latest.current = owner;
  const generation = useRef(0);
  const busy = useRef(false);
  const consumed = useRef(false);
  const [state, setState] = useState<typeof empty & { owner: Owner }>({ ...empty, owner });
  // A replacement render cannot show or download state belonging to old inputs,
  // even before effect cleanup. Repeated IDs do not reuse an earlier owner.
  const { pending, snapshot, error, downloaded } = state.owner === owner ? state : empty;

  useEffect(() => {
    ++generation.current;
    busy.current = false;
    consumed.current = false;
    setState({ ...empty, owner });
    return () => { ++generation.current; busy.current = false; consumed.current = true; };
  }, [owner]);

  async function prepare() {
    if (busy.current || latest.current !== owner) return;
    const request = ++generation.current;
    const current = () => generation.current === request && latest.current === owner;
    busy.current = true; consumed.current = false;
    setState({ ...empty, owner, pending: true });
    try {
      const value = await prepareMetadataSnapshot(record.id, version.id, record, version, api.manifest);
      if (current()) setState({ ...empty, owner, snapshot: value });
    } catch (cause) {
      if (current()) setState({ ...empty, owner, error: cause instanceof Error ? cause.message : String(cause) });
    } finally {
      if (current()) busy.current = false;
    }
  }

  function download() {
    if (!snapshot || latest.current !== owner || state.owner !== owner || busy.current || consumed.current) return;
    consumed.current = true;
    try {
      downloadMetadataSnapshot(snapshot);
      setState({ ...state, downloaded: true, error: null });
    } catch {
      consumed.current = false;
      setState({ ...state, error: "The browser could not create the download. Try again." });
    }
  }

  const incomplete = snapshot?.availability.publication_manifests !== "available";
  return <section aria-label="Metadata snapshot" style={{ marginTop: 14 }}>
    <h2>Metadata snapshot</h2>
    <p className="muted" style={{ fontSize: 12 }}>
      Save metadata captured from API responses for this record and version.
      This is not a verified or complete provenance graph and does not certify legal validity.
    </p>
    <button onClick={prepare} disabled={pending}>Prepare metadata snapshot (JSON)</button>
    {pending && <>
      <p role="status">Preparing metadata snapshot…</p>
      <button onClick={() => {
        ++generation.current; busy.current = false;
        setState({ ...empty, owner });
      }}>Cancel preparation</button>
    </>}
    {error && <p className="error" role="alert">{error}</p>}
    {snapshot && <div>
      <p role="status">{incomplete ? "Incomplete metadata snapshot" : "Metadata snapshot ready"}</p>
      <p className="muted" style={{ fontSize: 12 }}>
        {snapshot.version.datasets.length} datasets · {snapshot.version.documents.length} documents ·{" "}
        {snapshot.manifests.filter(item => item.status === "available").length}/{snapshot.manifests.length} manifests available
      </p>
      {snapshot.availability.publication_manifests === "none" &&
        <p>No publication manifests are available for this version.</p>}
      {snapshot.manifests.filter(item => item.status === "unavailable").map(item =>
        <p className="error" key={item.publication_id}>Manifest {item.publication_id}: {item.error}</p>)}
      {incomplete && <p>The file will explicitly include unavailable provenance and manifest errors.</p>}
      <button onClick={download} disabled={downloaded}>
        {incomplete ? "Download incomplete snapshot" : "Download snapshot"}
      </button>
      {downloaded && <p role="status">Download started.</p>}
    </div>}
  </section>;
}

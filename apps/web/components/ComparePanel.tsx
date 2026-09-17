"use client";

import { useEffect, useState } from "react";
import { api, type Changeset, type PlanningVersion } from "@/lib/api";

/** Find the land_use layer id belonging to a planning version by walking
 * version → datasets → layers. */
async function landUseLayerId(versionId: string): Promise<string | null> {
  const v = await api.versionDetail(versionId);
  for (const d of v.datasets) {
    if (d.dataset_type !== "vector") continue;
    const det = await api.dataset(d.id);
    const lyr = (det.layers ?? []).find((x) => x.canonical_name === "land_use");
    if (lyr) return lyr.id;
  }
  return null;
}

export default function ComparePanel({
  versions,
  onCompare,
}: {
  versions: PlanningVersion[];
  onCompare: (toPublicationId: string | null) => void;
}) {
  const [fromV, setFromV] = useState("");
  const [toV, setToV] = useState("");
  const [cs, setCs] = useState<Changeset | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    setCs(null);
  }, [fromV, toV]);

  async function run() {
    setBusy(true);
    setErr(null);
    try {
      const [l1, l2] = await Promise.all([
        landUseLayerId(fromV),
        landUseLayerId(toV),
      ]);
      if (!l1 || !l2) throw new Error("no land_use layer in a selected version");
      setCs(await api.compare(l1, l2));
      // overlay the "to" version's tiles on the map
      const pubs = await api.publications();
      onCompare(
        pubs.items.find((p) => p.planning_version_id === toV)?.id ?? null,
      );
    } catch (e) {
      setErr(String(e));
    } finally {
      setBusy(false);
    }
  }

  const s = cs?.summary ?? {};
  return (
    <div>
      <select value={fromV} onChange={(e) => setFromV(e.target.value)}>
        <option value="">from version…</option>
        {versions.map((v) => (
          <option key={v.id} value={v.id}>
            {v.version_label ?? v.id.slice(0, 8)} ({v.approval_decision_number ?? "—"})
          </option>
        ))}
      </select>
      <select
        value={toV}
        onChange={(e) => setToV(e.target.value)}
        style={{ marginTop: 6 }}
      >
        <option value="">to version…</option>
        {versions.map((v) => (
          <option key={v.id} value={v.id}>
            {v.version_label ?? v.id.slice(0, 8)} ({v.approval_decision_number ?? "—"})
          </option>
        ))}
      </select>
      <button
        className="primary"
        style={{ marginTop: 8, width: "100%" }}
        disabled={!fromV || !toV || fromV === toV || busy}
        onClick={run}
      >
        {busy ? "comparing…" : "Compare"}
      </button>
      {err && <div className="error">{err}</div>}
      {cs && (
        <div style={{ marginTop: 10 }}>
          <table className="diff">
            <tbody>
              {Object.entries(s).map(([k, v]) => (
                <tr key={k}>
                  <td className="muted">{k}</td>
                  <td>{typeof v === "number" && k.endsWith("_m2")
                    ? `${(v / 10000).toFixed(2)} ha`
                    : v}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="muted" style={{ marginTop: 8, fontSize: 12 }}>
            Geometric difference is not a legal interpretation. Verify the
            effective dates and decision documents.
          </div>
          <details style={{ marginTop: 6 }}>
            <summary className="muted" style={{ cursor: "pointer" }}>
              entries ({cs.entries.length})
            </summary>
            <table className="diff">
              <thead>
                <tr><th>type</th><th>key</th><th>Δ m²</th></tr>
              </thead>
              <tbody>
                {cs.entries.map((e, i) => (
                  <tr key={i}>
                    <td>{e.change_type}</td>
                    <td className="mono">{e.match_key ?? "—"}</td>
                    <td>{e.delta_area_m2?.toFixed(0) ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </details>
        </div>
      )}
    </div>
  );
}

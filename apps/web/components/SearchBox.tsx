"use client";

import { useState } from "react";
import { api, type SearchHit } from "@/lib/api";

export default function SearchBox({
  onPick,
}: {
  onPick: (hit: SearchHit) => void;
}) {
  const [q, setQ] = useState("");
  const [results, setResults] = useState<SearchHit[]>([]);
  const [err, setErr] = useState<string | null>(null);

  async function run() {
    setErr(null);
    try {
      const r = await api.search(q);
      setResults(r.results);
    } catch (e) {
      setErr(String(e));
    }
  }

  return (
    <div>
      <div style={{ display: "flex", gap: 6 }}>
        <input
          type="text"
          placeholder="Search records, units, '105.9, 20.9'…"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && run()}
        />
        <button className="primary" onClick={run} disabled={!q.trim()}>
          Go
        </button>
      </div>
      {err && <div className="error">{err}</div>}
      <div style={{ marginTop: 8 }}>
        {results.map((r, i) => (
          <div className="item" key={r.id ?? i} onClick={() => onPick(r)}>
            <div className="title">{r.title}</div>
            <div className="sub">
              <span className="badge">{r.kind}</span>{" "}
              {r.subtitle ?? ""}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

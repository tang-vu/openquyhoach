"use client";

import { useEffect, useState } from "react";
import { api, type ChangeEventInfo, type SourceInfo } from "@/lib/api";
import { ago, DataClassBadge, HealthBadge } from "@/components/badges";

function SourceRow({ s }: { s: SourceInfo }) {
  const c = s.crawl;
  return (
    <div className="item" style={{ cursor: "default" }}>
      <div className="title">
        {s.name} <DataClassBadge dataClass={s.data_class} />
      </div>
      <div className="sub mono" style={{ fontSize: 11 }}>
        {s.key} · {s.source_type}
        {s.enabled ? "" : " · disabled"}
      </div>
      {s.base_url && (
        <div className="sub">
          <a
            className="mono"
            style={{ fontSize: 11, color: "var(--accent)", wordBreak: "break-all" }}
            href={s.base_url}
            target="_blank"
            rel="noreferrer"
          >
            {s.base_url}
          </a>
        </div>
      )}
      <div className="sub" style={{ marginTop: 4 }}>
        <HealthBadge health={c?.health} />{" "}
        <span className="badge">{c?.freshness ?? "never_checked"}</span>{" "}
        {c?.locked && <span className="badge">locked</span>}
      </div>
      <dl className="kv" style={{ marginTop: 6 }}>
        <dt>last check</dt>
        <dd>{ago(c?.last_check_at)}</dd>
        <dt>last success</dt>
        <dd>{ago(c?.last_success_at)}</dd>
        <dt>last change</dt>
        <dd>{ago(c?.last_change_at)}</dd>
        <dt>next check</dt>
        <dd>
          {c?.next_check_at
            ? new Date(c.next_check_at).toLocaleString()
            : "unscheduled"}
          {c?.due ? " (due)" : ""}
        </dd>
        <dt>resources</dt>
        <dd>
          {c?.resources_seen ?? 0} observed
          {c?.consecutive_failures
            ? ` · ${c.consecutive_failures} consecutive failure(s)`
            : ""}
        </dd>
        {c?.last_http_status != null && (
          <>
            <dt>last http</dt>
            <dd>{c.last_http_status}</dd>
          </>
        )}
      </dl>
      {c?.last_error && (
        <div className="error" style={{ marginTop: 4 }}>
          {c.last_error}
        </div>
      )}
    </div>
  );
}

function ChangeRow({ e }: { e: ChangeEventInfo }) {
  const url = (e.detail?.url ?? e.detail?.to ?? "") as string;
  return (
    <div className="item" style={{ cursor: "default" }}>
      <div className="title">
        <span className="badge">{e.change_type}</span>{" "}
        <span className="muted" style={{ fontSize: 12 }}>{e.source}</span>
      </div>
      <div className="sub">{ago(e.detected_at)}</div>
      {url && (
        <div className="mono muted" style={{ fontSize: 11, wordBreak: "break-all" }}>
          {url}
        </div>
      )}
    </div>
  );
}

export default function SourcesPanel() {
  const [sources, setSources] = useState<SourceInfo[]>([]);
  const [changes, setChanges] = useState<ChangeEventInfo[]>([]);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    api
      .sources()
      .then((r) => setSources(r.items))
      .catch((e) => setErr(String(e)));
    api
      .changes(30)
      .then((r) => setChanges(r.items))
      .catch(() => {});
  }, []);

  const real = sources.filter((s) => s.data_class !== "synthetic");
  const demo = sources.filter((s) => s.data_class === "synthetic");

  return (
    <div>
      {err && <div className="error">{err}</div>}

      <h2>Official sources ({real.length})</h2>
      {real.length === 0 && (
        <div className="muted">No official sources registered yet.</div>
      )}
      {real.map((s) => (
        <SourceRow key={s.id} s={s} />
      ))}

      <h2>Demo fixtures ({demo.length})</h2>
      {demo.map((s) => (
        <SourceRow key={s.id} s={s} />
      ))}

      <h2>Recent upstream changes</h2>
      {changes.length === 0 && (
        <div className="muted">No change events recorded yet.</div>
      )}
      {changes.map((e) => (
        <ChangeRow key={e.id} e={e} />
      ))}
    </div>
  );
}

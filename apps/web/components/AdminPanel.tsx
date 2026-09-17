"use client";

import { useCallback, useEffect, useState } from "react";
import { api, type ReviewTask } from "@/lib/api";

export default function AdminPanel() {
  const [key, setKey] = useState("");
  const [reviewer, setReviewer] = useState("");
  const [tasks, setTasks] = useState<ReviewTask[]>([]);
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    setKey(localStorage.getItem("oqh_admin") ?? "");
    setReviewer(localStorage.getItem("oqh_reviewer") ?? "");
  }, []);

  const load = useCallback(async () => {
    try {
      setTasks((await api.reviewTasks()).items);
    } catch (e) {
      setErr(String(e));
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  async function resolve(t: ReviewTask, approve: boolean) {
    setErr(null);
    setMsg(null);
    localStorage.setItem("oqh_admin", key);
    localStorage.setItem("oqh_reviewer", reviewer);
    try {
      await api.resolveTask(
        t.id, approve, key, reviewer,
        approve ? "verified against source artifact" : "rejected — see notes",
      );
      setMsg(`${approve ? "Approved" : "Dismissed"} ${t.id.slice(0, 8)}`);
      await load();
    } catch (e) {
      setErr(String(e));
    }
  }

  return (
    <div>
      <input
        type="password"
        placeholder="admin key (dev token)"
        value={key}
        onChange={(e) => setKey(e.target.value)}
      />
      <input
        type="text"
        placeholder="reviewer name"
        value={reviewer}
        onChange={(e) => setReviewer(e.target.value)}
        style={{ marginTop: 6 }}
      />
      {msg && <div className="notice" style={{ borderColor: "var(--official)", color: "var(--official)" }}>{msg}</div>}
      {err && <div className="error">{err}</div>}
      <h2>Review tasks</h2>
      {tasks.length === 0 && <div className="muted">No pending tasks.</div>}
      {tasks.map((t) => (
        <div className="item" key={t.id} style={{ cursor: "default" }}>
          <div className="title">{t.task_type}</div>
          <div className="sub">
            {t.target_type} · {t.reason ?? ""}
          </div>
          <div className="mono muted" style={{ margin: "4px 0" }}>
            {t.target_id.slice(0, 8)}… · prio {t.priority}
          </div>
          <div style={{ display: "flex", gap: 6 }}>
            <button
              className="primary"
              disabled={!key || !reviewer}
              onClick={() => resolve(t, true)}
            >
              Approve
            </button>
            <button
              className="danger"
              disabled={!key || !reviewer}
              onClick={() => resolve(t, false)}
            >
              Dismiss
            </button>
          </div>
        </div>
      ))}
    </div>
  );
}

"use client";

/** Shared provenance badges — a record/source must never *look* real when
 *  it is synthetic, and machine-derived data must never look official. */

export function DataClassBadge({ dataClass }: { dataClass?: string | null }) {
  if (dataClass === "official")
    return <span className="badge official">REAL DATA</span>;
  if (dataClass === "mixed")
    return <span className="badge derived">MIXED</span>;
  if (dataClass === "synthetic")
    return <span className="badge synthetic">DEMO</span>;
  return <span className="badge">UNVERIFIED</span>;
}

const HEALTH_CLASS: Record<string, string> = {
  healthy: "official",
  unchanged: "official",
  changed: "changed",
  degraded: "derived",
  needs_review: "derived",
  failing: "unreviewed",
  blocked: "unreviewed",
  disabled: "",
  unknown: "",
};

export function HealthBadge({ health }: { health?: string | null }) {
  const cls = HEALTH_CLASS[health ?? ""] ?? "";
  return <span className={`badge ${cls}`}>{health ?? "unknown"}</span>;
}

export function OriginBadge({ origin }: { origin?: string | null }) {
  if (!origin) return null;
  const cls = origin === "official_explicit" || origin === "human_reviewed"
    ? "official"
    : origin === "derived_machine" || origin === "unknown"
      ? "unreviewed"
      : "derived";
  return <span className={`badge ${cls}`}>{origin}</span>;
}

/** Tiny relative-time helper for freshness columns. */
export function ago(isoDate?: string | null): string {
  if (!isoDate) return "never";
  const then = new Date(isoDate).getTime();
  if (Number.isNaN(then)) return "—";
  const s = Math.max(0, (Date.now() - then) / 1000);
  if (s < 90) return "just now";
  const m = s / 60;
  if (m < 90) return `${Math.round(m)}m ago`;
  const h = m / 60;
  if (h < 48) return `${Math.round(h)}h ago`;
  return `${Math.round(h / 24)}d ago`;
}

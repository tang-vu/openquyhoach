import type { MetadataSnapshot } from "./metadata-snapshot";

export function downloadMetadataSnapshot(snapshot: MetadataSnapshot) {
  const safe = (id: string) => id.replace(/[^a-zA-Z0-9_-]/g, "_").slice(0, 80);
  const blob = new Blob([JSON.stringify(snapshot, null, 2) + "\n"], { type: "application/json;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  try {
    anchor.href = url;
    anchor.download = `openquyhoach-${safe(snapshot.selection.record_id)}-${safe(snapshot.selection.version_id)}-metadata.json`;
    document.body.append(anchor);
    anchor.click();
  } finally {
    anchor.remove();
    setTimeout(() => URL.revokeObjectURL(url), 0);
  }
}

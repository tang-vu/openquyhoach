import { act, useLayoutEffect } from "react";
import { createRoot } from "react-dom/client";
import { expect, it, vi } from "vitest";
import MetadataSnapshotDownload from "@/components/MetadataSnapshotDownload";
import { downloadMetadataSnapshot } from "@/lib/download-metadata-snapshot";
import { api } from "@/lib/api";
import { detail, recordDetail } from "./navigation-support";

vi.mock("@/lib/download-metadata-snapshot", () => ({ downloadMetadataSnapshot: vi.fn() }));

it("hides a prior capture during a replacement commit before passive cleanup, including repeated IDs", async () => {
  vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);
  const load = vi.spyOn(api, "manifest").mockImplementation(async id => ({
    schema_version: "oqh.manifest/1", planning_record: "A", planning_version: id.replace("publication-", ""),
    sources: [], datasets: [], artifacts: [], disclaimer: "Synthetic fixture only.",
  }));
  const container = document.createElement("div"); document.body.append(container);
  const root = createRoot(container);
  const record = recordDetail("A");
  const first = detail("A1");
  const observations: string[] = [];
  function Probe({ version, replacement }: { version: ReturnType<typeof detail>; replacement: boolean }) {
    useLayoutEffect(() => {
      if (replacement) observations.push(container.textContent ?? "");
    }, [version, replacement]);
    return <MetadataSnapshotDownload record={record} version={version} />;
  }
  try {
    await act(async () => root.render(<Probe version={first} replacement={false} />));
    await act(async () => container.querySelector<HTMLButtonElement>("button")!.click());
    expect(container.textContent).toContain("Metadata snapshot ready");
    await act(async () => root.render(<Probe version={detail("A2")} replacement />));
    await act(async () => root.render(<Probe version={detail("A1")} replacement />));
    expect(observations).toHaveLength(2);
    for (const text of observations) {
      expect(text).not.toContain("Metadata snapshot ready");
      expect(text).not.toContain("Download snapshot");
    }
    expect(downloadMetadataSnapshot).not.toHaveBeenCalled();
  } finally {
    await act(async () => root.unmount()); container.remove(); load.mockRestore(); vi.unstubAllGlobals();
  }
});

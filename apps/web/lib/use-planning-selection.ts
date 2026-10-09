"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api, type Publication } from "./api";
import { assertRecordDetail, type RecordDetail } from "./metadata-snapshot-validation";

type Selection = { id: string; generation: number };
type RecordSelection = Selection & { frameRequest: number };
type VersionSelection = Selection & { frameRequest: number | null };
type RecordData = { owner: RecordSelection; value: RecordDetail };

/** Record navigation owns its versions, map targets and async completions. */
export function usePlanningSelection(publications: Publication[]) {
  const serial = useRef(0);
  const mounted = useRef(false);
  const recordRef = useRef<RecordSelection | null>(null);
  const versionRef = useRef<VersionSelection | null>(null);
  const frameRequest = useRef(0);
  const [record, setRecord] = useState<RecordSelection | null>(null);
  const [loaded, setLoaded] = useState<RecordData | null>(null);
  const [version, setVersion] = useState<VersionSelection | null>(null);
  const [rasterId, setRasterId] = useState<string | null>(null);
  const [comparePubId, setComparePubId] = useState<string | null>(null);
  const [bbox, setBbox] = useState<number[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; };
  }, []);

  const selectRecord = useCallback((id: string) => {
    if (recordRef.current?.id === id) return;
    const next = { id, generation: ++serial.current, frameRequest: ++frameRequest.current };
    recordRef.current = next;
    versionRef.current = null;
    setRecord(next);
    setLoaded(null);
    setVersion(null);
    setRasterId(null);
    setComparePubId(null);
    setBbox(null);
    setError(null);
  }, []);

  const beginVersion = useCallback((id: string, owner: RecordSelection, frame = true) => {
    if (recordRef.current !== owner || versionRef.current?.id === id) return;
    const next = { id, generation: ++serial.current,
      frameRequest: frame ? ++frameRequest.current : null };
    versionRef.current = next;
    setVersion(next);
    setRasterId(null);
    if (frame) setBbox(null);
  }, []);

  useEffect(() => {
    if (!record) return;
    let active = true;
    api.recordDetail(record.id).then((detail) => {
      if (!active || recordRef.current !== record) return;
      assertRecordDetail(detail, record.id);
      setLoaded({ owner: record, value: detail });
      const first = detail.versions[0];
      // A later explicit focus also supersedes extent work not started yet.
      if (first) beginVersion(first.id, record, frameRequest.current === record.frameRequest);
    }).catch((e) => {
      if (active && recordRef.current === record) setError(String(e));
    });
    return () => { active = false; };
  }, [record, beginVersion]);

  useEffect(() => {
    if (version?.frameRequest == null || frameRequest.current !== version.frameRequest) return;
    let active = true;
    const request = version.frameRequest;
    const current = () => active && versionRef.current === version &&
      frameRequest.current === request;
    api.versionExtent(version.id).then((extent) => {
      if (current()) setBbox(extent.bbox);
    }).catch(() => {
      if (current()) setBbox(null);
    });
    return () => { active = false; };
  }, [version]);

  const recordDetail = loaded?.owner === record ? loaded?.value ?? null : null;
  const versions = recordDetail?.versions ?? [];
  const selectVersion = useCallback((id: string) => {
    if (record && loaded?.owner === record &&
      loaded.value.versions.some((item) => item.id === id)) beginVersion(id, record);
  }, [record, loaded, beginVersion]);

  // A comparison belongs to its record, not to the currently viewed version.
  const onCompare = useCallback((id: string | null) => {
    if (mounted.current && record && recordRef.current === record)
      setComparePubId(id);
  }, [record]);

  const onRasterToggle = useCallback((id: string | null) => {
    if (mounted.current && version && versionRef.current === version)
      setRasterId(id);
  }, [version]);

  const focusBbox = useCallback((bounds: number[]) => {
    ++frameRequest.current;
    setBbox(bounds);
  }, []);

  return {
    recordId: record?.id ?? null,
    recordKey: record?.generation,
    versionId: version?.id ?? null,
    versionKey: version?.generation,
    recordDetail,
    versions,
    loading: !!record && loaded?.owner !== record && !error,
    error,
    pubId: publications.find((pub) => pub.planning_version_id === version?.id)?.id ?? null,
    rasterId, comparePubId, bbox,
    selectRecord, selectVersion, onCompare, onRasterToggle, focusBbox,
  };
}

"use client";

import { Activity } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import AnnotatedVideoCanvas from "@/components/AnnotatedVideoCanvas";
import AuditVerdictPanel from "@/components/AuditVerdictPanel";
import CompareCycles, { type Cycle } from "@/components/CompareCycles";
import SopEditorPanel from "@/components/SopEditorPanel";
import TelemetryTimeline from "@/components/TelemetryTimeline";
import { compileSop, compileSopFile, getLimits, getPresets, getTracks, startJob, waitForJob } from "@/lib/api";
import type { CompiledSop, JobResult, Limits, Preset, Tracks } from "@/lib/types";

export default function Workbench() {
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const resultsRef = useRef<HTMLElement | null>(null);
  const [presets, setPresets] = useState<Preset[]>([]);
  const [presetId, setPresetId] = useState<string | null>(null);
  const [upload, setUpload] = useState<File | null>(null);
  const [uploadUrl, setUploadUrl] = useState<string | null>(null);
  const [sopText, setSopText] = useState("");
  const [sop, setSop] = useState<CompiledSop | null>(null);
  const [compiling, setCompiling] = useState(false);
  const [compileNote, setCompileNote] = useState<string | null>(null);
  const [running, setRunning] = useState(false);
  const [stage, setStage] = useState<string | null>(null);
  const [result, setResult] = useState<JobResult | null>(null);
  const [tracks, setTracks] = useState<Tracks | null>(null);
  const [time, setTime] = useState(0);
  const [hidden, setHidden] = useState<Set<string>>(new Set());
  const [error, setError] = useState<string | null>(null);
  const [limits, setLimits] = useState<Limits | null>(null);
  const [compareOpen, setCompareOpen] = useState(false);
  const [reference, setReference] = useState<Cycle | null>(null);
  const [referenceId, setReferenceId] = useState<string | null>(null);
  const [referenceStage, setReferenceStage] = useState<string | null>(null);
  const [referenceError, setReferenceError] = useState<string | null>(null);
  const refreshLimits = useCallback(() => {
    getLimits().then(setLimits).catch(() => {});
  }, []);

  const selectPreset = useCallback((p: Preset) => {
    setPresetId(p.id);
    setUpload(null);
    setUploadUrl(null);
    setSopText(p.sop_text);
    setSop(p.sop);
    setCompileNote("Rules for this preset are already loaded. Recompile to regenerate them with Muse Spark.");
    setResult(null);
    setTracks(null);
    setStage(null);
    setError(null);
    setCompareOpen(false);
    setReference(null);
  }, []);

  const autoRun = useRef(false);

  // ?preset=<id> selects a preset, &run=1 analyzes it on load (handy for demo recordings).
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    getPresets()
      .then((ps) => {
        setPresets(ps);
        const wanted = ps.find((p) => p.id === params.get("preset")) ?? ps[0];
        if (wanted) selectPreset(wanted);
        autoRun.current = params.get("run") === "1";
      })
      .catch(() => setError("Backend unreachable. Start it with: uvicorn main:app --port 8000"));
    refreshLimits();
  }, [selectPreset, refreshLimits]);

  const onUpload = (f: File) => {
    setUpload(f);
    setUploadUrl(URL.createObjectURL(f));
    setPresetId(null);
    setResult(null);
    setTracks(null);
  };

  const onCompile = async () => {
    setCompiling(true);
    setError(null);
    const t0 = performance.now();
    try {
      const r = await compileSop(sopText);
      setSop(r.sop);
      setCompileNote(
        r.cached ? "Served from the compile cache." : `Compiled by Muse Spark 1.3 in ${((performance.now() - t0) / 1000).toFixed(1)}s.`,
      );
    } catch (e) {
      setError(`Compile failed: ${(e as Error).message}`);
    } finally {
      setCompiling(false);
      refreshLimits();
    }
  };

  const onCompileFile = async (f: File) => {
    setCompiling(true);
    setError(null);
    try {
      const r = await compileSopFile(f);
      setSopText(r.text);
      setSop(r.sop);
      setCompileNote(`Compiled ${f.name} with Muse Spark 1.3.`);
    } catch (e) {
      setError(`Compile failed: ${(e as Error).message}`);
    } finally {
      setCompiling(false);
      refreshLimits();
    }
  };

  const onAnalyze = async () => {
    if (!sop) return;
    setRunning(true);
    setError(null);
    setResult(null);
    setTracks(null);
    setCompareOpen(false);
    setReference(null);
    setStage("Submitting job");
    try {
      const { job_id } = await startJob(sop, upload ? { video: upload } : { presetId: presetId! });
      const res = await waitForJob(job_id, setStage);
      setTracks(await getTracks(res.tracks_url));
      setResult(res);
      setStage(res.cached ? "Served from cache" : "Analysis complete");
      const startAt = Number(new URLSearchParams(window.location.search).get("t"));
      if (startAt && videoRef.current) videoRef.current.currentTime = startAt;
      // On phones the results sit below the rules, so bring them into view.
      if (window.matchMedia("(max-width: 767px)").matches) {
        resultsRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
      }
    } catch (e) {
      setError((e as Error).message);
      setStage(null);
    } finally {
      setRunning(false);
      refreshLimits();
    }
  };

  useEffect(() => {
    if (autoRun.current && sop && presetId) {
      autoRun.current = false;
      onAnalyze();
    }
    // onAnalyze reads the latest state; only the trigger matters here
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sop, presetId]);

  const seek = useCallback((t: number) => {
    const v = videoRef.current;
    if (!v) return;
    v.pause();
    v.currentTime = Math.max(0, t);
  }, []);

  const toggle = (label: string) =>
    setHidden((h) => {
      const n = new Set(h);
      if (n.has(label)) n.delete(label);
      else n.add(label);
      return n;
    });

  const preset = presets.find((p) => p.id === presetId);
  const videoUrl = result?.video_url ?? uploadUrl ?? preset?.video_url ?? null;
  const sourceLabel = upload?.name ?? preset?.title ?? "";

  // Other presets whose rules check the same tool/part pairs can serve as a reference cycle.
  const pairsOf = (s: CompiledSop) =>
    [...new Set(s.steps.map((x) => `${x.actor_object}|${x.target_object}`))].sort().join(",");
  const candidates = result ? presets.filter((p) => p.id !== presetId && pairsOf(p.sop) === pairsOf(result.sop)) : [];

  // The reference runs under this cycle's rules, so both are judged the same way.
  const loadReference = async (ref: Preset) => {
    if (!result) return;
    setReferenceId(ref.id);
    setReference(null);
    setReferenceError(null);
    setReferenceStage("Running the reference cycle");
    try {
      const { job_id } = await startJob(result.sop, { presetId: ref.id });
      const res = await waitForJob(job_id, setReferenceStage);
      setReference({ label: ref.title, result: res, tracks: await getTracks(res.tracks_url) });
    } catch (e) {
      setReferenceError(`Couldn't load the reference: ${(e as Error).message}`);
    } finally {
      setReferenceStage(null);
    }
  };

  const openCompare = () => {
    setCompareOpen(true);
    const current = candidates.find((c) => c.id === referenceId);
    if (!reference || !current) void loadReference(candidates.find((c) => c.reference) ?? candidates[0]);
  };

  // Layouts: one scrolling column on phones, a sticky rules column beside the results on
  // tablets and small laptops, and three fixed-height columns from 1280px up.
  return (
    <div className="flex min-h-dvh flex-col pb-24 md:pb-0 xl:h-screen xl:min-h-0 xl:overflow-hidden">
      <header className="flex h-12 shrink-0 items-center gap-3 border-b border-line px-4">
        <div className="flex items-center gap-2">
          <div className="flex h-6 w-6 items-center justify-center rounded bg-accent text-black">
            <Activity size={15} strokeWidth={2.5} />
          </div>
          <span className="text-[15px] font-bold tracking-tight">KineSight</span>
        </div>
        <span className="hidden text-[12px] text-ink-3 lg:inline">Sensorless visual telemetry & SOP compliance engine</span>
        <div className="num ml-auto hidden items-center gap-1.5 text-[10.5px] text-ink-2 sm:flex">
          {["SAM 3.1", "OpenCV kinematics", "Muse Spark 1.3", "Muse Image"].map((m) => (
            <span key={m} className="rounded-full border border-line-2 px-2 py-0.5">
              {m}
            </span>
          ))}
        </div>
      </header>

      {error && (
        <div className="shrink-0 border-b border-fail/40 bg-fail/10 px-4 py-1.5 text-[12px] text-fail">{error}</div>
      )}

      <main className="grid flex-1 grid-cols-1 gap-3 p-3 md:grid-cols-[minmax(260px,300px)_minmax(0,1fr)] md:grid-rows-[auto_1fr] xl:min-h-0 xl:grid-cols-[280px_minmax(0,1fr)_340px] xl:grid-rows-[minmax(0,1fr)] 2xl:grid-cols-[300px_minmax(0,1fr)_380px]">
        <section className="panel flex flex-col p-3 md:sticky md:top-3 md:row-span-2 md:max-h-[calc(100dvh-4.5rem)] md:self-start xl:static xl:row-span-1 xl:max-h-none xl:min-h-0 xl:self-stretch">
          <SopEditorPanel
            presets={presets}
            presetId={presetId}
            onPreset={selectPreset}
            sopText={sopText}
            onSopText={setSopText}
            sop={sop}
            onSopChange={(s) => {
              setSop(s);
              setCompileNote("Rules edited by reviewer.");
            }}
            compiling={compiling}
            compileNote={compileNote}
            onCompile={onCompile}
            onCompileFile={onCompileFile}
            upload={upload}
            onUpload={onUpload}
            running={running}
            stage={stage}
            onAnalyze={onAnalyze}
            trackLabels={tracks?.labels ?? []}
            limits={limits}
          />
        </section>

        <section ref={resultsRef} className="flex scroll-mt-3 flex-col gap-3 xl:min-h-0">
          <div className="panel p-3 xl:min-h-[260px] xl:flex-1">
            <AnnotatedVideoCanvas
              videoUrl={videoUrl}
              tracks={tracks}
              videoRef={videoRef}
              onTime={setTime}
              hidden={hidden}
              onToggle={toggle}
            />
          </div>
          <div className="panel shrink-0 p-3">
            {result && tracks ? (
              <TelemetryTimeline result={result} tracks={tracks} time={time} onSeek={seek} />
            ) : (
              <div className="flex h-[200px] items-center justify-center px-4 text-center text-sm text-ink-3">
                {running ? stage : "Velocity and contact timeline appear after analysis"}
              </div>
            )}
          </div>
        </section>

        <section className="panel p-3 xl:min-h-0">
          <AuditVerdictPanel
            result={result}
            onSeek={seek}
            sourceLabel={sourceLabel}
            onCompare={candidates.length && tracks ? openCompare : undefined}
          />
        </section>
      </main>
      {compareOpen && result && tracks && (
        <CompareCycles
          current={{ label: sourceLabel, result, tracks }}
          reference={reference}
          candidates={candidates}
          referenceId={referenceId}
          onReference={loadReference}
          loading={referenceStage}
          error={referenceError}
          onClose={() => setCompareOpen(false)}
        />
      )}
      {preset && (
        <footer className="num shrink-0 border-t border-line px-4 py-1 text-[10px] text-ink-3">
          Footage: <a className="underline" href={preset.source.url} target="_blank" rel="noreferrer">{preset.source.credit}</a>
        </footer>
      )}
    </div>
  );
}

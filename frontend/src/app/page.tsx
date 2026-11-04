"use client";

import { Activity } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import AnnotatedVideoCanvas from "@/components/AnnotatedVideoCanvas";
import AuditVerdictPanel from "@/components/AuditVerdictPanel";
import SopEditorPanel from "@/components/SopEditorPanel";
import TelemetryTimeline from "@/components/TelemetryTimeline";
import { compileSop, compileSopFile, getJob, getPresets, getTracks, startJob } from "@/lib/api";
import type { CompiledSop, JobResult, Preset, Tracks } from "@/lib/types";

export default function Workbench() {
  const videoRef = useRef<HTMLVideoElement | null>(null);
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
  }, []);

  const [autoRun, setAutoRun] = useState(false);

  // ?preset=<id> selects a preset, &run=1 analyzes it on load (handy for demo recordings).
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    getPresets()
      .then((ps) => {
        setPresets(ps);
        const wanted = ps.find((p) => p.id === params.get("preset")) ?? ps[0];
        if (wanted) selectPreset(wanted);
        setAutoRun(params.get("run") === "1");
      })
      .catch(() => setError("Backend unreachable. Start it with: uvicorn main:app --port 8000"));
  }, [selectPreset]);

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
    }
  };

  const onAnalyze = async () => {
    if (!sop) return;
    setRunning(true);
    setError(null);
    setResult(null);
    setTracks(null);
    setStage("Submitting job");
    try {
      const { job_id } = await startJob(sop, upload ? { video: upload } : { presetId: presetId! });
      for (;;) {
        const job = await getJob(job_id);
        setStage(job.stage);
        if (job.status === "done" && job.result) {
          const tr = await getTracks(job.result.tracks_url);
          setTracks(tr);
          setResult(job.result);
          setStage(job.result.cached ? "Served from cache" : "Analysis complete");
          const startAt = Number(new URLSearchParams(window.location.search).get("t"));
          if (startAt && videoRef.current) videoRef.current.currentTime = startAt;
          break;
        }
        if (job.status === "failed") throw new Error(job.error ?? "analysis failed");
        await new Promise((r) => setTimeout(r, 800));
      }
    } catch (e) {
      setError((e as Error).message);
      setStage(null);
    } finally {
      setRunning(false);
    }
  };

  useEffect(() => {
    if (autoRun && sop && presetId) {
      setAutoRun(false);
      onAnalyze();
    }
    // onAnalyze reads the latest state; only the trigger matters here
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [autoRun, sop, presetId]);

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

  return (
    <div className="flex h-screen flex-col overflow-hidden">
      <header className="flex h-12 shrink-0 items-center gap-3 border-b border-line px-4">
        <div className="flex items-center gap-2">
          <div className="flex h-6 w-6 items-center justify-center rounded bg-accent text-black">
            <Activity size={15} strokeWidth={2.5} />
          </div>
          <span className="text-[15px] font-bold tracking-tight">KineSight</span>
        </div>
        <span className="hidden text-[12px] text-ink-3 md:inline">Sensorless visual telemetry & SOP compliance engine</span>
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

      <main className="grid min-h-0 flex-1 grid-cols-1 gap-3 overflow-auto p-3 lg:grid-cols-[300px_minmax(0,1fr)_370px] lg:overflow-hidden">
        <section className="panel min-h-0 p-3">
          <SopEditorPanel
            presets={presets}
            presetId={presetId}
            onPreset={selectPreset}
            sopText={sopText}
            onSopText={setSopText}
            sop={sop}
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
          />
        </section>

        <section className="flex min-h-0 flex-col gap-3">
          <div className="panel min-h-[320px] flex-1 p-3">
            <AnnotatedVideoCanvas
              videoUrl={videoUrl}
              tracks={tracks}
              videoRef={videoRef}
              onTime={setTime}
              hidden={hidden}
              onToggle={toggle}
            />
          </div>
          <div className="panel h-[250px] shrink-0 p-3">
            {result && tracks ? (
              <TelemetryTimeline result={result} tracks={tracks} time={time} onSeek={seek} />
            ) : (
              <div className="flex h-full items-center justify-center text-sm text-ink-3">
                {running ? stage : "Velocity and contact timeline appear after analysis"}
              </div>
            )}
          </div>
        </section>

        <section className="panel min-h-0 p-3">
          <AuditVerdictPanel result={result} onSeek={seek} />
        </section>
      </main>
      {preset && (
        <footer className="num shrink-0 border-t border-line px-4 py-1 text-[10px] text-ink-3">
          Footage: <a className="underline" href={preset.source.url} target="_blank" rel="noreferrer">{preset.source.credit}</a>
        </footer>
      )}
    </div>
  );
}

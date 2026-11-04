"use client";

import { FileUp, Film, Loader2, Play, Sparkles, X } from "lucide-react";
import { useRef } from "react";
import { colorFor } from "@/lib/api";
import type { CompiledSop, Limits, Preset, SopStep } from "@/lib/types";

interface Props {
  presets: Preset[];
  presetId: string | null;
  onPreset: (p: Preset) => void;
  sopText: string;
  onSopText: (t: string) => void;
  sop: CompiledSop | null;
  onSopChange: (sop: CompiledSop) => void;
  compiling: boolean;
  compileNote: string | null;
  onCompile: () => void;
  onCompileFile: (f: File) => void;
  upload: File | null;
  onUpload: (f: File) => void;
  running: boolean;
  stage: string | null;
  onAnalyze: () => void;
  trackLabels: string[];
  limits: Limits | null;
}

export default function SopEditorPanel(p: Props) {
  const sopFile = useRef<HTMLInputElement>(null);
  const videoFile = useRef<HTMLInputElement>(null);
  const labels = p.trackLabels.length ? p.trackLabels : [...(p.sop?.sam_prompts ?? []), "hand"];

  // Compiled rules are a proposal; the engineer can tune or drop them before analysis.
  const editStep = (n: number, patch: Partial<SopStep>) =>
    p.sop && p.onSopChange({ ...p.sop, steps: p.sop.steps.map((s) => (s.step_number === n ? { ...s, ...patch } : s)) });

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex min-h-0 flex-1 flex-col gap-3 md:overflow-y-auto md:pr-1">
        <div>
          <div className="label mb-1.5">Workstation feed</div>
          <div className="space-y-1.5">
            {p.presets.map((preset) => (
              <button
                key={preset.id}
                onClick={() => p.onPreset(preset)}
                className={`w-full rounded-md border px-2.5 py-2 text-left transition ${
                  p.presetId === preset.id && !p.upload ? "border-accent bg-accent/5" : "border-line bg-panel-2 hover:border-line-2"
                }`}
              >
                <div className="text-[13px] font-medium text-ink">{preset.title}</div>
                <div className="mt-0.5 text-[11px] leading-snug text-ink-3">{preset.subtitle}</div>
              </button>
            ))}
            {p.limits?.live === false ? (
              <div className="rounded-md border border-dashed border-line-2 px-2.5 py-2 text-[11px] leading-snug text-ink-3">
                This server replays recorded analyses. To analyze your own footage or edited rules,{" "}
                <a className="text-ink-2 underline" href="https://github.com/irrepressible007/kinesight" target="_blank" rel="noreferrer">
                  run KineSight locally
                </a>
                .
              </div>
            ) : (
              <button
                onClick={() => videoFile.current?.click()}
                className={`flex w-full items-center gap-2 rounded-md border border-dashed px-2.5 py-2 text-left text-[12px] transition ${
                  p.upload ? "border-accent text-ink" : "border-line-2 text-ink-2 hover:border-ink-3"
                }`}
              >
                <Film size={14} />
                {p.upload ? p.upload.name : "Upload your own bench video (mp4 / mov)"}
              </button>
            )}
            <input
              ref={videoFile}
              type="file"
              accept="video/*"
              className="hidden"
              onChange={(e) => e.target.files?.[0] && p.onUpload(e.target.files[0])}
            />
            {p.limits?.live && p.limits.video_left != null && (
              <div className="num px-0.5 text-[10.5px] leading-snug text-ink-3">
                Public demo: clips up to {p.limits.max_video_sec ?? "∞"}s · {p.limits.video_left} live video
                analyses and {p.limits.compile_left} new compiles left today. A new clip takes a few minutes on
                this free server.
              </div>
            )}
          </div>
        </div>

        <div className="flex shrink-0 flex-col">
          <div className="mb-1.5 flex items-center justify-between">
            <span className="label">Standard operating procedure</span>
            <button onClick={() => sopFile.current?.click()} className="flex items-center gap-1 text-[11px] text-ink-2 hover:text-ink">
              <FileUp size={12} /> PDF / TXT
            </button>
            <input
              ref={sopFile}
              type="file"
              accept=".pdf,.txt,.md"
              className="hidden"
              onChange={(e) => e.target.files?.[0] && p.onCompileFile(e.target.files[0])}
            />
          </div>
          <textarea
            value={p.sopText}
            onChange={(e) => p.onSopText(e.target.value)}
            spellCheck={false}
            className="h-44 shrink-0 resize-none rounded-md border border-line bg-panel-2 p-2.5 text-[12px] leading-relaxed text-ink-2 outline-none focus:border-line-2"
          />
          <button
            onClick={p.onCompile}
            disabled={p.compiling || !p.sopText.trim()}
            className="mt-2 flex items-center justify-center gap-2 rounded-md border border-line-2 bg-panel-2 px-3 py-2 text-[13px] font-medium text-ink hover:border-accent disabled:opacity-50"
          >
            {p.compiling ? <Loader2 size={14} className="animate-spin" /> : <Sparkles size={14} className="text-accent" />}
            {p.compiling ? "Muse Spark 1.3 is compiling rules…" : "Compile rules with Muse Spark 1.3"}
          </button>
          {p.compileNote && <div className="mt-1 text-[11px] text-ink-3">{p.compileNote}</div>}
        </div>

        {p.sop && (
          <div>
            <div className="label mb-1.5">Compiled rules</div>
            <div className="mb-2 flex flex-wrap gap-1">
              {p.sop.sam_prompts.map((s) => (
                <span
                  key={s}
                  className="num rounded-full border px-2 py-0.5 text-[11px]"
                  style={{ borderColor: colorFor(labels, s), color: colorFor(labels, s) }}
                >
                  SAM: {s}
                </span>
              ))}
            </div>
            <div className="space-y-1.5">
              {p.sop.steps.map((s) => (
                <div key={s.step_number} className="group rounded-md border border-line bg-panel-2 px-2.5 py-2">
                  <div className="flex items-start gap-1 text-[12.5px] leading-snug text-ink">
                    <span className="flex-1">
                      <span className="num mr-1 text-ink-3">{s.step_number}.</span>
                      {s.description}
                    </span>
                    {p.sop!.steps.length > 1 && (
                      <button
                        onClick={() => p.onSopChange({ ...p.sop!, steps: p.sop!.steps.filter((x) => x.step_number !== s.step_number) })}
                        className="text-ink-3 opacity-0 transition group-hover:opacity-100 hover:text-fail"
                        title="Remove this rule"
                        aria-label="Remove this rule"
                      >
                        <X size={13} />
                      </button>
                    )}
                  </div>
                  <div className="num mt-1.5 flex flex-wrap items-center gap-1 text-[10.5px]">
                    <span style={{ color: colorFor(labels, s.actor_object) }}>{s.actor_object}</span>
                    <span className="text-ink-3">∩</span>
                    <span style={{ color: colorFor(labels, s.target_object) }}>{s.target_object}</span>
                    <label className="ml-auto flex items-center rounded bg-bg px-1.5 py-px text-ink-2">
                      ≥
                      <input
                        type="number"
                        step={0.1}
                        min={0}
                        value={s.min_contact_sec}
                        onChange={(e) => editStep(s.step_number, { min_contact_sec: Math.max(0, Number(e.target.value)) })}
                        className="num w-9 bg-transparent text-right outline-none"
                      />
                      s
                    </label>
                    <label className="flex items-center rounded bg-bg px-1.5 py-px text-ink-2">
                      ×
                      <input
                        type="number"
                        min={1}
                        value={s.required_contacts}
                        onChange={(e) => editStep(s.step_number, { required_contacts: Math.max(1, Math.round(Number(e.target.value))) })}
                        className="num w-6 bg-transparent text-right outline-none"
                      />
                    </label>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>

      {/* Always reachable: a floating bar on phones, pinned under the scrolling rules elsewhere. */}
      <div className="fixed inset-x-0 bottom-0 z-40 border-t border-line bg-bg/90 px-3 pt-2.5 pb-3 backdrop-blur md:static md:z-auto md:mt-3 md:bg-transparent md:px-0 md:pb-0 md:pt-3 md:backdrop-blur-none">
        <button
          onClick={p.onAnalyze}
          disabled={p.running || !p.sop || (!p.presetId && !p.upload)}
          className="flex w-full items-center justify-center gap-2 rounded-md bg-accent px-3 py-2.5 text-[14px] font-semibold text-black shadow-[0_6px_20px_-6px_rgba(255,200,80,0.55)] hover:brightness-105 disabled:opacity-50 disabled:shadow-none"
        >
          {p.running ? <Loader2 size={15} className="animate-spin" /> : <Play size={15} />}
          {p.running ? "Analyzing…" : "Analyze video"}
        </button>
        {p.stage && <div className="num mt-1.5 truncate text-center text-[11px] text-ink-3">{p.stage}</div>}
      </div>
    </div>
  );
}

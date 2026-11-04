"use client";

import { FileUp, Film, Loader2, Play, Sparkles } from "lucide-react";
import { useRef } from "react";
import { colorFor } from "@/lib/api";
import type { CompiledSop, Preset } from "@/lib/types";

interface Props {
  presets: Preset[];
  presetId: string | null;
  onPreset: (p: Preset) => void;
  sopText: string;
  onSopText: (t: string) => void;
  sop: CompiledSop | null;
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
}

export default function SopEditorPanel(p: Props) {
  const sopFile = useRef<HTMLInputElement>(null);
  const videoFile = useRef<HTMLInputElement>(null);
  const labels = p.trackLabels.length ? p.trackLabels : [...(p.sop?.sam_prompts ?? []), "hand"];

  return (
    <div className="flex h-full flex-col gap-3 overflow-y-auto pr-1">
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
          <button
            onClick={() => videoFile.current?.click()}
            className={`flex w-full items-center gap-2 rounded-md border border-dashed px-2.5 py-2 text-left text-[12px] transition ${
              p.upload ? "border-accent text-ink" : "border-line-2 text-ink-2 hover:border-ink-3"
            }`}
          >
            <Film size={14} />
            {p.upload ? p.upload.name : "Upload your own bench video (mp4 / mov)"}
          </button>
          <input
            ref={videoFile}
            type="file"
            accept="video/*"
            className="hidden"
            onChange={(e) => e.target.files?.[0] && p.onUpload(e.target.files[0])}
          />
        </div>
      </div>

      <div className="flex min-h-0 flex-col">
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
          className="h-44 resize-none rounded-md border border-line bg-panel-2 p-2.5 text-[12px] leading-relaxed text-ink-2 outline-none focus:border-line-2"
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
              <div key={s.step_number} className="rounded-md border border-line bg-panel-2 px-2.5 py-2">
                <div className="text-[12.5px] leading-snug text-ink">
                  <span className="num mr-1 text-ink-3">{s.step_number}.</span>
                  {s.description}
                </div>
                <div className="num mt-1.5 flex flex-wrap items-center gap-1 text-[10.5px]">
                  <span style={{ color: colorFor(labels, s.actor_object) }}>{s.actor_object}</span>
                  <span className="text-ink-3">∩</span>
                  <span style={{ color: colorFor(labels, s.target_object) }}>{s.target_object}</span>
                  <span className="ml-auto rounded bg-bg px-1.5 py-px text-ink-2">≥ {s.min_contact_sec}s</span>
                  <span className="rounded bg-bg px-1.5 py-px text-ink-2">× {s.required_contacts}</span>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      <div className="mt-auto pt-1">
        <button
          onClick={p.onAnalyze}
          disabled={p.running || !p.sop || (!p.presetId && !p.upload)}
          className="flex w-full items-center justify-center gap-2 rounded-md bg-accent px-3 py-2.5 text-[14px] font-semibold text-black hover:brightness-105 disabled:opacity-50"
        >
          {p.running ? <Loader2 size={15} className="animate-spin" /> : <Play size={15} />}
          {p.running ? "Analyzing…" : "Analyze video"}
        </button>
        {p.stage && <div className="num mt-1.5 truncate text-center text-[11px] text-ink-3">{p.stage}</div>}
      </div>
    </div>
  );
}

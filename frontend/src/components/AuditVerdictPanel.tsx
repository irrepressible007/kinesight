"use client";

import { AlertTriangle, CheckCircle2, Clock, ShieldCheck, ShieldQuestion, X, Zap } from "lucide-react";
import { useState } from "react";
import { media } from "@/lib/api";
import type { JobResult, StepStatus } from "@/lib/types";

const STATUS_TEXT: Record<StepStatus, string> = {
  PASS: "Pass",
  FAIL_MISSING: "Step skipped",
  FAIL_COUNT_SHORTFALL: "Contact count short",
  FAIL_SHORT_DURATION: "Contact too short",
  FAIL_ORDER: "Out of order",
};

interface Props {
  result: JobResult | null;
  onSeek: (t: number) => void;
}

export default function AuditVerdictPanel({ result, onSeek }: Props) {
  const [zoom, setZoom] = useState<string | null>(null);

  if (!result) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-2 px-6 text-center text-sm text-ink-3">
        <ShieldQuestion size={28} className="text-ink-3" />
        Run an analysis to see the QA verdict, root cause and corrective diagram.
      </div>
    );
  }

  const { verdict, telemetry } = result;
  const tone = verdict.overall_status === "PASS" ? "pass" : verdict.overall_status === "FAIL" ? "fail" : "warn";
  const color = { pass: "var(--pass)", fail: "var(--fail)", warn: "var(--warn)" }[tone];
  const totalMs = Object.values(result.timings_ms).reduce((a, b) => a + b, 0);

  return (
    <div className="flex h-full flex-col gap-3 overflow-y-auto pr-1">
      <div className="rounded-lg border p-3" style={{ borderColor: color, background: `color-mix(in srgb, ${color} 8%, transparent)` }}>
        <div className="flex items-center justify-between">
          <div>
            <div className="label">QA verdict</div>
            <div className="mt-0.5 flex items-center gap-2 text-2xl font-bold tracking-tight" style={{ color }}>
              {tone === "pass" ? <CheckCircle2 size={22} /> : <AlertTriangle size={22} />}
              {verdict.overall_status}
            </div>
          </div>
          <div className="text-right">
            <div className="label">Compliance</div>
            <div className="num text-2xl font-semibold" style={{ color }}>
              {verdict.compliance_score.toFixed(1)}%
            </div>
          </div>
        </div>
        <div className="num mt-2 flex gap-4 text-xs text-ink-2">
          <span className="flex items-center gap-1">
            <Clock size={12} /> cycle {verdict.cycle_time_sec.toFixed(1)}s
          </span>
          <span>{telemetry.total_frames} frames @ {telemetry.fps_analyzed} fps</span>
        </div>
      </div>

      <div>
        <div className="label mb-1.5">SOP steps</div>
        <div className="space-y-1.5">
          {telemetry.detected_interactions.map((s) => (
            <div key={s.step_number} className="rounded-md border border-line bg-panel-2 px-2.5 py-2">
              <div className="flex items-start justify-between gap-2">
                <div className="text-[13px] leading-snug text-ink">
                  <span className="num mr-1.5 text-ink-3">{s.step_number}.</span>
                  {s.description}
                </div>
                <span
                  className={`num shrink-0 rounded px-1.5 py-0.5 text-[10px] font-semibold ${
                    s.status === "PASS" ? "bg-pass/15 text-pass" : "bg-fail/15 text-fail"
                  }`}
                >
                  {STATUS_TEXT[s.status]}
                </span>
              </div>
              <div className="num mt-1 flex flex-wrap gap-1">
                {s.contact_intervals.map((iv, i) => (
                  <button
                    key={i}
                    onClick={() => onSeek(iv.start_sec)}
                    className={`rounded border px-1.5 py-px text-[10.5px] hover:border-ink-2 ${
                      iv.meets_min_duration ? "border-pass/40 text-pass" : "border-warn/50 text-warn"
                    }`}
                  >
                    #{i + 1} {iv.start_sec.toFixed(1)}s · {iv.duration_sec.toFixed(1)}s
                  </button>
                ))}
                {Array.from({ length: Math.max(0, s.contacts_required - s.contact_intervals.length) }).map((_, i) => (
                  <span key={`m${i}`} className="rounded border border-dashed border-fail/60 px-1.5 py-px text-[10.5px] text-fail">
                    #{s.contact_intervals.length + i + 1} missing
                  </span>
                ))}
              </div>
            </div>
          ))}
        </div>
      </div>

      {verdict.defects.map((d) => (
        <div key={d.step_number} className="rounded-lg border border-fail/40 bg-fail/5 p-3">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <span className="num rounded bg-fail px-1.5 py-0.5 text-[10px] font-bold text-black">{d.severity}</span>
              <span className="text-sm font-semibold">Step {d.step_number} · {STATUS_TEXT[d.status]}</span>
            </div>
            <button onClick={() => onSeek(d.timestamp_sec)} className="num text-xs text-fail underline-offset-2 hover:underline">
              t = {d.timestamp_sec.toFixed(2)}s ↗
            </button>
          </div>

          <div className="mt-2 flex items-center gap-1.5 text-[11px] text-ink-2">
            {d.auditor_confirmed === null ? (
              <span className="text-warn">Auditor unavailable · deterministic finding only</span>
            ) : (
              <>
                <ShieldCheck size={13} className={d.auditor_confirmed ? "text-fail" : "text-warn"} />
                Muse Spark 1.3 {d.auditor_confirmed ? "confirmed a genuine defect" : "judged this a measurement artifact"}
                {d.auditor_confidence !== null && <span className="num text-ink-3">({Math.round(d.auditor_confidence * 100)}%)</span>}
              </>
            )}
          </div>

          <div className="mt-2">
            <div className="label">Root cause</div>
            <p className="mt-0.5 text-[13px] leading-relaxed text-ink">{d.root_cause_summary}</p>
          </div>
          <div className="mt-2">
            <div className="label">Corrective action</div>
            <p className="mt-0.5 text-[13px] leading-relaxed text-ink">{d.corrective_action}</p>
          </div>

          {d.keyframe_paths.length > 0 && (
            <div className="mt-2.5">
              <div className="label mb-1">Audited keyframes</div>
              <div className="grid grid-cols-3 gap-1.5">
                {d.keyframe_paths.map((k) => (
                  <button key={k} onClick={() => setZoom(k)} className="overflow-hidden rounded border border-line hover:border-ink-2">
                    {/* eslint-disable-next-line @next/next/no-img-element */}
                    <img src={media(k)} alt="Keyframe with SAM 3.1 mask contours" className="aspect-video w-full object-cover" />
                  </button>
                ))}
              </div>
            </div>
          )}

          {d.corrective_diagram_url && (
            <div className="mt-2.5">
              <div className="label mb-1">Muse Image corrective diagram</div>
              <button onClick={() => setZoom(d.corrective_diagram_url!)} className="w-full overflow-hidden rounded border border-line hover:border-ink-2">
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img src={media(d.corrective_diagram_url)} alt="Corrective workstation diagram" className="w-full" />
              </button>
            </div>
          )}
        </div>
      ))}

      <div className="rounded-md border border-line bg-panel-2 px-2.5 py-2">
        <div className="label mb-1 flex items-center gap-1">
          <Zap size={11} /> Pipeline latency {result.cached && <span className="text-pass">· served from cache</span>}
        </div>
        <div className="num grid grid-cols-2 gap-x-3 text-[11px] text-ink-2">
          {Object.entries(result.timings_ms).map(([k, v]) => (
            <div key={k} className="flex justify-between">
              <span className="text-ink-3">{k}</span>
              <span>{v >= 1000 ? `${(v / 1000).toFixed(1)}s` : `${v.toFixed(0)}ms`}</span>
            </div>
          ))}
          <div className="col-span-2 mt-0.5 flex justify-between border-t border-line pt-0.5">
            <span className="text-ink-3">first run total</span>
            <span>{(totalMs / 1000).toFixed(1)}s</span>
          </div>
        </div>
      </div>

      {zoom && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/85 p-8" onClick={() => setZoom(null)}>
          <button className="absolute right-5 top-5 text-ink" aria-label="Close">
            <X size={22} />
          </button>
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src={media(zoom)} alt="" className="max-h-full max-w-full rounded-lg" />
        </div>
      )}
    </div>
  );
}

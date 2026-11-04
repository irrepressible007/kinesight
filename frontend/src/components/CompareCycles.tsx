"use client";

import { Play, X } from "lucide-react";
import { type RefObject, useCallback, useRef, useState } from "react";
import AnnotatedVideoCanvas from "@/components/AnnotatedVideoCanvas";
import type { JobResult, Preset, Tracks } from "@/lib/types";

export interface Cycle {
  label: string;
  result: JobResult;
  tracks: Tracks;
}

interface Props {
  current: Cycle;
  reference: Cycle | null;
  candidates: Preset[];
  referenceId: string | null;
  onReference: (p: Preset) => void;
  loading: string | null;
  error: string | null;
  onClose: () => void;
}

const toneOf = (s: string) => (s === "PASS" ? "text-pass" : s === "FAIL" ? "text-fail" : "text-warn");

// Two cycles of the same SOP side by side, on one seconds axis, so a skipped or rushed
// contact shows up as a gap against the reference.
export default function CompareCycles(p: Props) {
  const refA = useRef<HTMLVideoElement | null>(null);
  const refB = useRef<HTMLVideoElement | null>(null);
  const span = Math.max(
    p.current.result.telemetry.total_duration_sec,
    p.reference?.result.telemetry.total_duration_sec ?? 0,
  );

  const playBoth = () => {
    for (const v of [refA.current, refB.current]) {
      if (!v) continue;
      v.currentTime = 0;
      void v.play();
    }
  };

  return (
    <div className="fixed inset-0 z-50 overflow-y-auto bg-black/85 p-2 sm:p-6" onClick={p.onClose}>
      <div className="panel mx-auto max-w-6xl p-3 sm:p-4" onClick={(e) => e.stopPropagation()}>
        <div className="mb-3 flex flex-wrap items-center gap-2">
          <h2 className="text-[15px] font-bold">Compare cycles</h2>
          <span className="text-[12px] text-ink-3">Same rules, one time axis</span>
          {p.candidates.length > 1 && (
            <select
              value={p.referenceId ?? ""}
              onChange={(e) => {
                const c = p.candidates.find((x) => x.id === e.target.value);
                if (c) p.onReference(c);
              }}
              className="rounded-md border border-line-2 bg-panel-2 px-2 py-1 text-[12px] text-ink"
            >
              {p.candidates.map((c) => (
                <option key={c.id} value={c.id}>
                  Reference: {c.title}
                </option>
              ))}
            </select>
          )}
          <button
            onClick={playBoth}
            disabled={!p.reference}
            className="ml-auto flex items-center gap-1.5 rounded-md bg-accent px-3 py-1.5 text-[12px] font-semibold text-black disabled:opacity-50"
          >
            <Play size={13} /> Play both from start
          </button>
          <button onClick={p.onClose} className="text-ink-2 hover:text-ink" aria-label="Close">
            <X size={20} />
          </button>
        </div>

        <div className="grid gap-3 md:grid-cols-2">
          <CycleColumn title="This cycle" cycle={p.current} span={span} videoRef={refA} />
          {p.reference ? (
            <CycleColumn title="Reference" cycle={p.reference} span={span} videoRef={refB} />
          ) : (
            <div className="flex min-h-[200px] items-center justify-center rounded-lg border border-dashed border-line-2 px-4 text-center text-sm text-ink-3">
              {p.error ?? p.loading ?? "Loading the reference cycle…"}
            </div>
          )}
        </div>

        {p.reference && <ComparisonTable a={p.current.result} b={p.reference.result} />}
      </div>
    </div>
  );
}

function CycleColumn({ title, cycle, span, videoRef }: {
  title: string; cycle: Cycle; span: number; videoRef: RefObject<HTMLVideoElement | null>;
}) {
  const [hidden, setHidden] = useState<Set<string>>(new Set());
  const [time, setTime] = useState(0);
  const onTime = useCallback((t: number) => setTime(t), []);
  const { verdict, telemetry } = cycle.result;
  const toggle = (label: string) =>
    setHidden((h) => {
      const n = new Set(h);
      if (n.has(label)) n.delete(label);
      else n.add(label);
      return n;
    });
  const seek = (t: number) => {
    const v = videoRef.current;
    if (v) v.currentTime = Math.max(0, t);
  };
  const pct = (t: number) => `${(100 * t) / span}%`;

  return (
    <div className="min-w-0 rounded-lg border border-line bg-panel-2 p-2.5">
      <div className="mb-2 flex items-baseline justify-between gap-2">
        <div className="min-w-0">
          <div className="label">{title}</div>
          <div className="truncate text-[13px] font-medium text-ink">{cycle.label}</div>
        </div>
        <div className="num shrink-0 text-right">
          <span className={`text-[15px] font-bold ${toneOf(verdict.overall_status)}`}>{verdict.overall_status}</span>
          <span className={`ml-2 text-[13px] ${toneOf(verdict.overall_status)}`}>{verdict.compliance_score.toFixed(1)}%</span>
          <div className="text-[11px] text-ink-3">cycle {verdict.cycle_time_sec.toFixed(1)}s</div>
        </div>
      </div>
      <AnnotatedVideoCanvas
        videoUrl={cycle.result.video_url}
        tracks={cycle.tracks}
        videoRef={videoRef}
        onTime={onTime}
        hidden={hidden}
        onToggle={toggle}
        fill={false}
      />
      <div className="mt-2 space-y-1.5">
        {telemetry.detected_interactions.map((s) => {
          const defect = verdict.defects.find((d) => d.step_number === s.step_number);
          return (
            <div key={s.step_number}>
              <div className="num mb-0.5 flex justify-between text-[10.5px]">
                <span className="text-ink-3">STEP {s.step_number}</span>
                <span className={s.status === "PASS" ? "text-pass" : "text-fail"}>
                  {s.contacts_detected}/{s.contacts_required} contacts
                </span>
              </div>
              <div
                className="relative h-5 cursor-pointer rounded bg-bg"
                onClick={(e) => {
                  const r = e.currentTarget.getBoundingClientRect();
                  seek(((e.clientX - r.left) / r.width) * span);
                }}
              >
                {/* Past this cycle's end the lane is hatched: nothing was recorded there. */}
                <div
                  className="absolute inset-y-0 right-0 rounded-r bg-[repeating-linear-gradient(135deg,transparent_0_4px,rgba(255,255,255,0.05)_4px_8px)]"
                  style={{ left: pct(telemetry.total_duration_sec) }}
                />
                {s.contact_intervals.map((iv, i) => (
                  <div
                    key={i}
                    title={`${iv.start_sec}s – ${iv.end_sec}s (${iv.duration_sec}s)`}
                    className={`absolute top-1 bottom-1 rounded-sm ${iv.meets_min_duration ? "bg-pass/80" : "bg-warn/80"}`}
                    style={{ left: pct(iv.start_sec), width: pct(iv.duration_sec) }}
                  >
                    <span className="num absolute left-1 text-[9.5px] font-semibold leading-3 text-black/80">#{i + 1}</span>
                  </div>
                ))}
                {defect && (
                  <div
                    className="absolute -top-0.5 -bottom-0.5 w-2 -translate-x-1/2 rounded-sm bg-fail shadow-[0_0_10px_#ff5d5d]"
                    style={{ left: pct(defect.timestamp_sec) }}
                  />
                )}
                <div className="pointer-events-none absolute inset-y-0 w-px bg-ink" style={{ left: pct(time) }} />
              </div>
            </div>
          );
        })}
        <div className="num flex justify-between text-[10px] text-ink-3">
          <span>0s</span>
          <span>{(span / 2).toFixed(0)}s</span>
          <span>{span.toFixed(0)}s</span>
        </div>
      </div>
    </div>
  );
}

function ComparisonTable({ a, b }: { a: JobResult; b: JobResult }) {
  const qualifying = (r: JobResult, n: number) =>
    r.telemetry.detected_interactions.find((s) => s.step_number === n)?.contact_intervals.filter((iv) => iv.meets_min_duration) ?? [];
  const total = (ivs: { duration_sec: number }[]) => ivs.reduce((t, iv) => t + iv.duration_sec, 0);

  const rows: { label: string; a: string; b: string; worse: boolean }[] = [];
  for (const s of a.telemetry.detected_interactions) {
    const qa = qualifying(a, s.step_number);
    const qb = qualifying(b, s.step_number);
    rows.push({
      label: `Step ${s.step_number}: qualifying contacts`,
      a: `${qa.length} / ${s.contacts_required}`,
      b: `${qb.length} / ${s.contacts_required}`,
      worse: qa.length < qb.length,
    });
    rows.push({
      label: `Step ${s.step_number}: total contact time`,
      a: `${total(qa).toFixed(1)}s`,
      b: `${total(qb).toFixed(1)}s`,
      worse: total(qa) < total(qb) && qa.length < s.contacts_required,
    });
  }
  rows.push({
    label: "Cycle time",
    a: `${a.verdict.cycle_time_sec.toFixed(1)}s`,
    b: `${b.verdict.cycle_time_sec.toFixed(1)}s`,
    worse: false,
  });
  rows.push({
    label: "Compliance",
    a: `${a.verdict.compliance_score.toFixed(1)}%`,
    b: `${b.verdict.compliance_score.toFixed(1)}%`,
    worse: a.verdict.compliance_score < b.verdict.compliance_score,
  });

  return (
    <div className="mt-3 overflow-x-auto rounded-lg border border-line">
      <table className="num w-full text-[12px]">
        <thead>
          <tr className="bg-panel-2 text-left text-[10.5px] uppercase tracking-wider text-ink-3">
            <th className="px-3 py-1.5 font-semibold">Measure</th>
            <th className="px-3 py-1.5 font-semibold">This cycle</th>
            <th className="px-3 py-1.5 font-semibold">Reference</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.label} className="border-t border-line">
              <td className="px-3 py-1.5 font-sans text-ink-2">{r.label}</td>
              <td className={`px-3 py-1.5 ${r.worse ? "font-semibold text-fail" : "text-ink"}`}>{r.a}</td>
              <td className="px-3 py-1.5 text-ink">{r.b}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

"use client";

import { useMemo } from "react";
import { CartesianGrid, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { colorFor } from "@/lib/api";
import type { JobResult, Tracks } from "@/lib/types";

interface Props {
  result: JobResult;
  tracks: Tracks;
  time: number;
  onSeek: (t: number) => void;
}

// Shared horizontal geometry so the contact lanes line up with the chart's plot area.
const Y_AXIS_W = 46;
const RIGHT_PAD = 14;

export default function TelemetryTimeline({ result, tracks, time, onSeek }: Props) {
  const duration = result.telemetry.total_duration_sec;
  const actors = useMemo(
    () => Array.from(new Set(result.sop.steps.map((s) => s.actor_object))).filter((a) => tracks.speed[a]),
    [result, tracks],
  );

  const data = useMemo(() => {
    const rows = [];
    for (let f = 0; f < tracks.total_frames; f++) {
      const row: Record<string, number | null> = { t: +(f / tracks.fps).toFixed(3) };
      for (const a of actors) row[a] = tracks.speed[a][f];
      rows.push(row);
    }
    return rows;
  }, [tracks, actors]);

  const pct = (t: number) => `${(100 * t) / duration}%`;

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center justify-between">
        <span className="label">Kinematic telemetry · tool speed (frame diagonals / s)</span>
        <span className="num text-[11px] text-ink-3">
          dashed line = stationary-work threshold {tracks.stationary_speed}
        </span>
      </div>
      <div className="relative mt-1 min-h-0 flex-1">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart
            data={data}
            margin={{ top: 6, right: RIGHT_PAD, bottom: 0, left: 0 }}
            onClick={(state) => {
              const label = (state as { activeLabel?: number | string })?.activeLabel;
              if (label !== undefined) onSeek(Number(label));
            }}
          >
            <CartesianGrid stroke="#1e252e" vertical={false} />
            <XAxis
              dataKey="t"
              type="number"
              domain={[0, duration]}
              tick={{ fill: "#6b7685", fontSize: 10, fontFamily: "var(--font-jetbrains)" }}
              tickFormatter={(v) => `${v}s`}
              stroke="#2f3844"
            />
            <YAxis
              width={Y_AXIS_W}
              domain={[0, 1.5]}
              allowDataOverflow
              tick={{ fill: "#6b7685", fontSize: 10, fontFamily: "var(--font-jetbrains)" }}
              stroke="#2f3844"
            />
            <Tooltip
              contentStyle={{ background: "#12161c", border: "1px solid #2f3844", borderRadius: 8, fontSize: 12 }}
              labelFormatter={(v) => `t = ${Number(v).toFixed(2)} s`}
              formatter={(v) => (typeof v === "number" ? v.toFixed(3) : "—")}
            />
            <ReferenceLine y={tracks.stationary_speed} stroke="#6b7685" strokeDasharray="4 4" />
            {result.verdict.defects.map((d) => (
              <ReferenceLine key={d.step_number} x={d.timestamp_sec} stroke="#ff5d5d" strokeWidth={2} />
            ))}
            <ReferenceLine x={time} stroke="#e7ebf0" strokeWidth={1.5} />
            {actors.map((a) => (
              <Line
                key={a}
                dataKey={a}
                stroke={colorFor(tracks.labels, a)}
                strokeWidth={1.6}
                dot={false}
                isAnimationActive={false}
                connectNulls={false}
              />
            ))}
          </LineChart>
        </ResponsiveContainer>
      </div>

      <div className="mt-1 space-y-1.5" style={{ paddingLeft: Y_AXIS_W, paddingRight: RIGHT_PAD }}>
        {result.telemetry.detected_interactions.map((step) => {
          const defect = result.verdict.defects.find((d) => d.step_number === step.step_number);
          return (
            <div key={step.step_number}>
              <div className="mb-0.5 flex items-center gap-2 text-[11px]">
                <span className="num text-ink-3">STEP {step.step_number}</span>
                <span className="text-ink-2">
                  {step.actor} → {step.target}
                </span>
                <span className={`num ${step.status === "PASS" ? "text-pass" : "text-fail"}`}>
                  {step.contacts_detected}/{step.contacts_required} contacts ≥ {step.min_contact_sec}s
                </span>
              </div>
              <div
                className="relative h-6 cursor-pointer rounded bg-panel-2"
                onClick={(e) => {
                  const r = e.currentTarget.getBoundingClientRect();
                  onSeek(((e.clientX - r.left) / r.width) * duration);
                }}
              >
                {step.contact_intervals.map((iv, i) => (
                  <div
                    key={i}
                    title={`${iv.start_sec}s – ${iv.end_sec}s (${iv.duration_sec}s)`}
                    className={`absolute top-1 bottom-1 rounded-sm ${iv.meets_min_duration ? "bg-pass/80" : "bg-warn/80"}`}
                    style={{ left: pct(iv.start_sec), width: pct(iv.duration_sec) }}
                  >
                    <span className="num absolute left-1 top-0 text-[10px] font-semibold leading-4 text-black/80">
                      #{i + 1}
                    </span>
                  </div>
                ))}
                {defect && (
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      onSeek(defect.timestamp_sec);
                    }}
                    className="absolute -top-1 -bottom-1 w-3 -translate-x-1/2 rounded-sm bg-fail shadow-[0_0_12px_#ff5d5d]"
                    style={{ left: pct(defect.timestamp_sec) }}
                    title={`Defect at ${defect.timestamp_sec}s, click to jump there`}
                  />
                )}
                <div className="pointer-events-none absolute top-0 bottom-0 w-px bg-ink" style={{ left: pct(time) }} />
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

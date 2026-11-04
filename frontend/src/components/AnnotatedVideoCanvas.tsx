"use client";

import { Pause, Play, RotateCcw } from "lucide-react";
import { RefObject, useEffect, useRef, useState } from "react";
import { colorFor, media } from "@/lib/api";
import type { Tracks } from "@/lib/types";

interface Props {
  videoUrl: string | null;
  tracks: Tracks | null;
  videoRef: RefObject<HTMLVideoElement | null>;
  onTime: (t: number) => void;
  hidden: Set<string>;
  onToggle: (label: string) => void;
  /** Fill the parent's height on wide screens; off, the player keeps a 16:9 box everywhere. */
  fill?: boolean;
}

export default function AnnotatedVideoCanvas({ videoUrl, tracks, videoRef, onTime, hidden, onToggle, fill = true }: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [playing, setPlaying] = useState(false);
  const [time, setTime] = useState(0);
  const [duration, setDuration] = useState(0);

  // Draw loop: masks are drawn from normalized polygons, so the overlay fits any player size.
  useEffect(() => {
    let raf = 0;
    let lastReported = -1;
    const draw = () => {
      const video = videoRef.current;
      const canvas = canvasRef.current;
      if (video && canvas) {
        const rect = canvas.getBoundingClientRect();
        const dpr = window.devicePixelRatio || 1;
        if (canvas.width !== Math.round(rect.width * dpr) || canvas.height !== Math.round(rect.height * dpr)) {
          canvas.width = Math.round(rect.width * dpr);
          canvas.height = Math.round(rect.height * dpr);
        }
        const ctx = canvas.getContext("2d")!;
        ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
        ctx.clearRect(0, 0, rect.width, rect.height);
        const t = video.currentTime;
        if (tracks) {
          // Letterbox math: the video keeps its aspect ratio inside the element.
          const vr = tracks.width / tracks.height;
          const er = rect.width / rect.height;
          const w = er > vr ? rect.height * vr : rect.width;
          const h = er > vr ? rect.height : rect.width / vr;
          const ox = (rect.width - w) / 2;
          const oy = (rect.height - h) / 2;
          const fi = Math.min(tracks.total_frames - 1, Math.max(0, Math.round(t * tracks.fps)));
          for (const label of tracks.labels) {
            if (hidden.has(label)) continue;
            const entry = tracks.tracks[label]?.[fi];
            if (!entry) continue;
            const color = colorFor(tracks.labels, label);
            ctx.lineWidth = 2;
            ctx.strokeStyle = color;
            ctx.fillStyle = color + "38";
            for (const poly of entry.poly) {
              ctx.beginPath();
              for (let i = 0; i < poly.length; i += 2) {
                const x = ox + poly[i] * w;
                const y = oy + poly[i + 1] * h;
                if (i === 0) ctx.moveTo(x, y);
                else ctx.lineTo(x, y);
              }
              ctx.closePath();
              ctx.fill();
              ctx.stroke();
            }
            if (entry.c) {
              const x = ox + entry.c[0] * w;
              const y = oy + entry.c[1] * h;
              ctx.beginPath();
              ctx.arc(x, y, 4, 0, Math.PI * 2);
              ctx.fillStyle = color;
              ctx.fill();
              ctx.font = "600 12px var(--font-jetbrains), monospace";
              const tw = ctx.measureText(label).width;
              ctx.fillStyle = "rgba(11,14,18,0.82)";
              ctx.fillRect(x + 8, y - 9, tw + 10, 18);
              ctx.fillStyle = color;
              ctx.fillText(label, x + 13, y + 4);
            }
          }
        }
        if (Math.abs(t - lastReported) > 0.05) {
          lastReported = t;
          setTime(t);
          onTime(t);
        }
      }
      raf = requestAnimationFrame(draw);
    };
    raf = requestAnimationFrame(draw);
    return () => cancelAnimationFrame(raf);
  }, [tracks, hidden, videoRef, onTime]);

  const toggle = () => {
    const v = videoRef.current;
    if (!v) return;
    if (v.paused) v.play();
    else v.pause();
  };

  return (
    <div className={`flex flex-col ${fill ? "h-full" : ""}`}>
      <div
        className={`relative aspect-video w-full overflow-hidden rounded-lg bg-black ${fill ? "xl:aspect-auto xl:min-h-0 xl:flex-1" : ""}`}
      >
        {videoUrl ? (
          <>
            <video
              ref={videoRef}
              key={videoUrl}
              src={media(videoUrl)}
              className="absolute inset-0 h-full w-full object-contain"
              playsInline
              muted
              preload="auto"
              onPlay={() => setPlaying(true)}
              onPause={() => setPlaying(false)}
              onLoadedMetadata={(e) => setDuration(e.currentTarget.duration)}
            />
            <canvas ref={canvasRef} className="pointer-events-none absolute inset-0 h-full w-full" />
          </>
        ) : (
          <div className="flex h-full items-center justify-center text-sm text-ink-3">Select a preset or upload a video</div>
        )}
      </div>
      <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-2">
        <button
          onClick={toggle}
          className="flex h-8 w-8 items-center justify-center rounded-md border border-line-2 bg-panel-2 text-ink hover:border-accent"
          aria-label={playing ? "Pause" : "Play"}
        >
          {playing ? <Pause size={15} /> : <Play size={15} />}
        </button>
        <button
          onClick={() => videoRef.current && (videoRef.current.currentTime = 0)}
          className="flex h-8 w-8 items-center justify-center rounded-md border border-line-2 bg-panel-2 text-ink-2 hover:border-accent"
          aria-label="Restart"
        >
          <RotateCcw size={14} />
        </button>
        <span className="num whitespace-nowrap text-sm text-ink">
          {time.toFixed(2)}
          <span className="text-ink-3"> / {duration ? duration.toFixed(2) : "--"} s</span>
        </span>
        {tracks && (
          <span className="num hidden whitespace-nowrap text-xs text-ink-3 sm:inline">
            frame {Math.round(time * tracks.fps)} @ {tracks.fps} fps
          </span>
        )}
        <div className="flex w-full flex-wrap gap-1.5 sm:ml-auto sm:w-auto sm:justify-end">
          {tracks?.labels.map((label) => (
            <button
              key={label}
              onClick={() => onToggle(label)}
              className={`flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-xs transition ${
                hidden.has(label) ? "border-line text-ink-3" : "border-line-2 text-ink"
              }`}
            >
              <span
                className="h-2 w-2 rounded-full"
                style={{ background: hidden.has(label) ? "transparent" : colorFor(tracks.labels, label), border: `1px solid ${colorFor(tracks.labels, label)}` }}
              />
              {label}
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}

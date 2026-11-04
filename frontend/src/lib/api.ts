import type { CompiledSop, JobResult, JobStatus, Limits, Preset, Tracks } from "./types";

export const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000";

export const media = (path: string) => (path.startsWith("http") ? path : `${API_BASE}${path}`);

// Mask colors, in the same order the backend uses for keyframe overlays.
export const PALETTE = ["#ffc850", "#3caaff", "#78dc78", "#ff78c8", "#ff5a5a", "#50dcdc"];

export const colorFor = (labels: string[], label: string) =>
  PALETTE[Math.max(0, labels.indexOf(label)) % PALETTE.length];

async function json<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let detail = res.statusText;
    try {
      detail = (await res.json()).detail ?? detail;
    } catch {}
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return res.json();
}

export const getLimits = () =>
  fetch(`${API_BASE}/api/health`).then((r) => json<{ limits: Limits }>(r)).then((h) => h.limits);

export const getPresets = () => fetch(`${API_BASE}/api/presets`).then((r) => json<Preset[]>(r));

export const compileSop = (text: string) =>
  fetch(`${API_BASE}/api/sop/compile`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text }),
  }).then((r) => json<{ sop: CompiledSop; cached: boolean }>(r));

export const compileSopFile = (file: File) => {
  const fd = new FormData();
  fd.append("file", file);
  return fetch(`${API_BASE}/api/sop/compile-file`, { method: "POST", body: fd }).then((r) =>
    json<{ sop: CompiledSop; cached: boolean; text: string }>(r),
  );
};

export const startJob = (sop: CompiledSop, source: { presetId?: string; video?: File }) => {
  const fd = new FormData();
  fd.append("sop", JSON.stringify(sop));
  if (source.presetId) fd.append("preset_id", source.presetId);
  if (source.video) fd.append("video", source.video);
  return fetch(`${API_BASE}/api/jobs`, { method: "POST", body: fd }).then((r) => json<{ job_id: string }>(r));
};

export const getJob = (id: string) => fetch(`${API_BASE}/api/jobs/${id}`).then((r) => json<JobStatus>(r));

/** Poll a job until it finishes, reporting each stage. */
export async function waitForJob(id: string, onStage?: (stage: string | null) => void): Promise<JobResult> {
  for (;;) {
    const job = await getJob(id);
    onStage?.(job.stage);
    if (job.status === "done" && job.result) return job.result;
    if (job.status === "failed") throw new Error(job.error ?? "analysis failed");
    await new Promise((r) => setTimeout(r, 800));
  }
}

export const getTracks = (url: string) => fetch(media(url)).then((r) => json<Tracks>(r));

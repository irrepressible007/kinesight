// Builds a self-contained HTML QA report for one analysis: images are embedded, so the file
// opens offline, can be mailed to a line supervisor, and prints cleanly to PDF.
import { media } from "./api";
import { STATUS_TEXT } from "./status";
import type { JobResult } from "./types";

const esc = (s: string | number) =>
  String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]!);

const fmt = (sec: number) => `${sec.toFixed(1)} s`;

async function embed(path: string): Promise<string> {
  try {
    const blob = await (await fetch(media(path))).blob();
    return await new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(reader.result as string);
      reader.onerror = reject;
      reader.readAsDataURL(blob);
    });
  } catch {
    return media(path);
  }
}

// One lane per step on a shared seconds axis: green contacts met the minimum, amber did not.
function timelineSvg(result: JobResult): string {
  const steps = result.telemetry.detected_interactions;
  const duration = Math.max(result.telemetry.total_duration_sec, 0.1);
  const W = 760, left = 70, laneH = 26, gap = 14, top = 10;
  const x = (t: number) => left + ((W - left - 10) * t) / duration;
  const h = top + steps.length * (laneH + gap) + 24;
  const tick = duration > 60 ? 10 : duration > 20 ? 5 : 2;
  let svg = `<svg viewBox="0 0 ${W} ${h}" width="100%" role="img" aria-label="Contact timeline">`;
  steps.forEach((s, i) => {
    const y = top + i * (laneH + gap);
    svg += `<text x="0" y="${y + laneH / 2 + 4}" class="lane-label">Step ${s.step_number}</text>`;
    svg += `<rect x="${left}" y="${y}" width="${W - left - 10}" height="${laneH}" rx="4" class="lane"/>`;
    s.contact_intervals.forEach((iv, k) => {
      const w = Math.max(2, x(iv.end_sec) - x(iv.start_sec));
      svg += `<rect x="${x(iv.start_sec)}" y="${y + 4}" width="${w}" height="${laneH - 8}" rx="3" class="${iv.meets_min_duration ? "ok" : "short"}"/>`;
      if (w > 22) svg += `<text x="${x(iv.start_sec) + 4}" y="${y + laneH / 2 + 4}" class="bar-label">#${k + 1}</text>`;
    });
    result.verdict.defects
      .filter((d) => d.step_number === s.step_number)
      .forEach((d) => {
        svg += `<rect x="${x(d.timestamp_sec) - 2}" y="${y - 2}" width="4" height="${laneH + 4}" class="defect"/>`;
      });
  });
  const axisY = top + steps.length * (laneH + gap) + 4;
  for (let t = 0; t <= duration + 1e-6; t += tick) {
    svg += `<text x="${x(t)}" y="${axisY + 12}" class="tick" text-anchor="middle">${t}s</text>`;
  }
  return svg + "</svg>";
}

export async function buildReport(result: JobResult, sourceLabel: string): Promise<string> {
  const { verdict, telemetry, sop } = result;
  const tone = verdict.overall_status === "PASS" ? "pass" : verdict.overall_status === "FAIL" ? "fail" : "warn";
  const generated = new Date();

  const defects = await Promise.all(
    verdict.defects.map(async (d) => {
      const keyframes = await Promise.all(d.keyframe_paths.map(embed));
      const diagram = d.corrective_diagram_url ? await embed(d.corrective_diagram_url) : null;
      const auditor =
        d.auditor_confirmed === null
          ? "Auditor unavailable: deterministic finding only."
          : `Muse Spark 1.3 ${d.auditor_confirmed ? "confirmed a genuine defect" : "judged this a measurement artifact"}` +
            (d.auditor_confidence !== null ? ` (confidence ${Math.round(d.auditor_confidence * 100)}%).` : ".");
      return `
      <article class="defect-card">
        <div class="defect-head">
          <span class="sev">${esc(d.severity)}</span>
          <strong>Step ${d.step_number} · ${esc(STATUS_TEXT[d.status])}</strong>
          <span class="at">at t = ${d.timestamp_sec.toFixed(2)} s</span>
        </div>
        <p class="muted">${esc(auditor)}</p>
        <h4>Root cause</h4><p>${esc(d.root_cause_summary)}</p>
        <h4>Corrective action</h4><p>${esc(d.corrective_action)}</p>
        ${keyframes.length ? `<h4>Audited keyframes (before, at, after)</h4><div class="frames">${keyframes.map((k) => `<img src="${k}" alt="Keyframe with SAM 3.1 mask contours">`).join("")}</div>` : ""}
        ${diagram ? `<h4>Corrective work instruction (Muse Image)</h4><img class="diagram" src="${diagram}" alt="Corrective diagram">` : ""}
      </article>`;
    }),
  );

  const rows = telemetry.detected_interactions
    .map((s) => {
      const rule = sop.steps.find((r) => r.step_number === s.step_number);
      const contacts = s.contact_intervals
        .map((iv, k) => `#${k + 1} ${fmt(iv.start_sec)}–${fmt(iv.end_sec)} (${fmt(iv.duration_sec)}${iv.meets_min_duration ? "" : ", too short"})`)
        .join("<br>");
      return `<tr>
        <td>${s.step_number}</td>
        <td>${esc(s.description)}<div class="muted">${esc(s.actor)} ∩ ${esc(s.target)}, ≥ ${s.min_contact_sec} s × ${rule?.required_contacts ?? s.contacts_required}</div></td>
        <td class="${s.status === "PASS" ? "pass" : "fail"}">${esc(STATUS_TEXT[s.status])}</td>
        <td>${s.contacts_detected} / ${s.contacts_required}</td>
        <td class="small">${contacts || "none"}</td>
      </tr>`;
    })
    .join("");

  const timings = Object.entries(result.timings_ms)
    .map(([k, v]) => `<span>${esc(k)} ${v >= 1000 ? `${(v / 1000).toFixed(1)} s` : `${v.toFixed(0)} ms`}</span>`)
    .join(" · ");

  return `<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>KineSight QA report · ${esc(sop.sop_title)}</title>
<style>
  :root { --ink:#111827; --muted:#6b7280; --line:#e5e7eb; --pass:#059669; --fail:#dc2626; --warn:#d97706; --accent:#b7791f; }
  * { box-sizing: border-box; }
  body { margin: 0; background: #f3f4f6; color: var(--ink); font: 14px/1.5 system-ui, -apple-system, "Segoe UI", sans-serif; }
  main { max-width: 860px; margin: 24px auto; background: #fff; padding: 32px; border-radius: 12px; box-shadow: 0 1px 3px rgba(0,0,0,.08); }
  header { display: flex; justify-content: space-between; align-items: flex-start; gap: 16px; border-bottom: 2px solid var(--ink); padding-bottom: 12px; }
  h1 { margin: 0; font-size: 22px; } h2 { font-size: 16px; margin: 28px 0 10px; } h4 { margin: 12px 0 4px; font-size: 12px; text-transform: uppercase; letter-spacing: .06em; color: var(--muted); }
  p { margin: 0 0 6px; } .muted { color: var(--muted); font-size: 12px; } .small { font-size: 12px; }
  .brand { font-weight: 800; letter-spacing: -.01em; } .brand span { color: var(--accent); }
  button { font: inherit; padding: 8px 14px; border-radius: 8px; border: 1px solid var(--ink); background: var(--ink); color: #fff; cursor: pointer; }
  .summary { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 12px; margin-top: 20px; }
  .stat { border: 1px solid var(--line); border-radius: 10px; padding: 10px 12px; } .stat b { display: block; font-size: 22px; }
  .pass { color: var(--pass); } .fail { color: var(--fail); } .warn { color: var(--warn); }
  .verdict.pass { border-color: var(--pass); } .verdict.fail { border-color: var(--fail); } .verdict.warn { border-color: var(--warn); }
  table { width: 100%; border-collapse: collapse; } th, td { text-align: left; vertical-align: top; padding: 8px; border-bottom: 1px solid var(--line); } th { font-size: 12px; color: var(--muted); }
  svg .lane { fill: #f3f4f6; } svg .ok { fill: #34d399; } svg .short { fill: #fbbf24; } svg .defect { fill: var(--fail); }
  svg .lane-label { font-size: 12px; fill: var(--muted); } svg .bar-label { font-size: 10px; font-weight: 700; fill: #064e3b; } svg .tick { font-size: 10px; fill: var(--muted); }
  .legend { font-size: 12px; color: var(--muted); } .legend i { display: inline-block; width: 10px; height: 10px; border-radius: 2px; margin: 0 4px 0 10px; vertical-align: -1px; }
  .defect-card { border: 1px solid #fecaca; background: #fef2f2; border-radius: 10px; padding: 14px; margin-bottom: 14px; break-inside: avoid; }
  .defect-head { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; margin-bottom: 6px; } .at { margin-left: auto; color: var(--fail); font-weight: 600; }
  .sev { background: var(--fail); color: #fff; font-size: 11px; font-weight: 700; padding: 2px 6px; border-radius: 4px; }
  .frames { display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; } .frames img, .diagram { width: 100%; border-radius: 6px; border: 1px solid var(--line); }
  footer { margin-top: 28px; padding-top: 12px; border-top: 1px solid var(--line); color: var(--muted); font-size: 12px; }
  @media print { body { background: #fff; } main { box-shadow: none; margin: 0; max-width: none; padding: 0; } .no-print { display: none; } }
  @media (max-width: 600px) { main { padding: 18px; margin: 0; border-radius: 0; } .frames { grid-template-columns: 1fr; } }
</style></head>
<body><main>
  <header>
    <div>
      <div class="brand">Kine<span>Sight</span> · QA report</div>
      <h1>${esc(sop.sop_title)}</h1>
      <div class="muted">Footage: ${esc(sourceLabel)} · Generated ${esc(generated.toLocaleString())} · Job ${esc(result.job_id)}</div>
    </div>
    <button class="no-print" onclick="window.print()">Print / save as PDF</button>
  </header>

  <section class="summary">
    <div class="stat verdict ${tone}"><span class="muted">QA verdict</span><b class="${tone}">${esc(verdict.overall_status)}</b></div>
    <div class="stat"><span class="muted">Compliance</span><b class="${tone}">${verdict.compliance_score.toFixed(1)}%</b></div>
    <div class="stat"><span class="muted">Cycle time</span><b>${fmt(verdict.cycle_time_sec)}</b></div>
    <div class="stat"><span class="muted">Frames analyzed</span><b>${telemetry.total_frames}</b><span class="muted">at ${telemetry.fps_analyzed} fps</span></div>
  </section>

  <h2>Contact timeline</h2>
  ${timelineSvg(result)}
  <div class="legend"><i style="background:#34d399"></i>contact met the minimum<i style="background:#fbbf24"></i>too short<i style="background:#dc2626"></i>defect flagged</div>

  <h2>SOP steps</h2>
  <table><thead><tr><th>#</th><th>Step and rule</th><th>Status</th><th>Contacts</th><th>Measured contacts</th></tr></thead><tbody>${rows}</tbody></table>

  <h2>Defects</h2>
  ${defects.length ? defects.join("") : `<p class="pass">No defects: every step met its rule.</p>`}

  <h2>How this was measured</h2>
  <p class="small">SAM 3.1 segmented and tracked every tool and part from text prompts, frame by frame. A deterministic OpenCV/NumPy engine computed centroids, tool speed and dilated-mask contact to turn those masks into timed contact intervals; all counts and durations above come from that math. Muse Spark 1.3 compiled the SOP into these rules and audited only the flagged steps from their keyframes, and Muse Image drew the corrective work instruction.</p>
  <p class="muted">Pipeline timings of the original run: ${timings}</p>

  <footer>Generated by KineSight: sensorless visual telemetry and SOP compliance for assembly lines.</footer>
</main></body></html>`;
}

export async function downloadReport(result: JobResult, sourceLabel: string): Promise<void> {
  const html = await buildReport(result, sourceLabel);
  const d = new Date();
  const pad = (n: number) => String(n).padStart(2, "0");
  const stamp = `${d.getFullYear()}${pad(d.getMonth() + 1)}${pad(d.getDate())}-${pad(d.getHours())}${pad(d.getMinutes())}`;
  const slug = result.sop.sop_title.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "").slice(0, 40) || "cycle";
  const url = URL.createObjectURL(new Blob([html], { type: "text/html" }));
  const a = document.createElement("a");
  a.href = url;
  a.download = `kinesight-report-${slug}-${stamp}.html`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 10_000);
}

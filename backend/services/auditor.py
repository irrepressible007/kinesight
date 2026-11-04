"""Stage 4: keyframes around each anomaly, Muse Spark root-cause audit, Muse Image fix diagram."""

import json
import logging
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import cv2
import numpy as np

from schemas import AuditVerdict, CompiledSop, Defect, StepResult
from services.kinematics import KinematicResult
from services.meta_client import image_part, muse_image, spark_json
from services.rule_evaluator import Anomaly

log = logging.getLogger(__name__)

# BGR, matching the frontend palette order
PALETTE = [(80, 200, 255), (255, 170, 60), (120, 220, 120), (200, 120, 255), (90, 90, 255), (220, 220, 80)]

SYSTEM = """You are a senior manufacturing QA auditor. A deterministic vision pipeline (SAM 3.1 masks
plus OpenCV contact geometry) measured tool-to-part contacts on an assembly video and flagged a
possible violation of one SOP step. You get the SOP step, the measured telemetry, and three keyframes
(before, at, and after the flagged moment) with colored mask overlays and object labels.

Decide whether this is a genuine procedural defect or a measurement artifact (occlusion, a mask that
dropped out, an object outside the frame). The telemetry's timings and counts are ground truth for
WHEN and HOW MANY; never re-estimate them. Use the images to judge WHERE and WHY: name the specific
location (e.g. "top-right corner hole") and what is visibly wrong. Keep each text field to at most two
sentences. diagram_prompt must describe a clean top-down instructional diagram an image model can draw
that shows the corrected procedure or workstation layout for this exact defect."""

SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["is_genuine_defect", "confidence", "root_cause_summary", "corrective_action", "diagram_prompt"],
    "properties": {
        "is_genuine_defect": {"type": "boolean"},
        "confidence": {"type": "number"},
        "root_cause_summary": {"type": "string"},
        "corrective_action": {"type": "string"},
        "diagram_prompt": {"type": "string"},
    },
}

DIAGRAM_STYLE = (" Style: flat vector engineering work-instruction diagram, top-down view, white background, "
                 "navy and orange accents, numbered callouts, crisp legible labels, no photorealism.")

FALLBACK_ACTION = {
    "FAIL_MISSING": "Stop the unit and perform the skipped step before it leaves the station.",
    "FAIL_COUNT_SHORTFALL": "Return the unit to the station and complete the missing contacts; stage a pre-counted parts tray.",
    "FAIL_SHORT_DURATION": "Rework the affected contact and hold the tool for the full specified duration.",
    "FAIL_ORDER": "Rework the unit and follow the SOP sequence; add a sequence check at the station.",
}


def region(loc: tuple[float, float] | None) -> str:
    if loc is None:
        return "unknown position"
    x, y = loc
    col = "left" if x < 0.36 else "right" if x > 0.64 else "center"
    row = "top" if y < 0.36 else "bottom" if y > 0.64 else "middle"
    return "center of frame" if (row, col) == ("middle", "center") else f"{row}-{col} of frame"


def render_keyframes(video_path: Path, kin: KinematicResult, times: list[float], out_dir: Path,
                     stem: str) -> list[Path]:
    """Grab frames at the given times and draw the SAM mask contours over them."""
    out_dir.mkdir(parents=True, exist_ok=True)
    cap = cv2.VideoCapture(str(video_path))
    labels = list(kin.tracks)
    paths = []
    for i, t in enumerate(times):
        cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
        ok, frame = cap.read()
        if not ok:
            continue
        fh, fw = frame.shape[:2]
        fi = min(kin.total_frames - 1, max(0, int(round(t * kin.fps))))
        overlay = frame.copy()
        for li, lb in enumerate(labels):
            color = PALETTE[li % len(PALETTE)]
            entry = kin.tracks[lb][fi]
            for poly in entry["poly"]:
                pts = (np.array(poly).reshape(-1, 2) * (fw, fh)).astype(np.int32)
                cv2.fillPoly(overlay, [pts], color)
                cv2.polylines(frame, [pts], True, color, 3, cv2.LINE_AA)
            if entry["c"]:
                cx, cy = int(entry["c"][0] * fw), int(entry["c"][1] * fh)
                cv2.putText(frame, lb, (cx + 8, cy), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 0, 0), 5, cv2.LINE_AA)
                cv2.putText(frame, lb, (cx + 8, cy), cv2.FONT_HERSHEY_SIMPLEX, 0.9, color, 2, cv2.LINE_AA)
        frame = cv2.addWeighted(overlay, 0.25, frame, 0.75, 0)
        tag = f"t = {t:.2f}s"
        cv2.putText(frame, tag, (20, 44), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0, 0, 0), 6, cv2.LINE_AA)
        cv2.putText(frame, tag, (20, 44), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (255, 255, 255), 2, cv2.LINE_AA)
        if fw > 960:
            frame = cv2.resize(frame, (960, int(fh * 960 / fw)), interpolation=cv2.INTER_AREA)
        p = out_dir / f"{stem}_{i}.jpg"
        cv2.imwrite(str(p), frame, [cv2.IMWRITE_JPEG_QUALITY, 88])
        paths.append(p)
    cap.release()
    return paths


def _audit_one(anomaly: Anomaly, step: StepResult, sop: CompiledSop, kin: KinematicResult,
               video_path: Path, out_dir: Path, url_of, duration: float) -> Defect:
    ts = anomaly.timestamp_sec
    times = [max(0.0, ts - 1.5), min(ts, duration - 0.05), min(duration - 0.05, ts + 1.5)]
    stem = f"step{step.step_number}"
    keyframes = render_keyframes(video_path, kin, times, out_dir / "keyframes", stem)

    contacts = [
        {"start_sec": iv.start_sec, "end_sec": iv.end_sec, "duration_sec": iv.duration_sec,
         "meets_min_duration": iv.meets_min_duration, "where": region(iv.location)}
        for iv in step.contact_intervals
    ]
    brief = {
        "sop_title": sop.sop_title,
        "step": {"number": step.step_number, "description": step.description, "actor": step.actor,
                 "target": step.target, "min_contact_sec": step.min_contact_sec,
                 "required_contacts": step.contacts_required},
        "measured": {"status": anomaly.status, "contacts_meeting_minimum": step.contacts_detected,
                     "contacts": contacts, "flagged_at_sec": ts, "cycle_time_sec": round(duration, 2)},
        "engine_summary": anomaly.summary,
        "keyframe_times_sec": [round(t, 2) for t in times],
    }

    defect = Defect(
        step_number=step.step_number,
        status=anomaly.status,
        severity=anomaly.severity,
        timestamp_sec=ts,
        keyframe_paths=[url_of(p) for p in keyframes],
        root_cause_summary=anomaly.summary,
        corrective_action=FALLBACK_ACTION[anomaly.status],
    )
    try:
        content = [{"type": "text", "text": "Audit this flagged step.\n" + json.dumps(brief, indent=1)}]
        content += [image_part(p) for p in keyframes]
        verdict = spark_json(SYSTEM, content, "qa_audit", SCHEMA)
    except Exception as e:  # the deterministic finding stands even if the auditor is unreachable
        log.warning("auditor failed for step %s: %s", step.step_number, e)
        return defect

    defect.root_cause_summary = verdict["root_cause_summary"]
    defect.corrective_action = verdict["corrective_action"]
    defect.auditor_confirmed = bool(verdict["is_genuine_defect"])
    defect.auditor_confidence = round(float(verdict["confidence"]), 2)
    if defect.auditor_confirmed:
        try:
            diagram = muse_image(verdict["diagram_prompt"] + DIAGRAM_STYLE, out_dir / "diagrams" / stem)
            defect.corrective_diagram_url = url_of(diagram)
        except Exception as e:
            log.warning("diagram failed for step %s: %s", step.step_number, e)
    return defect


def audit(sop: CompiledSop, steps: list[StepResult], anomalies: list[Anomaly], score: float,
          kin: KinematicResult, video_path: Path, out_dir: Path, url_of) -> AuditVerdict:
    duration = kin.total_frames / kin.fps
    by_number = {s.step_number: s for s in steps}
    with ThreadPoolExecutor(max_workers=4) as pool:
        defects = list(pool.map(
            lambda a: _audit_one(a, by_number[a.step_number], sop, kin, video_path, out_dir, url_of, duration),
            anomalies,
        ))
    if not defects:
        status = "PASS"
    elif all(d.auditor_confirmed is False for d in defects):
        status = "REVIEW"  # every flag was judged a measurement artifact; a human should look
    else:
        status = "FAIL"
    return AuditVerdict(overall_status=status, cycle_time_sec=round(duration, 2),
                        compliance_score=score, defects=defects)

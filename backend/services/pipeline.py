"""End-to-end run: SAM tracking -> kinematics -> rule evaluation -> audit, with idempotent caching.

A result is keyed by (video_sha256, sop_sha256, analysis settings). Re-running the same
inputs returns the stored result without touching the network.
"""

import hashlib
import json
import subprocess
import time
from pathlib import Path
from typing import Callable

import config
from schemas import CompiledSop, JobResult, Telemetry
from services import auditor, kinematics, rule_evaluator, sam_tracker

# Always segmented for the overlay even when no rule uses it.
CONTEXT_PROMPTS = ["hand"]

Progress = Callable[[str], None]


def prompts_for(sop: CompiledSop) -> list[str]:
    return list(dict.fromkeys(sop.sam_prompts + CONTEXT_PROMPTS))


def needs_segmentation(work_dir: Path, sop: CompiledSop) -> bool:
    """True when some prompt has no cached SAM output, so a run would call SAM 3.1."""
    return any(not sam_tracker.raw_path(work_dir, p).exists() for p in prompts_for(sop))


def settings_fingerprint() -> str:
    keys = ["FPS_RATE", "ANALYSIS_WIDTH", "DILATE_FRAC", "OVERLAP_FRAC", "STATIONARY_SPEED",
            "SPEED_WINDOW_SEC", "MAX_GAP_SEC", "MIN_INTERVAL_SEC", "SPARK_MODEL", "IMAGE_MODEL"]
    blob = json.dumps({k: getattr(config, k) for k in keys}, sort_keys=True)
    return hashlib.sha256(blob.encode()).hexdigest()[:8]


def sop_sha(sop: CompiledSop) -> str:
    return hashlib.sha256(sop.model_dump_json().encode()).hexdigest()


def result_key(sop: CompiledSop) -> str:
    return f"{sop_sha(sop)[:12]}_{settings_fingerprint()}"


def make_playback_video(src: Path, dst: Path) -> Path:
    """Browser-safe H.264 copy; the analysis video is derived from it so both share a timeline."""
    if not dst.exists():
        subprocess.run(
            ["ffmpeg", "-v", "error", "-y", "-i", str(src),
             "-vf", f"scale='min({config.ANALYSIS_WIDTH},iw)':-2", "-an", "-c:v", "libx264",
             "-preset", "veryfast", "-crf", "23", "-threads", config.FFMPEG_THREADS,
             "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(dst)],
            check=True,
        )
    return dst


def cached_result(work_dir: Path, sop: CompiledSop) -> JobResult | None:
    path = work_dir / f"result_{result_key(sop)}.json"
    if not path.exists():
        return None
    result = JobResult.model_validate_json(path.read_text(encoding="utf-8"))
    result.cached = True
    return result


def run(job_id: str, video_path: Path, sop: CompiledSop, work_dir: Path, url_prefix: str,
        video_url: str, progress: Progress = lambda _: None) -> JobResult:
    """Analyze one video against one compiled SOP. work_dir holds every artifact."""
    hit = cached_result(work_dir, sop)
    if hit:
        hit.job_id = job_id
        return hit

    def url_of(p: Path) -> str:
        return f"{url_prefix}/{p.relative_to(work_dir).as_posix()}"

    timings: dict[str, float] = {}
    t = time.perf_counter()

    def lap(name: str) -> None:
        nonlocal t
        now = time.perf_counter()
        timings[name] = round((now - t) * 1000, 1)
        t = now

    progress("Preparing video")
    analysis = sam_tracker.make_analysis_video(video_path, work_dir / "analysis.mp4")
    width, height, fps, total = sam_tracker.probe(analysis)
    lap("prepare")

    prompts = prompts_for(sop)
    progress(f"Segmenting {len(prompts)} objects with SAM 3.1")
    tracks = sam_tracker.track_prompts(analysis, prompts, work_dir,
                                       on_progress=lambda p: progress(f"SAM 3.1 finished '{p}'"))
    lap("sam_tracking")

    progress("Computing centroids, velocities and contacts")
    pairs = list(dict.fromkeys((s.actor_object, s.target_object) for s in sop.steps))
    kin = kinematics.analyze(tracks, width, height, fps, total, pairs)
    lap("kinematics")

    duration = total / fps
    steps, anomalies, score = rule_evaluator.evaluate(sop, kin.intervals, duration)
    telemetry = Telemetry(
        video_id=video_path.parent.name, fps_analyzed=fps, total_frames=total,
        total_duration_sec=round(duration, 2), frame_width=width, frame_height=height,
        detected_interactions=steps,
    )
    lap("rules")

    progress(f"Auditing {len(anomalies)} flagged step(s) with Muse Spark" if anomalies else "No violations found")
    verdict = auditor.audit(sop, steps, anomalies, score, kin, video_path, work_dir, url_of)
    lap("audit")

    key = result_key(sop)
    tracks_path = work_dir / f"tracks_{key}.json"
    tracks_path.write_text(json.dumps({
        "fps": fps, "width": width, "height": height, "total_frames": total,
        "labels": list(kin.tracks),
        "tracks": kin.tracks,
        "speed": kin.speed,
        "contact": {f"{a}|{b}": kin.contact[(a, b)].astype(int).tolist() for a, b in pairs},
        "stationary_speed": config.STATIONARY_SPEED,
    }, separators=(",", ":")), encoding="utf-8")

    result = JobResult(job_id=job_id, video_url=video_url, tracks_url=url_of(tracks_path), sop=sop,
                       telemetry=telemetry, verdict=verdict, timings_ms=timings)
    (work_dir / f"result_{key}.json").write_text(result.model_dump_json(indent=1), encoding="utf-8")
    return result

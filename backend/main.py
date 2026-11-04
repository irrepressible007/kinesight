"""KineSight API.

    uvicorn main:app --reload --port 8000   (run from backend/)
"""

import hashlib
import json
import logging
import subprocess
import tempfile
import threading
import uuid
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ValidationError

import config
import database
from schemas import CompiledSop, JobResult
from services import pipeline, sop_compiler
from services.sam_tracker import file_sha256

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("kinesight")

app = FastAPI(title="KineSight", version="1.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.mount("/presets", StaticFiles(directory=config.PRESETS_DIR), name="presets")
app.mount("/cache", StaticFiles(directory=config.CACHE_DIR), name="cache")

SOP_CACHE = config.CACHE_DIR / "sop"
SOP_CACHE.mkdir(exist_ok=True)
VIDEO_TYPES = {".mp4", ".mov", ".m4v", ".webm", ".avi", ".mkv"}
BUDGETS = {"video": config.DAILY_VIDEO_JOBS, "rules": config.DAILY_RULE_JOBS, "compile": config.DAILY_COMPILES}
BUDGET_SPENT = {
    "video": "The public demo's daily budget for new video analyses is used up.",
    "rules": "The public demo's daily budget for re-running presets with edited rules is used up.",
    "compile": "The public demo's daily budget for new SOP compiles is used up.",
}


REPLAY_ONLY = ("This server replays recorded results and makes no live model calls (no META_API_KEY). "
               "Run KineSight with a key to compile new SOPs, edit rules or analyze your own video.")


def spend(kind: str) -> None:
    if not config.LIVE_ANALYSIS:
        raise HTTPException(403, REPLAY_ONLY)
    if not database.take_quota(kind, BUDGETS[kind]):
        raise HTTPException(429, f"{BUDGET_SPENT[kind]} The presets still replay; run KineSight locally for unlimited use.")


@app.get("/api/health")
def health():
    return {
        "ok": True,
        "meta_api_key": bool(config.META_API_KEY),
        "settings": pipeline.settings_fingerprint(),
        "limits": {
            "live": config.LIVE_ANALYSIS,
            "max_video_sec": config.MAX_VIDEO_SEC or None,
            "max_upload_mb": config.MAX_UPLOAD_MB or None,
            **{f"{k}_left": database.quota_left(k, n) for k, n in BUDGETS.items()},
        },
    }


# ---- presets ---------------------------------------------------------------


def load_presets() -> list[dict]:
    presets = []
    for f in sorted(config.PRESETS_DIR.glob("*/preset.json")):
        p = json.loads(f.read_text(encoding="utf-8"))
        p["id"] = f.parent.name
        p["video_url"] = f"/presets/{p['id']}/video.mp4"
        p["sop_text"] = (f.parent / p.pop("sop_text_file")).read_text(encoding="utf-8")
        presets.append(p)
    return presets


@app.get("/api/presets")
def presets():
    return load_presets()


def _seed_sop_cache() -> None:
    """Each preset's rules were compiled live from its SOP text; register them in the compile
    cache so recompiling a preset's text is instant even on a fresh deployment."""
    for p in load_presets():
        path = SOP_CACHE / f"{hashlib.sha256(p['sop_text'].strip().encode()).hexdigest()[:16]}.json"
        if not path.exists():
            path.write_text(CompiledSop.model_validate(p["sop"]).model_dump_json(indent=1), encoding="utf-8")


# ---- stage 1: SOP compiler ---------------------------------------------------


class CompileRequest(BaseModel):
    text: str


def _compile_cached(text: str) -> dict:
    key = hashlib.sha256(text.strip().encode()).hexdigest()[:16]
    path = SOP_CACHE / f"{key}.json"
    if path.exists():
        return {"sop": json.loads(path.read_text(encoding="utf-8")), "cached": True}
    spend("compile")
    try:
        sop = sop_compiler.compile_sop(text)
    except (ValidationError, ValueError) as e:
        raise HTTPException(422, f"Muse Spark returned rules that failed validation: {e}") from e
    except Exception as e:
        log.exception("SOP compile failed")
        raise HTTPException(502, f"Muse Spark request failed: {e}") from e
    path.write_text(sop.model_dump_json(indent=1), encoding="utf-8")
    return {"sop": sop.model_dump(), "cached": False}


@app.post("/api/sop/compile")
def compile_text(req: CompileRequest):
    if not req.text.strip():
        raise HTTPException(400, "SOP text is empty")
    return _compile_cached(req.text)


@app.post("/api/sop/compile-file")
async def compile_file(file: UploadFile = File(...)):
    data = await file.read()
    text = sop_compiler.pdf_to_text(data) if file.filename.lower().endswith(".pdf") else data.decode("utf-8", "ignore")
    if not text.strip():
        raise HTTPException(400, "No text could be extracted from the file")
    return {**_compile_cached(text), "text": text}


# ---- stages 2-4: analysis jobs -------------------------------------------------

_results: dict[str, JobResult] = {}
_workers = threading.BoundedSemaphore(max(1, config.MAX_CONCURRENT_JOBS))


def _run_job(job_id: str, source: Path, video: Path, sop: CompiledSop, work_dir: Path, url_prefix: str,
             video_url: str):
    database.update_job(job_id, stage="Waiting for a free worker")
    try:
        with _workers:
            database.update_job(job_id, status="running", stage="Preparing video")
            # Encoded here rather than in the request: on a slow host it takes minutes.
            if not video.exists():
                pipeline.make_playback_video(source, video)
            result = pipeline.run(job_id, video, sop, work_dir, url_prefix, video_url,
                                  progress=lambda stage: database.update_job(job_id, stage=stage))
        _results[job_id] = result
        database.update_job(job_id, status="done", stage="Done")
    except Exception as e:
        log.exception("job %s failed", job_id)
        database.update_job(job_id, status="failed", error=str(e)[:1000])


@app.post("/api/jobs")
def create_job(sop: str = Form(...), preset_id: str | None = Form(None), video: UploadFile | None = File(None)):
    try:
        compiled = CompiledSop.model_validate_json(sop)
    except ValidationError as e:
        raise HTTPException(422, f"Invalid SOP rules: {e}") from e

    if preset_id:
        preset_dir = config.PRESETS_DIR / preset_id
        source = preset_dir / "video.mp4"
        if not source.exists():
            raise HTTPException(404, f"Unknown preset '{preset_id}'")
        work_dir, url_prefix = preset_dir / "cache", f"/presets/{preset_id}/cache"
        video_path, video_url = source, f"/presets/{preset_id}/video.mp4"
        video_sha = preset_id
    elif video is not None:
        if not config.LIVE_ANALYSIS:
            raise HTTPException(403, REPLAY_ONLY)
        suffix = Path(video.filename or "").suffix.lower()
        if suffix not in VIDEO_TYPES:
            raise HTTPException(415, f"Unsupported video type '{suffix}'")
        tmp_path = _save_upload(video, suffix)
        video_sha = file_sha256(tmp_path)
        work_dir = config.CACHE_DIR / video_sha[:16]
        work_dir.mkdir(exist_ok=True)
        source = work_dir / f"source{suffix}"
        if source.exists():
            tmp_path.unlink()
        else:
            tmp_path.replace(source)
        video_path = work_dir / "video.mp4"
        url_prefix, video_url = f"/cache/{video_sha[:16]}", f"/cache/{video_sha[:16]}/video.mp4"
    else:
        raise HTTPException(400, "Provide a preset_id or a video file")

    hit = pipeline.cached_result(work_dir, compiled)
    if not hit and preset_id and config.MAX_VIDEO_SEC and pipeline.needs_segmentation(work_dir, compiled):
        # Without cached SAM output the preset is segmented from scratch; hold it to the clip cap.
        duration = _duration(source)
        if duration > config.MAX_VIDEO_SEC:
            raise HTTPException(413, f"These rules need a fresh SAM 3.1 pass over this preset's {duration:.0f}s clip, "
                                     f"and this server analyzes clips up to {config.MAX_VIDEO_SEC:.0f}s. Upload a "
                                     "shorter clip, or run KineSight locally.")
    if not hit:
        spend("rules" if preset_id else "video")
    elif not video_path.exists():
        pipeline.make_playback_video(source, video_path)

    job_id = uuid.uuid4().hex[:12]
    database.create_job(job_id, video_sha, pipeline.sop_sha(compiled))
    if hit:
        hit.job_id = job_id
        _results[job_id] = hit
        database.update_job(job_id, status="done", stage="Served from cache")
    else:
        threading.Thread(target=_run_job, args=(job_id, source, video_path, compiled, work_dir, url_prefix, video_url),
                         daemon=True).start()
    return {"job_id": job_id}


def _save_upload(video: UploadFile, suffix: str) -> Path:
    """Stream an upload to disk, enforcing the size and duration caps."""
    max_bytes = config.MAX_UPLOAD_MB * 1024 * 1024
    size = 0
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix, dir=config.CACHE_DIR) as tmp:
        while chunk := video.file.read(1 << 20):
            size += len(chunk)
            if max_bytes and size > max_bytes:
                break
            tmp.write(chunk)
    path = Path(tmp.name)
    if max_bytes and size > max_bytes:
        path.unlink()
        raise HTTPException(413, f"Video is larger than {config.MAX_UPLOAD_MB:.0f} MB")
    if config.MAX_VIDEO_SEC:
        try:
            duration = _duration(path)
        except (subprocess.CalledProcessError, ValueError):
            path.unlink()
            raise HTTPException(415, "Could not read that video file") from None
        if duration > config.MAX_VIDEO_SEC:
            path.unlink()
            raise HTTPException(413, f"Video is {duration:.0f}s long; the public demo accepts up to {config.MAX_VIDEO_SEC:.0f}s")
    return path


def _duration(path: Path) -> float:
    return float(subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True, check=True,
    ).stdout.strip())


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str):
    job = database.get_job(job_id)
    if not job:
        raise HTTPException(404, "Unknown job")
    result = _results.get(job_id)
    return {
        "job_id": job_id,
        "status": job["status"],
        "stage": job["stage"],
        "error": job["error"],
        "result": result.model_dump() if result else None,
    }


_seed_sop_cache()

# Registered last so the API routes and media mounts above take precedence.
if config.FRONTEND_DIR.is_dir():
    app.mount("/", StaticFiles(directory=config.FRONTEND_DIR, html=True), name="frontend")

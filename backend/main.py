"""KineSight API.

    uvicorn main:app --reload --port 8000   (run from backend/)
"""

import hashlib
import json
import logging
import shutil
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


@app.get("/api/health")
def health():
    return {"ok": True, "meta_api_key": bool(config.META_API_KEY), "settings": pipeline.settings_fingerprint()}


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


# ---- stage 1: SOP compiler ---------------------------------------------------


class CompileRequest(BaseModel):
    text: str


def _compile_cached(text: str) -> dict:
    key = hashlib.sha256(text.strip().encode()).hexdigest()[:16]
    path = SOP_CACHE / f"{key}.json"
    if path.exists():
        return {"sop": json.loads(path.read_text(encoding="utf-8")), "cached": True}
    try:
        sop = sop_compiler.compile_sop(text)
    except (ValidationError, ValueError) as e:
        raise HTTPException(422, f"Muse Spark returned rules that failed validation: {e}") from e
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


def _run_job(job_id: str, video: Path, sop: CompiledSop, work_dir: Path, url_prefix: str, video_url: str):
    database.update_job(job_id, status="running")
    try:
        result = pipeline.run(job_id, video, sop, work_dir, url_prefix, video_url,
                              progress=lambda stage: database.update_job(job_id, stage=stage))
        _results[job_id] = result
        database.update_job(job_id, status="done", stage="Done")
    except Exception as e:
        log.exception("job %s failed", job_id)
        database.update_job(job_id, status="failed", error=str(e)[:1000])


@app.post("/api/jobs")
async def create_job(sop: str = Form(...), preset_id: str | None = Form(None), video: UploadFile | None = File(None)):
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
        suffix = Path(video.filename or "").suffix.lower()
        if suffix not in VIDEO_TYPES:
            raise HTTPException(415, f"Unsupported video type '{suffix}'")
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix, dir=config.CACHE_DIR) as tmp:
            shutil.copyfileobj(video.file, tmp)
        tmp_path = Path(tmp.name)
        video_sha = file_sha256(tmp_path)
        work_dir = config.CACHE_DIR / video_sha[:16]
        work_dir.mkdir(exist_ok=True)
        source = work_dir / f"source{suffix}"
        if source.exists():
            tmp_path.unlink()
        else:
            tmp_path.replace(source)
        video_path = pipeline.make_playback_video(source, work_dir / "video.mp4")
        url_prefix, video_url = f"/cache/{video_sha[:16]}", f"/cache/{video_sha[:16]}/video.mp4"
    else:
        raise HTTPException(400, "Provide a preset_id or a video file")

    job_id = uuid.uuid4().hex[:12]
    database.create_job(job_id, video_sha, pipeline.sop_sha(compiled))

    hit = pipeline.cached_result(work_dir, compiled)
    if hit:
        hit.job_id = job_id
        _results[job_id] = hit
        database.update_job(job_id, status="done", stage="Served from cache")
    else:
        threading.Thread(target=_run_job, args=(job_id, video_path, compiled, work_dir, url_prefix, video_url),
                         daemon=True).start()
    return {"job_id": job_id}


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

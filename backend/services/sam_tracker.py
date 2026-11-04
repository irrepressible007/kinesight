"""SAM 3.1 video segmentation over the Meta Model API.

Each concept prompt is one streamed /responses call on an uploaded video. The raw
output text is cached per (video, prompt) so re-runs and SOP edits never re-bill SAM.
"""

import hashlib
import json
import re
import subprocess
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

import cv2
import httpx
import numpy as np
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

import config

_RETRYABLE = (httpx.TransportError, httpx.HTTPStatusError)
DECODER = config.BACKEND_DIR / "sam_decoder" / "decode.mjs"


@dataclass
class Instance:
    """One segmented object in one frame. The mask covers only its box, at frame scale."""

    object_id: str
    left: int
    top: int
    mask: np.ndarray  # uint8 {0,1}, shape (box_h, box_w)


# frame index -> instances of one prompt in that frame
PromptTrack = dict[int, list[Instance]]


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def probe(path: Path) -> tuple[int, int, float, int]:
    """Return (width, height, fps, frame_count) for a video."""
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-count_packets",
         "-show_entries", "stream=width,height,r_frame_rate,nb_read_packets", "-of", "json", str(path)],
        capture_output=True, text=True, check=True,
    ).stdout
    s = json.loads(out)["streams"][0]
    num, den = s["r_frame_rate"].split("/")
    return int(s["width"]), int(s["height"]), float(num) / float(den), int(s["nb_read_packets"])


def make_analysis_video(src: Path, dst: Path, fps: float = config.FPS_RATE) -> Path:
    """Resample to the analysis frame rate and width as H.264, which SAM accepts."""
    if dst.exists():
        return dst
    dst.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-i", str(src),
         "-vf", f"fps={fps},scale='min({config.ANALYSIS_WIDTH},iw)':-2",
         "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
         "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(dst)],
        check=True,
    )
    return dst


def _headers() -> dict[str, str]:
    if not config.META_API_KEY:
        raise RuntimeError("META_API_KEY is not set in .env")
    return {"Authorization": f"Bearer {config.META_API_KEY}"}


@retry(retry=retry_if_exception_type(_RETRYABLE), wait=wait_exponential(min=2, max=20), stop=stop_after_attempt(4))
def upload_video(path: Path) -> str:
    with open(path, "rb") as f:
        r = httpx.post(
            f"{config.META_BASE_URL}/files",
            headers=_headers(),
            files={"file": (path.name, f, "video/mp4")},
            data={"purpose": "user_data"},
            timeout=300,
        )
    r.raise_for_status()
    return r.json()["id"]


@retry(retry=retry_if_exception_type(_RETRYABLE), wait=wait_exponential(min=2, max=30), stop=stop_after_attempt(4))
def segment_video(file_id: str, prompt: str) -> str:
    """Run one concept prompt over an uploaded video and return SAM's raw output text."""
    body = {
        "model": config.SAM_MODEL,
        "stream": True,
        "metadata": {"include_confidence": "true"},
        "input": [{
            "type": "message",
            "role": "user",
            "content": [
                {"type": "input_text", "text": prompt},
                {"type": "input_video", "file_id": file_id},
            ],
        }],
    }
    parts: list[str] = []
    final: str | None = None
    with httpx.stream("POST", f"{config.META_BASE_URL}/responses", headers=_headers(), json=body, timeout=900) as r:
        if r.status_code >= 400:
            r.read()
            if r.status_code in (429,) or r.status_code >= 500:
                r.raise_for_status()
            raise RuntimeError(f"SAM request failed ({r.status_code}): {r.text[:500]}")
        for line in r.iter_lines():
            if not line.startswith("data: {"):
                continue
            event = json.loads(line[6:])
            kind = event.get("type")
            if kind == "response.output_text.delta":
                parts.append(event["delta"])
            elif kind == "response.output_text.done":
                final = event["text"]
            elif kind in ("response.failed", "error"):
                raise RuntimeError(f"SAM stream failed: {json.dumps(event)[:500]}")
    return final if final is not None else "".join(parts)


def load_track(raw_path: Path) -> PromptTrack:
    """Decode a cached raw SAM output into per-frame instances.

    Decoding runs through Meta's TypeScript parser (sam_decoder/decode.mjs): the Python
    parser decodes masks pixel by pixel and takes minutes per prompt on a full video.
    """
    prefix = raw_path.with_suffix(".dec")
    index_path, bin_path = prefix.with_suffix(".dec.json"), prefix.with_suffix(".dec.bin")
    if not (index_path.exists() and bin_path.exists()):
        subprocess.run(["node", str(DECODER), str(raw_path), str(prefix)], check=True, capture_output=True)
    records = json.loads(index_path.read_text())["records"]
    buf = np.fromfile(bin_path, dtype=np.uint8)
    track: PromptTrack = {}
    for r in records:
        n = r["w"] * r["h"]
        mask = np.unpackbits(buf[r["o"]: r["o"] + (n + 7) // 8])[:n].reshape(r["h"], r["w"])
        # Large masks are downscaled by SAM; stretch the raster back over its box.
        box_w, box_h = r["r"] - r["l"], r["b"] - r["t"]
        if box_w > 0 and box_h > 0 and (box_w, box_h) != (r["w"], r["h"]):
            mask = cv2.resize(mask, (box_w, box_h), interpolation=cv2.INTER_NEAREST)
        track.setdefault(r["f"], []).append(Instance(r["id"], r["l"], r["t"], mask))
    return track


def _slug(prompt: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", prompt.lower()).strip("_")


def track_prompts(analysis_video: Path, prompts: list[str], cache_dir: Path,
                  on_progress=None) -> dict[str, PromptTrack]:
    """Segment every prompt, reusing cached SAM output where present."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    paths = {p: cache_dir / f"sam_{_slug(p)}.txt" for p in prompts}
    missing = [p for p in prompts if not paths[p].exists()]

    if missing:
        file_id = upload_video(analysis_video)

        def run(p: str) -> None:
            paths[p].write_text(segment_video(file_id, p), encoding="utf-8")
            if on_progress:
                on_progress(p)

        with ThreadPoolExecutor(max_workers=min(4, len(missing))) as pool:
            list(pool.map(run, missing))

    with ThreadPoolExecutor(max_workers=len(prompts)) as pool:
        return dict(zip(prompts, pool.map(load_track, paths.values())))

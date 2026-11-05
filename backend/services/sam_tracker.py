"""SAM 3.1 video segmentation over the Meta Model API.

Each concept prompt is one streamed /responses call on an uploaded video. The raw
output text is cached per (video, prompt) so re-runs and SOP edits never re-bill SAM.
"""

import hashlib
import json
import re
import subprocess
from collections.abc import Callable, Iterator, Mapping
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
PromptTrack = Mapping[int, list[Instance]]


class PackedTrack(Mapping[int, list[Instance]]):
    """A prompt's instances, unpacked from the decoder's bit-packed masks only when a frame
    is read. Unpacked up front, a clip where a large part fills the frame needs hundreds
    of MB, more than a small host has."""

    def __init__(self, records: list[dict], buf: np.ndarray):
        self._buf = buf
        self._frames: dict[int, list[dict]] = {}
        for r in records:
            self._frames.setdefault(r["f"], []).append(r)

    def __getitem__(self, frame: int) -> list[Instance]:
        return [self._instance(r) for r in self._frames[frame]]

    def __iter__(self) -> Iterator[int]:
        return iter(self._frames)

    def __len__(self) -> int:
        return len(self._frames)

    def _instance(self, r: dict) -> Instance:
        n = r["w"] * r["h"]
        mask = np.unpackbits(self._buf[r["o"]: r["o"] + (n + 7) // 8], count=n).reshape(r["h"], r["w"])
        # Large masks are downscaled by SAM; stretch the raster back over its box.
        box_w, box_h = r["r"] - r["l"], r["b"] - r["t"]
        if box_w > 0 and box_h > 0 and (box_w, box_h) != (r["w"], r["h"]):
            mask = cv2.resize(mask, (box_w, box_h), interpolation=cv2.INTER_NEAREST)
        return Instance(r["id"], r["l"], r["t"], mask)


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


def make_analysis_video(src: Path, dst: Path, fps: float = config.FPS_RATE, width: int = config.ANALYSIS_WIDTH) -> Path:
    """Resample to the analysis frame rate and width as H.264, which SAM accepts."""
    if dst.exists():
        return dst
    dst.parent.mkdir(parents=True, exist_ok=True)
    # Encode beside the target and rename on success, so an interrupted encode is never reused.
    part = dst.with_name(f"{dst.stem}.part{dst.suffix}")
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-i", str(src),
         "-vf", f"fps={fps},scale='min({width},iw)':-2",
         "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-threads", config.FFMPEG_THREADS,
         "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(part)],
        check=True,
    )
    part.replace(dst)
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
def segment_video(file_id: str, prompt: str, out_path: Path) -> None:
    """Run one concept prompt over an uploaded video and save SAM's raw output text.

    The text runs to tens of MB for a large part, and the closing events repeat all of it,
    so deltas go straight to disk and only the events that matter are parsed.
    """
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
    part = out_path.with_suffix(".part")
    wrote = False
    with httpx.stream("POST", f"{config.META_BASE_URL}/responses", headers=_headers(), json=body,
                      timeout=900) as r, open(part, "w", encoding="utf-8") as out:
        if r.status_code >= 400:
            r.read()
            if r.status_code in (429,) or r.status_code >= 500:
                r.raise_for_status()
            raise RuntimeError(f"SAM request failed ({r.status_code}): {r.text[:500]}")
        def wanted(kind: str | None) -> bool:
            return kind in _ALWAYS_PARSED or (kind == _DONE and not wrote)

        for kind, data in _sse(r, wanted):
            if not data.startswith("{"):
                continue
            if kind is None:  # no event line; fall back to the type inside the payload
                kind = json.loads(data).get("type")
            if kind == _DELTA:
                out.write(json.loads(data)["delta"])
                wrote = True
            elif kind == _DONE and not wrote:
                out.write(json.loads(data)["text"])
            elif kind in ("response.failed", "error"):
                raise RuntimeError(f"SAM stream failed: {data[:500]}")
    part.replace(out_path)


_DELTA, _DONE = "response.output_text.delta", "response.output_text.done"
_ALWAYS_PARSED = {_DELTA, "response.failed", "error", None}


def _sse(response: httpx.Response, wanted: Callable[[str | None], bool]) -> Iterator[tuple[str | None, str]]:
    """Yield (event, data) for server-sent events that `wanted` accepts. Data lines of other
    events are dropped as they stream in, never buffered whole: SAM's closing events repeat
    the entire output, which for a minute-long clip of a large part is tens of MB."""
    event: str | None = None
    line, skipping = bytearray(), False
    for chunk in response.iter_bytes():
        start = 0
        while start <= len(chunk):
            end = chunk.find(b"\n", start)
            if not skipping:
                line += chunk[start:] if end < 0 else chunk[start:end]
                if line.startswith(b"data:") and not wanted(event):
                    skipping = True
                    line.clear()
            if end < 0:
                break
            if not skipping:
                text = line.decode("utf-8").rstrip("\r")
                if text.startswith("event:"):
                    event = text[6:].strip()
                elif text.startswith("data:"):
                    yield event, text[5:].lstrip()
                elif not text:
                    event = None
            line.clear()
            skipping = False
            start = end + 1


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
    # Memory-mapped: the OS pages masks in as frames are read and can drop them under pressure.
    buf = np.memmap(bin_path, dtype=np.uint8, mode="r") if bin_path.stat().st_size else np.zeros(0, np.uint8)
    return PackedTrack(records, buf)


def _slug(prompt: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", prompt.lower()).strip("_")


def raw_path(cache_dir: Path, prompt: str) -> Path:
    """Where a prompt's raw SAM output is cached."""
    return cache_dir / f"sam_{_slug(prompt)}.txt"


def track_prompts(analysis_video: Path, prompts: list[str], cache_dir: Path,
                  on_progress=None) -> dict[str, PromptTrack]:
    """Segment every prompt, reusing cached SAM output where present."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    paths = {p: raw_path(cache_dir, p) for p in prompts}
    missing = [p for p in prompts if not paths[p].exists()]

    if missing:
        file_id = upload_video(analysis_video)

        def run(p: str) -> None:
            segment_video(file_id, p, paths[p])
            if on_progress:
                on_progress(p)

        with ThreadPoolExecutor(max_workers=min(4, len(missing))) as pool:
            list(pool.map(run, missing))

    with ThreadPoolExecutor(max_workers=max(1, min(len(prompts), config.SAM_DECODE_WORKERS))) as pool:
        return dict(zip(prompts, pool.map(load_track, paths.values())))

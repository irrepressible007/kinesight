"""Rebuild the demo presets from their Pexels source and pre-run the full pipeline.

    python scripts/build_presets.py            (from backend/)

Each preset's results are cached in presets/<id>/cache so the demo replays instantly.
"""

import json
import subprocess
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config  # noqa: E402
from schemas import CompiledSop  # noqa: E402
from services import pipeline  # noqa: E402

RAW = config.PRESETS_DIR / "raw"

# id -> (pexels video id, ffmpeg filters, max duration in seconds)
PRESETS = {
    # Pexels 856232 shows four corner screws being removed; reversed, it is a fastening cycle.
    "plate_4screw_pass": (856232, "scale=1280:-2,reverse", None),
    # Same cycle cut at 27s, before the last (top-right) screw is driven.
    "plate_4screw_defect": (856232, "scale=1280:-2,reverse", 27.0),
}


def download(pexels_id: int) -> Path:
    dst = RAW / f"pexels_{pexels_id}.mp4"
    if not dst.exists():
        RAW.mkdir(parents=True, exist_ok=True)
        print(f"downloading Pexels {pexels_id}")
        with httpx.stream("GET", f"https://www.pexels.com/download/video/{pexels_id}/", follow_redirects=True,
                          headers={"User-Agent": "Mozilla/5.0"}, timeout=300) as r:
            r.raise_for_status()
            with open(dst, "wb") as f:
                for chunk in r.iter_bytes():
                    f.write(chunk)
    return dst


def build_clip(preset_id: str) -> Path:
    pexels_id, filters, max_sec = PRESETS[preset_id]
    out = config.PRESETS_DIR / preset_id / "video.mp4"
    if out.exists():
        return out
    src = download(pexels_id)
    cmd = ["ffmpeg", "-v", "error", "-y", "-i", str(src), "-vf", filters]
    if max_sec:
        cmd += ["-t", str(max_sec)]
    cmd += ["-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p",
            "-movflags", "+faststart", str(out)]
    subprocess.run(cmd, check=True)
    return out


def main(ids: list[str]) -> None:
    for preset_id in ids:
        video = build_clip(preset_id)
        meta = json.loads((config.PRESETS_DIR / preset_id / "preset.json").read_text(encoding="utf-8"))
        sop = CompiledSop.model_validate(meta["sop"])
        t = time.time()
        result = pipeline.run(
            f"preset-{preset_id}", video, sop, config.PRESETS_DIR / preset_id / "cache",
            f"/presets/{preset_id}/cache", f"/presets/{preset_id}/video.mp4",
            progress=lambda s: print(f"  [{preset_id}] {s}", flush=True),
        )
        v = result.verdict
        print(f"{preset_id}: {v.overall_status} score={v.compliance_score} defects={len(v.defects)} "
              f"({time.time() - t:.1f}s, cached={result.cached})")
        for step in result.telemetry.detected_interactions:
            print(f"  step {step.step_number}: {step.status} {step.contacts_detected}/{step.contacts_required}")
        for d in v.defects:
            print(f"  defect @ {d.timestamp_sec}s confirmed={d.auditor_confirmed}: {d.root_cause_summary}")


if __name__ == "__main__":
    main(sys.argv[1:] or list(PRESETS))

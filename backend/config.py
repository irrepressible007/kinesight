"""Runtime configuration. Every value can be overridden from the repo-root .env file."""

import os
from pathlib import Path

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parent
load_dotenv(BACKEND_DIR.parent / ".env")


def _float(name: str, default: float) -> float:
    return float(os.getenv(name, default))


META_API_KEY = os.getenv("META_API_KEY", "").strip()
META_BASE_URL = os.getenv("META_BASE_URL", "https://api.meta.ai/v1").rstrip("/")

SAM_MODEL = os.getenv("SAM_MODEL", "sam-3.1")
SPARK_MODEL = os.getenv("SPARK_MODEL", "muse-spark-1.3")
IMAGE_MODEL = os.getenv("IMAGE_MODEL", "muse-image-1.0")

# Video is resampled to this rate and width before segmentation.
FPS_RATE = _float("FPS_RATE", 15)
ANALYSIS_WIDTH = int(os.getenv("ANALYSIS_WIDTH", 1280))

# Kinematic thresholds are relative to the frame so they hold at any resolution.
DILATE_FRAC = _float("DILATE_FRAC", 0.030)  # dilation kernel, fraction of frame width
OVERLAP_FRAC = _float("OVERLAP_FRAC", 0.0002)  # min overlap pixels, fraction of frame area
STATIONARY_SPEED = _float("STATIONARY_SPEED", 0.45)  # frame diagonals per second
SPEED_WINDOW_SEC = _float("SPEED_WINDOW_SEC", 0.6)  # rolling-median window for the speed gate
MAX_GAP_SEC = _float("MAX_GAP_SEC", 0.8)  # contact gaps shorter than this are merged
MIN_INTERVAL_SEC = _float("MIN_INTERVAL_SEC", 0.6)  # shorter contacts are discarded as noise

# Guards for a public deployment that spends the owner's API credit. 0 means unlimited,
# the default for local runs. LIVE_ANALYSIS=0, or a missing key, turns the server into a
# replay of cached results that never calls the Meta API.
LIVE_ANALYSIS = os.getenv("LIVE_ANALYSIS", "1").strip() != "0" and bool(META_API_KEY)
DAILY_VIDEO_JOBS = int(os.getenv("DAILY_VIDEO_JOBS", 0))  # analyses of newly uploaded videos
DAILY_RULE_JOBS = int(os.getenv("DAILY_RULE_JOBS", 0))  # preset re-runs with edited rules
DAILY_COMPILES = int(os.getenv("DAILY_COMPILES", 0))  # SOP compiles not already cached
MAX_VIDEO_SEC = _float("MAX_VIDEO_SEC", 0)
MAX_UPLOAD_MB = _float("MAX_UPLOAD_MB", 0)
MAX_CONCURRENT_JOBS = int(os.getenv("MAX_CONCURRENT_JOBS", 2))
FFMPEG_THREADS = os.getenv("FFMPEG_THREADS", "0").strip()  # 0 = ffmpeg's choice; each thread buffers frames
SAM_DECODE_WORKERS = int(os.getenv("SAM_DECODE_WORKERS", 4))  # parallel mask decoders; 1 on 512 MB hosts

CACHE_DIR = BACKEND_DIR / "cache"
PRESETS_DIR = BACKEND_DIR / "presets"
DB_PATH = BACKEND_DIR / "kinesight.db"
# Static export of the frontend; served at / when present (single-container deployment).
FRONTEND_DIR = Path(os.getenv("FRONTEND_DIR", BACKEND_DIR.parent / "frontend" / "out"))

CACHE_DIR.mkdir(exist_ok=True)

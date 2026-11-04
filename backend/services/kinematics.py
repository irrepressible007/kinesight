"""Deterministic kinematics over SAM masks: centroids, velocities and dilated-mask contact.

No model is consulted here. Every duration, count and contact in the final verdict is
computed in this module from pixel masks.
"""

from dataclasses import dataclass, field

import cv2
import numpy as np

import config
from schemas import ContactInterval
from services.sam_tracker import Instance, PromptTrack

Pair = tuple[str, str]


def place_mask(instances: list[Instance], height: int, width: int) -> np.ndarray | None:
    """Union a label's box-local instance masks into one full-frame uint8 mask."""
    if not instances:
        return None
    full = np.zeros((height, width), np.uint8)
    for inst in instances:
        mh, mw = inst.mask.shape
        y0, x0 = max(inst.top, 0), max(inst.left, 0)
        y1, x1 = min(height, inst.top + mh), min(width, inst.left + mw)
        if y1 <= y0 or x1 <= x0:
            continue
        full[y0:y1, x0:x1] |= inst.mask[y0 - inst.top: y1 - inst.top, x0 - inst.left: x1 - inst.left]
    return full if full.any() else None


def centroid(mask: np.ndarray) -> tuple[float, float] | None:
    """Mask center of mass from spatial moments: (M10/M00, M01/M00)."""
    m = cv2.moments(mask, binaryImage=True)
    if m["m00"] == 0:
        return None
    return m["m10"] / m["m00"], m["m01"] / m["m00"]


def solid_region(mask: np.ndarray) -> np.ndarray:
    """Convex hull of a mask. Hands occluding a rigid part (plate, board) cut notches and
    holes into its mask exactly where the work happens; the hull restores that region."""
    pts = cv2.findNonZero(mask)
    out = np.zeros_like(mask)
    if pts is not None:
        cv2.fillConvexPoly(out, cv2.convexHull(pts), 1)
    return out


def dilated_overlap(actor: np.ndarray, target: np.ndarray, kernel_px: int) -> tuple[int, tuple[float, float] | None]:
    """Count pixels of Dilate(actor, k) AND target, and return where they sit."""
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (kernel_px, kernel_px))
    inter = cv2.bitwise_and(cv2.dilate(actor, k), target)
    n = int(cv2.countNonZero(inter))
    return n, (centroid(inter) if n else None)


def velocities(points: np.ndarray, fps: float, scale: float) -> np.ndarray:
    """Per-frame velocity vectors in scale-units per second; NaN where a point is missing."""
    v = np.full_like(points, np.nan)
    v[1:] = (points[1:] - points[:-1]) * fps / scale
    return v


def smooth(values: np.ndarray, window: int = 3) -> np.ndarray:
    """Rolling median that ignores NaN, to keep single-frame mask jitter out of speeds."""
    out = np.full_like(values, np.nan)
    half = window // 2
    for i in range(len(values)):
        w = values[max(0, i - half): i + half + 1]
        w = w[~np.isnan(w)]
        if w.size:
            out[i] = np.median(w)
    return out


def frames_to_intervals(flags: np.ndarray, fps: float, max_gap_sec: float,
                        min_interval_sec: float) -> list[tuple[int, int]]:
    """Turn per-frame contact flags into [start, end) frame intervals.

    Gaps up to max_gap_sec are bridged so a brief occlusion doesn't split one contact
    into two; intervals shorter than min_interval_sec are dropped as noise.
    """
    runs: list[list[int]] = []
    t, n = 0, len(flags)
    while t < n:
        if flags[t]:
            s = t
            while t < n and flags[t]:
                t += 1
            runs.append([s, t])
        else:
            t += 1
    max_gap = int(round(max_gap_sec * fps))
    merged: list[list[int]] = []
    for run in runs:
        if merged and run[0] - merged[-1][1] <= max_gap:
            merged[-1][1] = run[1]
        else:
            merged.append(run)
    min_len = min_interval_sec * fps
    return [(s, e) for s, e in merged if e - s >= min_len]


def polygons(mask: np.ndarray, width: int, height: int, min_area_frac: float = 0.0003) -> list[list[float]]:
    """Outer contours as flat [x0, y0, x1, y1, ...] lists normalized to [0, 1]."""
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    min_area = min_area_frac * width * height
    out = []
    for c in contours:
        if cv2.contourArea(c) < min_area:
            continue
        approx = cv2.approxPolyDP(c, 0.003 * cv2.arcLength(c, True), True).reshape(-1, 2)
        if len(approx) < 3:
            continue
        norm = approx.astype(np.float64) / (width, height)
        out.append([round(float(v), 4) for v in norm.flatten()])
    return out


@dataclass
class KinematicResult:
    width: int
    height: int
    fps: float
    total_frames: int
    # label -> per-frame {"poly": [...], "c": [x, y] | None}, normalized coordinates
    tracks: dict[str, list[dict]] = field(default_factory=dict)
    # label -> per-frame smoothed speed in frame diagonals per second (None when unseen)
    speed: dict[str, list[float | None]] = field(default_factory=dict)
    overlap: dict[Pair, np.ndarray] = field(default_factory=dict)
    contact: dict[Pair, np.ndarray] = field(default_factory=dict)
    intervals: dict[Pair, list[ContactInterval]] = field(default_factory=dict)


def analyze(tracks: dict[str, PromptTrack], width: int, height: int, fps: float,
            total_frames: int, pairs: list[Pair]) -> KinematicResult:
    labels = list(tracks)
    diag = float(np.hypot(width, height))
    kernel_px = max(3, int(round(config.DILATE_FRAC * width)) | 1)
    min_overlap = config.OVERLAP_FRAC * width * height

    cents = {lb: np.full((total_frames, 2), np.nan) for lb in labels}
    overlap = {p: np.zeros(total_frames) for p in pairs}
    overlap_loc = {p: np.full((total_frames, 2), np.nan) for p in pairs}
    res = KinematicResult(width, height, fps, total_frames, tracks={lb: [] for lb in labels})

    for t in range(total_frames):
        masks = {lb: place_mask(tracks[lb].get(t, []), height, width) for lb in labels}
        for lb, m in masks.items():
            c = centroid(m) if m is not None else None
            if c is not None:
                cents[lb][t] = c
            res.tracks[lb].append({
                "poly": polygons(m, width, height) if m is not None else [],
                "c": [round(c[0] / width, 4), round(c[1] / height, 4)] if c else None,
            })
        solids: dict[str, np.ndarray] = {}
        for a, b in pairs:
            if masks.get(a) is None or masks.get(b) is None:
                continue
            if b not in solids:
                solids[b] = solid_region(masks[b])
            n, loc = dilated_overlap(masks[a], solids[b], kernel_px)
            overlap[(a, b)][t] = n
            if loc is not None:
                overlap_loc[(a, b)][t] = loc

    vel = {lb: velocities(cents[lb], fps, diag) for lb in labels}
    for lb in labels:
        sp = smooth(np.hypot(vel[lb][:, 0], vel[lb][:, 1]))
        res.speed[lb] = [None if np.isnan(s) else round(float(s), 4) for s in sp]

    window = max(3, int(round(config.SPEED_WINDOW_SEC * fps)) | 1)
    for a, b in pairs:
        # Gate on the actor's own speed. A large target (plate, PCB) is partly occluded by
        # the hand while work happens, which makes its centroid drift; subtracting that
        # drift would inject noise rather than remove it.
        work_speed = smooth(np.hypot(vel[a][:, 0], vel[a][:, 1]), window)
        # An unknown speed (object just appeared) doesn't veto contact; overlap still must hold.
        still = np.isnan(work_speed) | (work_speed <= config.STATIONARY_SPEED)
        flags = (overlap[(a, b)] >= min_overlap) & still
        res.overlap[(a, b)] = overlap[(a, b)]
        res.contact[(a, b)] = flags
        res.intervals[(a, b)] = [
            _interval(s, e, fps, overlap[(a, b)], overlap_loc[(a, b)], width, height)
            for s, e in frames_to_intervals(flags, fps, config.MAX_GAP_SEC, config.MIN_INTERVAL_SEC)
        ]
    return res


def _interval(s: int, e: int, fps: float, overlap: np.ndarray, loc: np.ndarray,
              width: int, height: int) -> ContactInterval:
    seg = overlap[s:e]
    pts = loc[s:e]
    pts = pts[~np.isnan(pts[:, 0])]
    location = None
    if len(pts):
        mx, my = pts.mean(axis=0)
        location = (round(float(mx / width), 4), round(float(my / height), 4))
    return ContactInterval(
        start_sec=round(s / fps, 2),
        end_sec=round(e / fps, 2),
        duration_sec=round((e - s) / fps, 2),
        mean_overlap_px=round(float(seg[seg > 0].mean()) if (seg > 0).any() else 0.0, 1),
        location=location,
    )

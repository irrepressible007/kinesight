import numpy as np
import pytest

from services.kinematics import (
    centroid,
    dilated_overlap,
    frames_to_intervals,
    place_mask,
    polygons,
    smooth,
    solid_region,
    velocities,
)
from services.sam_tracker import Instance


def rect(h, w, y0, y1, x0, x1):
    m = np.zeros((h, w), np.uint8)
    m[y0:y1, x0:x1] = 1
    return m


def test_centroid_of_rectangle():
    assert centroid(rect(100, 100, 10, 30, 40, 60)) == pytest.approx((49.5, 19.5))


def test_centroid_of_empty_mask_is_none():
    assert centroid(np.zeros((10, 10), np.uint8)) is None


def test_place_mask_offsets_box_local_masks_and_clips_edges():
    inst = Instance("0", left=8, top=8, mask=np.ones((4, 4), np.uint8))
    full = place_mask([inst], 10, 10)
    assert full.sum() == 4  # only the 2x2 corner inside the frame survives
    assert full[8:, 8:].all()


def test_place_mask_unions_instances():
    a = Instance("0", 0, 0, np.ones((2, 2), np.uint8))
    b = Instance("1", 5, 5, np.ones((2, 2), np.uint8))
    assert place_mask([a, b], 10, 10).sum() == 8


def test_dilation_detects_edge_contact_that_raw_overlap_misses():
    tool = rect(50, 50, 20, 30, 10, 20)
    part = rect(50, 50, 20, 30, 22, 40)  # 2px gap between tool and part
    assert (tool & part).sum() == 0
    n, loc = dilated_overlap(tool, part, kernel_px=7)
    assert n > 0
    assert loc[0] == pytest.approx(22.5, abs=1.0)


def test_no_contact_when_far_apart():
    n, loc = dilated_overlap(rect(50, 50, 0, 5, 0, 5), rect(50, 50, 40, 50, 40, 50), kernel_px=7)
    assert n == 0 and loc is None


def test_velocity_is_distance_times_fps_over_scale():
    pts = np.array([[0.0, 0.0], [3.0, 4.0], [np.nan, np.nan]])
    v = velocities(pts, fps=10, scale=50)
    assert np.isnan(v[0]).all()
    assert np.hypot(*v[1]) == pytest.approx(1.0)  # 5px * 10fps / 50
    assert np.isnan(v[2]).all()


def test_smooth_removes_single_frame_spike_and_ignores_nan():
    s = smooth(np.array([1.0, 1.0, 9.0, 1.0, np.nan, 1.0]))
    assert s[2] == 1.0
    assert s[4] == 1.0


def test_intervals_merge_short_gaps_and_drop_noise():
    flags = np.array([1, 1, 1, 0, 1, 1, 0, 0, 0, 0, 1, 0, 0, 0, 1, 1, 1, 1], bool)
    # fps=10: gap of 1 frame (0.1s) merges, lone frame at 10 (0.1s) is noise
    assert frames_to_intervals(flags, fps=10, max_gap_sec=0.2, min_interval_sec=0.3) == [(0, 6), (14, 18)]


def test_intervals_trailing_run_and_empty():
    assert frames_to_intervals(np.zeros(5, bool), 10, 0.2, 0.1) == []
    assert frames_to_intervals(np.ones(5, bool), 10, 0.2, 0.1) == [(0, 5)]


def test_polygons_are_normalized():
    polys = polygons(rect(100, 200, 10, 50, 20, 120), width=200, height=100)
    assert len(polys) == 1
    xs, ys = polys[0][0::2], polys[0][1::2]
    assert min(xs) == pytest.approx(0.1) and max(xs) == pytest.approx(119 / 200)
    assert min(ys) == pytest.approx(0.1) and max(ys) == pytest.approx(0.49)


def test_solid_region_fills_occlusion_notch_per_instance():
    plate = np.ones((10, 10), np.uint8)
    plate[4:7, 0:5] = 0  # a hand-shaped notch cut into the plate's left edge
    far = np.ones((2, 2), np.uint8)
    solid = solid_region([Instance("0", 0, 0, plate), Instance("1", 30, 30, far)], 40, 40)
    assert solid[5, 2] == 1  # notch restored
    assert solid[20, 20] == 0  # the two instances are not bridged
    assert solid[30:32, 30:32].all()

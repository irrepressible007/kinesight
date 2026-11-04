import pytest

from schemas import CompiledSop, ContactInterval
from services.rule_evaluator import evaluate


def iv(start, end):
    return ContactInterval(start_sec=start, end_sec=end, duration_sec=round(end - start, 2), mean_overlap_px=100)


def sop(*steps):
    prompts = sorted({o for s in steps for o in (s["actor_object"], s["target_object"])})
    return CompiledSop(sop_title="t", sam_prompts=prompts, steps=[
        {"step_number": i + 1, "description": f"step {i + 1}", **s} for i, s in enumerate(steps)
    ])


PASTE = {"actor_object": "syringe", "target_object": "pcb", "min_contact_sec": 1.5, "required_contacts": 1}
SINK = {"actor_object": "heatsink", "target_object": "pcb", "min_contact_sec": 2.0, "required_contacts": 1}
SCREWS = {"actor_object": "screwdriver", "target_object": "heatsink", "min_contact_sec": 1.8, "required_contacts": 4}


def test_spec_example_three_of_four_screws():
    intervals = {
        ("syringe", "pcb"): [iv(2.1, 4.0)],
        ("heatsink", "pcb"): [iv(5.5, 19.0)],
        ("screwdriver", "heatsink"): [iv(8.0, 10.1), iv(11.2, 13.4), iv(14.5, 16.6)],
    }
    results, anomalies, score = evaluate(sop(PASTE, SINK, SCREWS), intervals, 22.0)
    assert [r.status for r in results] == ["PASS", "PASS", "FAIL_COUNT_SHORTFALL"]
    assert results[2].contacts_detected == 3
    assert score == pytest.approx(66.7)
    assert len(anomalies) == 1
    assert anomalies[0].timestamp_sec == 16.6 and anomalies[0].severity == "CRITICAL"


def test_missing_step():
    results, anomalies, score = evaluate(sop(PASTE, SINK), {("syringe", "pcb"): [iv(1, 3)]}, 10.0)
    assert results[1].status == "FAIL_MISSING"
    assert anomalies[0].timestamp_sec == 3
    assert score == 50.0


def test_short_duration_cold_joint():
    results, anomalies, _ = evaluate(sop(PASTE), {("syringe", "pcb"): [iv(1.0, 1.4)]}, 10.0)
    assert results[0].status == "FAIL_SHORT_DURATION"
    assert results[0].contact_intervals[0].meets_min_duration is False
    assert anomalies[0].severity == "MAJOR"


def test_four_contacts_one_too_short_is_short_duration_not_shortfall():
    ivs = [iv(0, 2), iv(3, 5), iv(6, 8), iv(9, 9.5)]
    results, _, _ = evaluate(sop(SCREWS), {("screwdriver", "heatsink"): ivs}, 12.0)
    assert results[0].status == "FAIL_SHORT_DURATION"
    assert results[0].contacts_detected == 3


def test_out_of_order():
    intervals = {("syringe", "pcb"): [iv(6.0, 8.0)], ("heatsink", "pcb"): [iv(1.0, 4.0)]}
    results, anomalies, _ = evaluate(sop(PASTE, SINK), intervals, 10.0)
    assert results[1].status == "FAIL_ORDER"
    assert anomalies[0].timestamp_sec == 1.0


def test_overlapping_long_step_does_not_break_order():
    # Heatsink stays on the PCB while screws are driven; order is judged by start time.
    intervals = {
        ("heatsink", "pcb"): [iv(5.5, 19.0)],
        ("screwdriver", "heatsink"): [iv(8, 10), iv(11, 13), iv(14, 16), iv(16.5, 18.5)],
    }
    results, anomalies, score = evaluate(sop(SINK, SCREWS), intervals, 20.0)
    assert [r.status for r in results] == ["PASS", "PASS"]
    assert anomalies == [] and score == 100.0


def test_shared_pair_steps_consume_intervals_in_order():
    first = {**SCREWS, "required_contacts": 2}
    second = {**SCREWS, "required_contacts": 2}
    ivs = [iv(0, 2), iv(3, 5), iv(6, 8)]
    results, _, _ = evaluate(sop(first, second), {("screwdriver", "heatsink"): ivs}, 10.0)
    assert results[0].status == "PASS"
    assert results[1].status == "FAIL_COUNT_SHORTFALL"
    assert results[1].contact_intervals == [ivs[2].model_copy(update={"meets_min_duration": True})]

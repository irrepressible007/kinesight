"""Deterministic rule evaluation: measured contact intervals vs. compiled SOP steps."""

from dataclasses import dataclass

from schemas import CompiledSop, ContactInterval, Severity, StepResult, StepStatus

Pair = tuple[str, str]

SEVERITY: dict[StepStatus, Severity] = {
    "FAIL_MISSING": "CRITICAL",
    "FAIL_COUNT_SHORTFALL": "CRITICAL",
    "FAIL_SHORT_DURATION": "MAJOR",
    "FAIL_ORDER": "MAJOR",
}


@dataclass
class Anomaly:
    step_number: int
    status: StepStatus
    severity: Severity
    timestamp_sec: float
    summary: str


def evaluate(sop: CompiledSop, intervals: dict[Pair, list[ContactInterval]],
             duration_sec: float) -> tuple[list[StepResult], list[Anomaly], float]:
    """Return per-step results, anomalies to audit, and a compliance score in percent.

    When several steps share an actor/target pair, each step consumes intervals in time
    order so one contact is never credited to two steps.
    """
    cursor: dict[Pair, int] = {}
    results: list[StepResult] = []
    anomalies: list[Anomaly] = []
    prev_start: float | None = None
    prev_end = 0.0

    for step in sop.steps:
        pair = (step.actor_object, step.target_object)
        pool = intervals.get(pair, [])
        shared = sum(1 for s in sop.steps if (s.actor_object, s.target_object) == pair) > 1
        start_idx = cursor.get(pair, 0)
        own = pool[start_idx: start_idx + step.required_contacts] if shared else pool[start_idx:]
        cursor[pair] = start_idx + len(own)

        own = [iv.model_copy(update={"meets_min_duration": iv.duration_sec >= step.min_contact_sec}) for iv in own]
        qualifying = [iv for iv in own if iv.meets_min_duration]

        if not own:
            status: StepStatus = "FAIL_MISSING"
        elif len(qualifying) >= step.required_contacts:
            status = "PASS"
        elif len(own) >= step.required_contacts:
            status = "FAIL_SHORT_DURATION"
        else:
            status = "FAIL_COUNT_SHORTFALL"

        first_start = own[0].start_sec if own else None
        if status == "PASS" and prev_start is not None and first_start is not None and first_start < prev_start:
            status = "FAIL_ORDER"

        results.append(StepResult(
            event_id=f"evt_{step.step_number}",
            step_number=step.step_number,
            description=step.description,
            actor=step.actor_object,
            target=step.target_object,
            min_contact_sec=step.min_contact_sec,
            contact_intervals=own,
            contacts_detected=len(qualifying),
            contacts_required=step.required_contacts,
            status=status,
        ))

        if status != "PASS":
            anomalies.append(_anomaly(step.step_number, status, own, qualifying, step.required_contacts,
                                      step.min_contact_sec, pair, prev_end, duration_sec))
        if first_start is not None:
            prev_start = first_start
            prev_end = own[-1].end_sec

    passed = sum(r.status == "PASS" for r in results)
    score = round(100.0 * passed / len(results), 1) if results else 0.0
    return results, anomalies, score


def _anomaly(step_number: int, status: StepStatus, own: list[ContactInterval],
             qualifying: list[ContactInterval], required: int, min_sec: float, pair: Pair,
             prev_end: float, duration_sec: float) -> Anomaly:
    actor, target = pair
    if status == "FAIL_MISSING":
        ts = prev_end if prev_end else 0.0
        summary = f"No {actor}-to-{target} contact was measured anywhere in the cycle."
    elif status == "FAIL_COUNT_SHORTFALL":
        ts = own[-1].end_sec
        summary = f"Only {len(own)} of {required} required {actor}-to-{target} contacts were measured."
    elif status == "FAIL_SHORT_DURATION":
        short = min((iv for iv in own if not iv.meets_min_duration), key=lambda iv: iv.duration_sec)
        ts = short.end_sec
        summary = (f"{len(qualifying)} of {required} {actor}-to-{target} contacts met the "
                   f"{min_sec:.1f}s minimum; the shortest lasted {short.duration_sec:.2f}s.")
    else:
        ts = own[0].start_sec
        summary = f"{actor}-to-{target} contact started at {ts:.1f}s, before the preceding step began."
    return Anomaly(step_number, status, SEVERITY[status], round(min(ts, duration_sec), 2), summary)

"""Pydantic contracts shared by the pipeline stages and the API."""

from typing import Literal

from pydantic import BaseModel, Field, model_validator

StepStatus = Literal[
    "PASS",
    "FAIL_MISSING",
    "FAIL_COUNT_SHORTFALL",
    "FAIL_SHORT_DURATION",
    "FAIL_ORDER",
]
Severity = Literal["CRITICAL", "MAJOR", "MINOR"]


# ---- Stage 1: compiled SOP -------------------------------------------------


class SopStep(BaseModel):
    step_number: int = Field(ge=1)
    description: str
    actor_object: str
    target_object: str
    min_contact_sec: float = Field(ge=0)
    required_contacts: int = Field(ge=1)


class CompiledSop(BaseModel):
    sop_title: str
    sam_prompts: list[str] = Field(min_length=1, max_length=8)
    steps: list[SopStep] = Field(min_length=1)

    @model_validator(mode="after")
    def _check_references(self) -> "CompiledSop":
        prompts = set(self.sam_prompts)
        for step in self.steps:
            for obj in (step.actor_object, step.target_object):
                if obj not in prompts:
                    raise ValueError(f"step {step.step_number} references '{obj}', which is not in sam_prompts")
            if step.actor_object == step.target_object:
                raise ValueError(f"step {step.step_number} uses the same object as actor and target")
        self.steps.sort(key=lambda s: s.step_number)
        return self


# ---- Stage 3: kinematic telemetry ------------------------------------------


class ContactInterval(BaseModel):
    start_sec: float
    end_sec: float
    duration_sec: float
    mean_overlap_px: float
    # Mean position of the actor/target overlap, normalized to [0, 1] of the frame.
    location: tuple[float, float] | None = None
    meets_min_duration: bool = True


class StepResult(BaseModel):
    event_id: str
    step_number: int
    description: str
    actor: str
    target: str
    min_contact_sec: float
    contact_intervals: list[ContactInterval]
    contacts_detected: int  # intervals that meet min_contact_sec
    contacts_required: int
    status: StepStatus


class Telemetry(BaseModel):
    video_id: str
    fps_analyzed: float
    total_frames: int
    total_duration_sec: float
    frame_width: int
    frame_height: int
    detected_interactions: list[StepResult]


# ---- Stage 4: audit verdict ------------------------------------------------


class Defect(BaseModel):
    step_number: int
    status: StepStatus
    severity: Severity
    timestamp_sec: float
    keyframe_paths: list[str] = []
    root_cause_summary: str
    corrective_action: str
    corrective_diagram_url: str | None = None
    auditor_confirmed: bool | None = None  # None when the auditor could not be reached
    auditor_confidence: float | None = None


class AuditVerdict(BaseModel):
    overall_status: Literal["PASS", "FAIL", "REVIEW"]
    cycle_time_sec: float
    compliance_score: float
    defects: list[Defect]


# ---- API payloads ----------------------------------------------------------


class JobResult(BaseModel):
    job_id: str
    video_url: str
    tracks_url: str
    sop: CompiledSop
    telemetry: Telemetry
    verdict: AuditVerdict
    timings_ms: dict[str, float] = {}
    cached: bool = False

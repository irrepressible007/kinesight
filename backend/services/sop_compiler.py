"""Stage 1: compile a human SOP into SAM prompts and machine-checkable contact rules."""

import io

from pypdf import PdfReader

from schemas import CompiledSop
from services.meta_client import spark_json

SYSTEM = """You compile manufacturing Standard Operating Procedures into machine-verifiable rules
for a vision system. The vision system segments objects with SAM 3.1 from short text prompts and
measures when one object's mask touches another's, for how long, and how many times.

Rules:
- sam_prompts: 2 to 6 short, concrete, visible noun phrases that SAM can find in an overhead video
  (e.g. "screwdriver", "metal plate", "soldering iron", "circuit board", "hand"). Lowercase, no
  underscores, no abstract things (no "torque", "alignment"). Include "hand" only if useful.
  Name objects by what they look like, not their role in the procedure: SAM recognizes "metal
  plate" or "circuit board", but not "mounting plate", "bracket assembly" or "unit under test".
- Each step is one physical contact rule: actor_object touches target_object. Both MUST be exact
  strings from sam_prompts, and must differ. Prefer a large, stable target (the plate or board being
  worked on) over tiny parts that the tool will hide (screws, pins).
- min_contact_sec: the minimum seconds each contact must last. Use the SOP's number when given;
  otherwise a realistic value for the action (screw driving ~1.5, soldering a joint ~2.0).
- required_contacts: how many separate contacts the step needs (e.g. 4 screws -> 4).
- Number steps from 1 in the order the SOP requires. Skip steps that no camera could verify.
- sop_title: a short title for the procedure."""

SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["sop_title", "sam_prompts", "steps"],
    "properties": {
        "sop_title": {"type": "string"},
        "sam_prompts": {"type": "array", "items": {"type": "string"}},
        "steps": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["step_number", "description", "actor_object", "target_object",
                             "min_contact_sec", "required_contacts"],
                "properties": {
                    "step_number": {"type": "integer"},
                    "description": {"type": "string"},
                    "actor_object": {"type": "string"},
                    "target_object": {"type": "string"},
                    "min_contact_sec": {"type": "number"},
                    "required_contacts": {"type": "integer"},
                },
            },
        },
    },
}


def pdf_to_text(data: bytes) -> str:
    return "\n".join(page.extract_text() or "" for page in PdfReader(io.BytesIO(data)).pages)


def compile_sop(sop_text: str) -> CompiledSop:
    raw = spark_json(SYSTEM, f"SOP document:\n\n{sop_text.strip()}", "compiled_sop", SCHEMA)
    return CompiledSop.model_validate(raw)

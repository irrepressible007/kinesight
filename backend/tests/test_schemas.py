import pytest
from pydantic import ValidationError

from schemas import CompiledSop

SPEC_SOP = {
    "sop_title": "Router PCB Heatsink & Fan Assembly",
    "sam_prompts": ["hand", "thermal_syringe", "heatsink", "screwdriver", "pcb"],
    "steps": [
        {"step_number": 1, "description": "Apply thermal paste", "actor_object": "thermal_syringe",
         "target_object": "pcb", "min_contact_sec": 1.5, "required_contacts": 1},
        {"step_number": 3, "description": "Fasten 4 screws", "actor_object": "screwdriver",
         "target_object": "heatsink", "min_contact_sec": 1.8, "required_contacts": 4},
        {"step_number": 2, "description": "Place heatsink", "actor_object": "heatsink",
         "target_object": "pcb", "min_contact_sec": 2.0, "required_contacts": 1},
    ],
}


def test_spec_example_parses_and_sorts_steps():
    sop = CompiledSop.model_validate(SPEC_SOP)
    assert [s.step_number for s in sop.steps] == [1, 2, 3]


def test_unknown_object_is_rejected():
    bad = {**SPEC_SOP, "sam_prompts": ["hand", "heatsink", "screwdriver", "pcb"]}
    with pytest.raises(ValidationError, match="thermal_syringe"):
        CompiledSop.model_validate(bad)


def test_same_actor_and_target_is_rejected():
    bad = {**SPEC_SOP, "steps": [{**SPEC_SOP["steps"][0], "target_object": "thermal_syringe"}]}
    with pytest.raises(ValidationError, match="same object"):
        CompiledSop.model_validate(bad)


def test_non_positive_contacts_rejected():
    bad = {**SPEC_SOP, "steps": [{**SPEC_SOP["steps"][0], "required_contacts": 0}]}
    with pytest.raises(ValidationError):
        CompiledSop.model_validate(bad)

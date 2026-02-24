"""
Unit tests for Flooring & Finishes schema (FinishSpec, FloorFinish)
and the three interview extractor functions.
"""

from __future__ import annotations

import pytest

from civilengineer.requirements_interview.questions import (
    QUESTION_BY_ID,
    QUESTIONS,
    answers_to_requirements,
    extract_ceiling_finish,
    extract_floor_finish,
    extract_wall_paint,
)
from civilengineer.schemas.design import (
    DesignRequirements,
    FinishSpec,
    FloorFinish,
)


# ---------------------------------------------------------------------------
# FloorFinish extractor
# ---------------------------------------------------------------------------


class TestExtractFloorFinish:
    def test_marble(self):
        assert extract_floor_finish("We want Italian marble") == FloorFinish.MARBLE

    def test_marble_variant(self):
        assert extract_floor_finish("imported marble throughout") == FloorFinish.MARBLE

    def test_granite(self):
        assert extract_floor_finish("granite slab for the lobby") == FloorFinish.GRANITE

    def test_hardwood(self):
        assert extract_floor_finish("hardwood floor in bedrooms") == FloorFinish.HARDWOOD

    def test_timber(self):
        assert extract_floor_finish("timber floor, teak") == FloorFinish.HARDWOOD

    def test_mosaic(self):
        assert extract_floor_finish("mosaic tile in bathrooms") == FloorFinish.MOSAIC

    def test_vinyl(self):
        assert extract_floor_finish("vinyl flooring, laminate") == FloorFinish.VINYL

    def test_pvc_vinyl(self):
        assert extract_floor_finish("luxury vinyl PVC tiles") == FloorFinish.VINYL

    def test_concrete(self):
        assert extract_floor_finish("plain concrete screed") == FloorFinish.CONCRETE

    def test_default_tile(self):
        assert extract_floor_finish("standard tile") == FloorFinish.TILE

    def test_empty_defaults_to_tile(self):
        assert extract_floor_finish("") == FloorFinish.TILE

    def test_vitrified_tile(self):
        assert extract_floor_finish("vitrified tile everywhere") == FloorFinish.TILE


# ---------------------------------------------------------------------------
# Ceiling finish extractor
# ---------------------------------------------------------------------------


class TestExtractCeilingFinish:
    def test_wood_panel(self):
        assert extract_ceiling_finish("wood panel ceiling") == "wood_panel"

    def test_timber(self):
        assert extract_ceiling_finish("timber panel") == "wood_panel"

    def test_false_ceiling(self):
        assert extract_ceiling_finish("false ceiling in living room") == "false_ceiling"

    def test_gypsum(self):
        assert extract_ceiling_finish("gypsum board grid") == "false_ceiling"

    def test_pop(self):
        assert extract_ceiling_finish("POP cornice on all rooms") == "pop"

    def test_decorative(self):
        assert extract_ceiling_finish("decorative plaster of paris") == "pop"

    def test_plaster_default(self):
        assert extract_ceiling_finish("") == "plaster"

    def test_plain_plaster(self):
        assert extract_ceiling_finish("just plain plaster, nothing fancy") == "plaster"


# ---------------------------------------------------------------------------
# Wall paint extractor
# ---------------------------------------------------------------------------


class TestExtractWallPaint:
    def test_texture(self):
        assert extract_wall_paint("texture paint in the living room") == "texture"

    def test_3d_paint(self):
        assert extract_wall_paint("3d paint effect") == "texture"

    def test_premium(self):
        assert extract_wall_paint("premium branded paint") == "premium"

    def test_asian_paints(self):
        assert extract_wall_paint("asian paints royale luxury") == "premium"

    def test_standard_default(self):
        assert extract_wall_paint("standard emulsion") == "standard"

    def test_empty(self):
        assert extract_wall_paint("") == "standard"


# ---------------------------------------------------------------------------
# FinishSpec schema
# ---------------------------------------------------------------------------


class TestFinishSpec:
    def test_default_values(self):
        spec = FinishSpec()
        assert spec.flooring == FloorFinish.TILE
        assert spec.wall_paint == "standard"
        assert spec.ceiling == "plaster"

    def test_custom_values(self):
        spec = FinishSpec(flooring=FloorFinish.MARBLE, wall_paint="premium", ceiling="false_ceiling")
        assert spec.flooring == FloorFinish.MARBLE
        assert spec.ceiling == "false_ceiling"

    def test_serialisation(self):
        spec = FinishSpec(flooring=FloorFinish.GRANITE)
        d = spec.model_dump()
        assert d["flooring"] == "granite"
        assert d["wall_paint"] == "standard"

    def test_deserialisation_from_string(self):
        spec = FinishSpec.model_validate({"flooring": "marble", "ceiling": "pop"})
        assert spec.flooring == FloorFinish.MARBLE
        assert spec.ceiling == "pop"


# ---------------------------------------------------------------------------
# DesignRequirements.finish_overrides
# ---------------------------------------------------------------------------


class TestDesignRequirementsFinishes:
    def test_finish_overrides_default_empty(self):
        req = DesignRequirements(project_id="p1")
        assert req.finish_overrides == {}

    def test_finish_overrides_stored(self):
        req = DesignRequirements(
            project_id="p1",
            finish_overrides={
                "bedroom": {"flooring": "marble", "wall_paint": "premium", "ceiling": "plaster"},
                "bathroom": {"flooring": "tile", "wall_paint": "standard", "ceiling": "false_ceiling"},
            },
        )
        assert req.finish_overrides["bedroom"].flooring == FloorFinish.MARBLE
        assert req.finish_overrides["bathroom"].flooring == FloorFinish.TILE

    def test_roundtrip_json(self):
        req = DesignRequirements(
            project_id="p1",
            finish_overrides={
                "kitchen": FinishSpec(flooring=FloorFinish.GRANITE, ceiling="pop"),
            },
        )
        data = req.model_dump()
        req2 = DesignRequirements.model_validate(data)
        assert req2.finish_overrides["kitchen"].flooring == FloorFinish.GRANITE
        assert req2.finish_overrides["kitchen"].ceiling == "pop"


# ---------------------------------------------------------------------------
# QUESTIONS list registration
# ---------------------------------------------------------------------------


class TestFinishQuestionsRegistered:
    def test_floor_finish_dry_in_questions(self):
        assert "floor_finish_dry" in QUESTION_BY_ID

    def test_floor_finish_wet_in_questions(self):
        assert "floor_finish_wet" in QUESTION_BY_ID

    def test_ceiling_finish_in_questions(self):
        assert "ceiling_finish" in QUESTION_BY_ID

    def test_wall_paint_in_questions(self):
        assert "wall_paint" in QUESTION_BY_ID

    def test_all_finish_questions_have_finishes_phase(self):
        finish_questions = [q for q in QUESTIONS if q.phase == "finishes"]
        ids = {q.id for q in finish_questions}
        assert {"floor_finish_dry", "floor_finish_wet", "ceiling_finish", "wall_paint"} == ids

    def test_finish_questions_not_required(self):
        for q in QUESTIONS:
            if q.phase == "finishes":
                assert not q.required, f"Question {q.id} should be optional"

    def test_floor_finish_dry_extractor(self):
        q = QUESTION_BY_ID["floor_finish_dry"]
        assert q.extractor is not None
        assert q.extractor("marble flooring please") == FloorFinish.MARBLE

    def test_ceiling_finish_extractor(self):
        q = QUESTION_BY_ID["ceiling_finish"]
        assert q.extractor is not None
        assert q.extractor("false ceiling") == "false_ceiling"


# ---------------------------------------------------------------------------
# answers_to_requirements integration
# ---------------------------------------------------------------------------


class TestAnswersToRequirementsFinishes:
    def _base_answers(self) -> dict:
        return {
            "building_type": "residential",
            "num_floors": 2,
            "bhk_config": {"bedroom_count": 2, "bathroom_count": 1},
        }

    def test_no_finish_answers_gives_empty_overrides(self):
        req_dict = answers_to_requirements(self._base_answers(), project_id="p1")
        assert req_dict["finish_overrides"] == {}

    def test_dry_finish_marble_populates_bedroom_and_living(self):
        answers = {**self._base_answers(), "floor_finish_dry": FloorFinish.MARBLE}
        req_dict = answers_to_requirements(answers, project_id="p1")
        overrides = req_dict["finish_overrides"]
        assert overrides["master_bedroom"]["flooring"] == "marble"
        assert overrides["bedroom"]["flooring"] == "marble"
        assert overrides["living_room"]["flooring"] == "marble"
        assert overrides["dining_room"]["flooring"] == "marble"

    def test_wet_finish_granite_populates_kitchen_and_bathroom(self):
        answers = {**self._base_answers(), "floor_finish_wet": FloorFinish.GRANITE}
        req_dict = answers_to_requirements(answers, project_id="p1")
        overrides = req_dict["finish_overrides"]
        assert overrides["bathroom"]["flooring"] == "granite"
        assert overrides["kitchen"]["flooring"] == "granite"
        assert overrides["toilet"]["flooring"] == "granite"

    def test_dry_and_wet_both_populated(self):
        answers = {
            **self._base_answers(),
            "floor_finish_dry": FloorFinish.HARDWOOD,
            "floor_finish_wet": FloorFinish.TILE,
        }
        req_dict = answers_to_requirements(answers, project_id="p1")
        overrides = req_dict["finish_overrides"]
        assert overrides["bedroom"]["flooring"] == "hardwood"
        assert overrides["bathroom"]["flooring"] == "tile"

    def test_ceiling_applied_to_both_groups(self):
        answers = {
            **self._base_answers(),
            "floor_finish_dry": FloorFinish.TILE,
            "floor_finish_wet": FloorFinish.TILE,
            "ceiling_finish": "false_ceiling",
        }
        req_dict = answers_to_requirements(answers, project_id="p1")
        overrides = req_dict["finish_overrides"]
        assert overrides["bedroom"]["ceiling"] == "false_ceiling"
        assert overrides["bathroom"]["ceiling"] == "false_ceiling"

    def test_wall_paint_applied(self):
        answers = {
            **self._base_answers(),
            "floor_finish_dry": FloorFinish.MARBLE,
            "wall_paint": "premium",
        }
        req_dict = answers_to_requirements(answers, project_id="p1")
        overrides = req_dict["finish_overrides"]
        assert overrides["bedroom"]["wall_paint"] == "premium"

    def test_result_is_valid_design_requirements(self):
        answers = {
            **self._base_answers(),
            "floor_finish_dry": FloorFinish.TILE,
            "floor_finish_wet": FloorFinish.MOSAIC,
            "ceiling_finish": "pop",
            "wall_paint": "texture",
        }
        req_dict = answers_to_requirements(answers, project_id="p1")
        req = DesignRequirements.model_validate(req_dict)
        assert req.finish_overrides["bathroom"].flooring == FloorFinish.MOSAIC
        assert req.finish_overrides["kitchen"].ceiling == "pop"
        assert req.finish_overrides["bedroom"].wall_paint == "texture"

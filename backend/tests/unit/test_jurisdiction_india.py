"""
Phase 10: India Jurisdiction (IN-MH) unit tests.

Tests cover:
  - SetbackDB: Mumbai, Pune, Bangalore setback lookups
  - India-specific extractor functions
  - India style preferences
  - India questions registered in QUESTIONS list
  - Rule compiler: loads rules_india.json for IN-MH jurisdiction
  - Jurisdiction fallback hierarchy (IN-MH → IN → fallback)
"""

from __future__ import annotations

import pytest

from civilengineer.knowledge.setback_db import SetbackDB, _guess_fallback_table
from civilengineer.requirements_interview.questions import (
    QUESTION_BY_ID,
    QUESTIONS,
    extract_basement_parking,
    extract_fsi_zone,
    extract_india_style,
    extract_rera_applicable,
    extract_unit_preference,
)
from civilengineer.schemas.design import StylePreference


# ---------------------------------------------------------------------------
# SetbackDB — India cities
# ---------------------------------------------------------------------------


class TestSetbackDBMumbai:
    db = SetbackDB()

    def test_mumbai_narrow_road(self):
        front, rear, left, right = self.db.get_setbacks("mumbai", road_width_m=6.0)
        assert front == 3.0
        assert left == 1.5

    def test_mumbai_local_road(self):
        front, rear, left, right = self.db.get_setbacks("mumbai", road_width_m=10.0)
        assert front == 4.5
        assert rear == 3.0

    def test_mumbai_collector_road(self):
        front, rear, left, right = self.db.get_setbacks("IN-MH", road_width_m=15.0)
        assert front == 6.0
        assert left == 3.0

    def test_mumbai_arterial_road(self):
        front, rear, left, right = self.db.get_setbacks("IN-MH", road_width_m=25.0)
        assert front == 9.0
        assert rear == 4.5

    def test_mumbai_highway(self):
        front, rear, left, right = self.db.get_setbacks("greater mumbai", road_width_m=35.0)
        assert front == 12.0
        assert left == 6.0

    def test_mumbai_unknown_road(self):
        front, rear, left, right = self.db.get_setbacks("mumbai", road_width_m=None)
        assert front == 3.0   # default for unknown road width


class TestSetbackDBPune:
    db = SetbackDB()

    def test_pune_narrow_road(self):
        front, rear, left, right = self.db.get_setbacks("pune", road_width_m=7.0)
        assert front == 3.0

    def test_pune_local_road(self):
        front, rear, left, right = self.db.get_setbacks("IN-MH-PUN", road_width_m=10.0)
        assert front == 4.5

    def test_pune_arterial_road(self):
        front, rear, left, right = self.db.get_setbacks("pune", road_width_m=20.0)
        assert front == 9.0

    def test_pimpri_alias(self):
        front, rear, left, right = self.db.get_setbacks("pimpri", road_width_m=7.0)
        assert front == 3.0  # same as Pune


class TestSetbackDBBangalore:
    db = SetbackDB()

    def test_bangalore_narrow_road(self):
        front, rear, left, right = self.db.get_setbacks("bangalore", road_width_m=6.0)
        assert front == 2.0
        assert left == 1.2

    def test_bengaluru_alias(self):
        front, rear, left, right = self.db.get_setbacks("bengaluru", road_width_m=6.0)
        assert front == 2.0

    def test_bangalore_collector_road(self):
        front, rear, left, right = self.db.get_setbacks("IN-KA", road_width_m=15.0)
        assert front == 4.5
        assert left == pytest.approx(2.25)

    def test_bangalore_arterial_road(self):
        front, rear, left, right = self.db.get_setbacks("bangalore", road_width_m=22.0)
        assert front == 6.0

    def test_mysore_alias(self):
        front, rear, left, right = self.db.get_setbacks("mysore", road_width_m=10.0)
        assert front == 3.0


class TestSetbackDBGenericIndia:
    db = SetbackDB()

    def test_india_generic_fallback(self):
        front, rear, left, right = self.db.get_setbacks("india", road_width_m=7.0)
        assert front == 2.5

    def test_in_code_alias(self):
        front, rear, left, right = self.db.get_setbacks("IN", road_width_m=10.0)
        assert front == 3.0

    def test_unknown_india_city_falls_back_to_IN(self):
        # e.g. "IN-GJ" (Gujarat) — not in table, should fall back to "IN"
        front, rear, left, right = self.db.get_setbacks("IN-GJ", road_width_m=7.0)
        assert front == 2.5   # IN generic narrow


class TestGuessFirstTable:
    def test_in_prefix_gives_india_defaults(self):
        table = _guess_fallback_table("IN-GJ")
        assert "narrow" in table
        # India generic narrow setback
        assert table["narrow"].front == 2.5

    def test_np_prefix_gives_nepal_defaults(self):
        table = _guess_fallback_table("NP-LAL")
        assert table["narrow"].front == 1.5

    def test_unknown_prefix_gives_nepal(self):
        table = _guess_fallback_table("US-CA")
        assert table["narrow"].front == 1.5   # Nepal default


class TestSetbackDBSupportedCities:
    db = SetbackDB()

    def test_india_cities_in_supported_list(self):
        cities = self.db.supported_cities()
        assert "IN-MH" in cities
        assert "IN-MH-PUN" in cities
        assert "IN-KA" in cities
        assert "IN" in cities

    def test_nepal_cities_still_present(self):
        cities = self.db.supported_cities()
        assert "NP-KTM" in cities
        assert "NP-PKR" in cities


# ---------------------------------------------------------------------------
# India extractor functions
# ---------------------------------------------------------------------------


class TestExtractFsiZone:
    def test_r1_from_text(self):
        assert extract_fsi_zone("This plot is in R1 zone") == "R1"

    def test_r2_from_text(self):
        assert extract_fsi_zone("R2 residential zone") == "R2"

    def test_c1_from_text(self):
        assert extract_fsi_zone("neighbourhood commercial C1") == "C1"

    def test_c2_from_text(self):
        assert extract_fsi_zone("C2 major commercial area") == "C2"

    def test_mixed_use(self):
        assert extract_fsi_zone("mixed use development") == "mixed"

    def test_unknown(self):
        assert extract_fsi_zone("not sure about zone") == "unknown"

    def test_r1_case_insensitive(self):
        assert extract_fsi_zone("r1 low density") == "R1"

    def test_residential_1_text(self):
        assert extract_fsi_zone("residential 1 zone") == "R1"


class TestExtractUnitPreference:
    def test_sqft(self):
        assert extract_unit_preference("I prefer sq ft") == "sqft"

    def test_square_feet(self):
        assert extract_unit_preference("show me in square feet") == "sqft"

    def test_sqm_default(self):
        assert extract_unit_preference("sq m please") == "sqm"

    def test_metric_default(self):
        assert extract_unit_preference("metric system") == "sqm"

    def test_feet_keyword(self):
        assert extract_unit_preference("feet and inches") == "sqft"


class TestExtractBasementParking:
    def test_yes_with_count(self):
        result = extract_basement_parking("yes, 2 cars in basement")
        assert result["required"] is True
        assert result["car_count"] == 2

    def test_no_basement(self):
        result = extract_basement_parking("no basement parking")
        assert result["required"] is False
        assert result["car_count"] == 0

    def test_stilt_parking(self):
        result = extract_basement_parking("stilt parking for 1 car")
        assert result["required"] is True
        assert result["car_count"] == 1

    def test_underground_3_vehicles(self):
        result = extract_basement_parking("underground parking for 3 vehicles")
        assert result["required"] is True
        assert result["car_count"] == 3

    def test_no_keyword(self):
        result = extract_basement_parking("not needed")
        assert result["required"] is False


class TestExtractReraApplicable:
    def test_yes_rera(self):
        assert extract_rera_applicable("yes, RERA required") is True

    def test_rera_keyword(self):
        assert extract_rera_applicable("RERA compliance needed") is True

    def test_not_applicable(self):
        assert extract_rera_applicable("not applicable, small project") is False

    def test_na(self):
        assert extract_rera_applicable("n/a") is False

    def test_default_true(self):
        # No clear answer → default to True (safe choice)
        assert extract_rera_applicable("don't know") is True


class TestExtractIndiaStyle:
    def test_south_indian(self):
        assert extract_india_style("South Indian traditional") == "south_indian"

    def test_kerala_style(self):
        assert extract_india_style("Kerala vernacular") == "south_indian"

    def test_contemporary(self):
        assert extract_india_style("contemporary Indo-modern") == "contemporary"

    def test_fusion(self):
        assert extract_india_style("fusion style") == "contemporary"

    def test_traditional_mughal(self):
        assert extract_india_style("Mughal inspired traditional") == "traditional"

    def test_minimal(self):
        assert extract_india_style("minimal clean lines") == "minimal"

    def test_default_modern(self):
        assert extract_india_style("any style is fine") == "modern"


# ---------------------------------------------------------------------------
# StylePreference enum values
# ---------------------------------------------------------------------------


class TestStylePreferenceEnum:
    def test_contemporary_exists(self):
        assert StylePreference.CONTEMPORARY == "contemporary"

    def test_south_indian_exists(self):
        assert StylePreference.SOUTH_INDIAN == "south_indian"

    def test_existing_values_unchanged(self):
        assert StylePreference.MODERN == "modern"
        assert StylePreference.NEWARI == "newari"


# ---------------------------------------------------------------------------
# India questions registered in QUESTIONS list
# ---------------------------------------------------------------------------


class TestIndiaQuestionsRegistered:
    def test_fsi_zone_question_exists(self):
        assert "india_fsi_zone" in QUESTION_BY_ID

    def test_unit_preference_question_exists(self):
        assert "india_unit_preference" in QUESTION_BY_ID

    def test_basement_parking_question_exists(self):
        assert "india_basement_parking" in QUESTION_BY_ID

    def test_rera_question_exists(self):
        assert "india_rera_applicable" in QUESTION_BY_ID

    def test_sunken_slab_question_exists(self):
        assert "india_sunken_slab" in QUESTION_BY_ID

    def test_india_questions_have_correct_phase(self):
        india_qs = [q for q in QUESTIONS if q.phase == "india_specific"]
        assert len(india_qs) >= 5

    def test_india_questions_are_optional(self):
        india_qs = [q for q in QUESTIONS if q.phase == "india_specific"]
        for q in india_qs:
            assert q.required is False, f"Question {q.id} should be optional"

    def test_fsi_zone_has_extractor(self):
        q = QUESTION_BY_ID["india_fsi_zone"]
        assert q.extractor is not None
        assert q.extractor("R1 zone") == "R1"


# ---------------------------------------------------------------------------
# Rule compiler — loads IN-MH rules from rules_india.json
# ---------------------------------------------------------------------------


class TestRuleCompilerIndia:
    def test_load_rules_for_in_mh(self):
        from civilengineer.knowledge.rule_compiler import load_rules

        rule_set = load_rules(jurisdiction="IN-MH")
        assert rule_set.jurisdiction == "IN-MH"
        assert len(rule_set.rules) > 0

    def test_in_mh_rules_have_correct_jurisdiction(self):
        from civilengineer.knowledge.rule_compiler import load_rules

        rule_set = load_rules(jurisdiction="IN-MH")
        for rule in rule_set.rules:
            assert rule.jurisdiction == "IN-MH"

    def test_in_mh_rules_contain_area_rules(self):
        from civilengineer.knowledge.rule_compiler import load_rules

        rule_set = load_rules(jurisdiction="IN-MH")
        area_rules = [r for r in rule_set.rules if r.category.value == "area"]
        assert len(area_rules) > 0

    def test_in_mh_has_bedroom_min_area(self):
        from civilengineer.knowledge.rule_compiler import load_rules

        rule_set = load_rules(jurisdiction="IN-MH")
        bedroom_rules = [
            r for r in rule_set.rules
            if "bedroom" in r.applies_to and r.rule_type == "min_area"
        ]
        assert len(bedroom_rules) > 0
        areas = [r.numeric_value for r in bedroom_rules]
        assert any(v is not None and v >= 9.0 for v in areas)

    def test_in_mh_has_far_rules(self):
        from civilengineer.knowledge.rule_compiler import load_rules

        rule_set = load_rules(jurisdiction="IN-MH")
        far_rules = [r for r in rule_set.rules if r.rule_type == "max_far"]
        assert len(far_rules) >= 2  # R1 and R2 zones

    def test_in_mh_code_version_is_nbc_2016(self):
        from civilengineer.knowledge.rule_compiler import load_rules

        rule_set = load_rules(jurisdiction="IN-MH")
        assert rule_set.code_version == "NBC_2016"

    def test_rules_path_for_in_jurisdiction(self):
        from civilengineer.knowledge.rule_compiler import _rules_path_for_jurisdiction

        path = _rules_path_for_jurisdiction("IN-MH")
        assert path.exists()
        assert "rules_india" in path.name

    def test_rules_path_for_np_jurisdiction(self):
        from civilengineer.knowledge.rule_compiler import _rules_path_for_jurisdiction

        path = _rules_path_for_jurisdiction("NP-KTM")
        assert path.exists()
        assert "rules.json" in path.name

    def test_rules_path_fallback_for_unknown(self):
        from civilengineer.knowledge.rule_compiler import _rules_path_for_jurisdiction

        # Unknown jurisdiction → falls back to rules.json (Nepal)
        path = _rules_path_for_jurisdiction("US-CA")
        assert path.exists()
        assert "rules.json" in path.name

    def test_load_rules_no_jurisdiction_loads_nepal(self):
        from civilengineer.knowledge.rule_compiler import load_rules

        rule_set = load_rules()
        assert rule_set.jurisdiction == "NP-KTM"

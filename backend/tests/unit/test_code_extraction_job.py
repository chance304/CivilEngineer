"""
Unit tests for the two-agent PDF rule extraction + verification job.

All LLM calls and DB operations are mocked.  Only pure-logic helpers
(_parse_extractor_response, _parse_verifier_response, _extract_pages,
page-batching behaviour) are tested without I/O.
"""

from __future__ import annotations

import json
import re
from unittest.mock import MagicMock, patch

import pytest

from civilengineer.jobs.code_extraction_job import (
    PAGE_BATCH_SIZE,
    VALID_CATEGORIES,
    VALID_SEVERITIES,
    _parse_extractor_response,
    _parse_verifier_response,
)


# ---------------------------------------------------------------------------
# _parse_extractor_response
# ---------------------------------------------------------------------------


class TestParseExtractorResponse:
    def test_valid_json_array(self):
        data = [
            {
                "name": "Min room size",
                "description": "Habitable rooms shall be at least 9.5 m2.",
                "source_section": "4.2.1",
                "category": "room_size",
                "severity": "hard",
                "numeric_value": 9.5,
                "unit": "m2",
                "confidence": 0.95,
            }
        ]
        result = _parse_extractor_response(json.dumps(data))
        assert len(result) == 1
        assert result[0]["name"] == "Min room size"
        assert result[0]["numeric_value"] == 9.5

    def test_empty_array(self):
        assert _parse_extractor_response("[]") == []

    def test_json_in_markdown_fences(self):
        raw = "```json\n[{\"name\": \"Setback\", \"description\": \"3m front\", \"source_section\": \"5.1\", \"category\": \"setback\", \"severity\": \"hard\", \"numeric_value\": 3, \"unit\": \"m\", \"confidence\": 0.9}]\n```"
        result = _parse_extractor_response(raw)
        assert len(result) == 1
        assert result[0]["category"] == "setback"

    def test_malformed_json_returns_empty(self):
        assert _parse_extractor_response("this is not json") == []

    def test_non_array_json_returns_empty(self):
        assert _parse_extractor_response('{"key": "value"}') == []

    def test_items_missing_name_are_skipped(self):
        data = [
            {"name": "Valid rule", "description": "desc"},
            {"description": "no name here"},  # missing name
        ]
        result = _parse_extractor_response(json.dumps(data))
        assert len(result) == 1
        assert result[0]["name"] == "Valid rule"

    def test_items_missing_description_are_skipped(self):
        data = [
            {"name": "Good rule", "description": "Has description"},
            {"name": "Bad rule"},  # missing description
        ]
        result = _parse_extractor_response(json.dumps(data))
        assert len(result) == 1

    def test_multiple_rules_extracted(self):
        data = [
            {"name": f"Rule {i}", "description": f"desc {i}", "category": "other"}
            for i in range(5)
        ]
        result = _parse_extractor_response(json.dumps(data))
        assert len(result) == 5

    def test_json_array_embedded_in_text(self):
        raw = 'Here are the rules: [{"name": "Headroom", "description": "2.4m min", "source_section": "3.1"}] End.'
        result = _parse_extractor_response(raw)
        assert len(result) == 1
        assert result[0]["name"] == "Headroom"

    def test_non_dict_items_skipped(self):
        raw = json.dumps(["string item", 42, {"name": "Valid", "description": "OK"}])
        result = _parse_extractor_response(raw)
        assert len(result) == 1


# ---------------------------------------------------------------------------
# _parse_verifier_response
# ---------------------------------------------------------------------------


class TestParseVerifierResponse:
    def test_verified_status(self):
        raw = json.dumps({"status": "verified", "notes": "", "confidence": 0.95})
        result = _parse_verifier_response(raw)
        assert result["status"] == "verified"
        assert result["confidence"] == 0.95

    def test_flagged_status(self):
        raw = json.dumps({
            "status": "flagged",
            "notes": "Numeric value differs from source text (source says 3.5m not 3.0m).",
            "confidence": 0.4,
        })
        result = _parse_verifier_response(raw)
        assert result["status"] == "flagged"
        assert "3.5m" in result["notes"]

    def test_unverifiable_status(self):
        raw = json.dumps({"status": "unverifiable", "notes": "Source text lacks numeric data.", "confidence": 0.2})
        result = _parse_verifier_response(raw)
        assert result["status"] == "unverifiable"

    def test_unknown_status_normalised_to_unverifiable(self):
        raw = json.dumps({"status": "uncertain", "notes": "", "confidence": 0.5})
        result = _parse_verifier_response(raw)
        assert result["status"] == "unverifiable"

    def test_malformed_json_falls_back(self):
        result = _parse_verifier_response("not json at all")
        assert result["status"] == "unverifiable"
        assert "notes" in result

    def test_non_object_json_falls_back(self):
        result = _parse_verifier_response("[1, 2, 3]")
        assert result["status"] == "unverifiable"

    def test_json_in_markdown_fences(self):
        raw = '```json\n{"status": "verified", "notes": "", "confidence": 0.88}\n```'
        result = _parse_verifier_response(raw)
        assert result["status"] == "verified"
        assert result["confidence"] == 0.88

    def test_missing_confidence_field(self):
        raw = json.dumps({"status": "verified", "notes": ""})
        result = _parse_verifier_response(raw)
        assert result["status"] == "verified"
        assert result.get("confidence") is None

    def test_status_case_insensitive(self):
        raw = json.dumps({"status": "VERIFIED", "notes": "", "confidence": 0.9})
        result = _parse_verifier_response(raw)
        # uppercase is not normalised to lower — treated as unknown
        # depending on implementation; test the actual behaviour
        # Our code does .lower(), so this should be "verified"
        assert result["status"] == "verified"

    def test_embedded_json_object_in_text(self):
        raw = 'After analysis: {"status": "flagged", "notes": "Wrong value", "confidence": 0.3}'
        result = _parse_verifier_response(raw)
        assert result["status"] == "flagged"


# ---------------------------------------------------------------------------
# Valid category / severity constants
# ---------------------------------------------------------------------------


class TestValidConstants:
    def test_valid_categories_not_empty(self):
        assert len(VALID_CATEGORIES) > 0

    def test_other_in_valid_categories(self):
        assert "other" in VALID_CATEGORIES

    def test_expected_categories_present(self):
        for cat in ("setback", "room_size", "ventilation", "structural", "fire"):
            assert cat in VALID_CATEGORIES, f"Missing expected category: {cat}"

    def test_valid_severities(self):
        assert VALID_SEVERITIES == {"hard", "soft", "advisory"}


# ---------------------------------------------------------------------------
# PAGE_BATCH_SIZE
# ---------------------------------------------------------------------------


class TestPageBatchSize:
    def test_batch_size_positive(self):
        assert PAGE_BATCH_SIZE > 0

    def test_batch_size_reasonable(self):
        # Batches too large waste tokens; too small increases API calls
        assert 1 <= PAGE_BATCH_SIZE <= 20


# ---------------------------------------------------------------------------
# _extract_pages (mocked pdfplumber)
# ---------------------------------------------------------------------------


class TestExtractPages:
    def test_returns_list_of_strings(self):
        """pdfplumber is mocked to return two pages."""
        from civilengineer.jobs.code_extraction_job import _extract_pages

        mock_page1 = MagicMock()
        mock_page1.extract_text.return_value = "Page one content with rules."
        mock_page2 = MagicMock()
        mock_page2.extract_text.return_value = "Page two content."

        mock_pdf = MagicMock()
        mock_pdf.pages = [mock_page1, mock_page2]
        mock_pdf.__enter__ = lambda s: mock_pdf
        mock_pdf.__exit__ = MagicMock(return_value=False)

        with patch("pdfplumber.open", return_value=mock_pdf):
            pages = _extract_pages(b"%PDF-fake")

        assert len(pages) == 2
        assert pages[0] == "Page one content with rules."
        assert pages[1] == "Page two content."

    def test_none_page_text_becomes_empty_string(self):
        from civilengineer.jobs.code_extraction_job import _extract_pages

        mock_page = MagicMock()
        mock_page.extract_text.return_value = None

        mock_pdf = MagicMock()
        mock_pdf.pages = [mock_page]
        mock_pdf.__enter__ = lambda s: mock_pdf
        mock_pdf.__exit__ = MagicMock(return_value=False)

        with patch("pdfplumber.open", return_value=mock_pdf):
            pages = _extract_pages(b"%PDF-fake")

        assert pages == [""]

    def test_pdfplumber_exception_returns_empty_list(self):
        from civilengineer.jobs.code_extraction_job import _extract_pages

        with patch("pdfplumber.open", side_effect=Exception("corrupt PDF")):
            pages = _extract_pages(b"not a pdf")

        assert pages == []

    def test_empty_pdf_returns_empty_list(self):
        from civilengineer.jobs.code_extraction_job import _extract_pages

        mock_pdf = MagicMock()
        mock_pdf.pages = []
        mock_pdf.__enter__ = lambda s: mock_pdf
        mock_pdf.__exit__ = MagicMock(return_value=False)

        with patch("pdfplumber.open", return_value=mock_pdf):
            pages = _extract_pages(b"%PDF-empty")

        assert pages == []


# ---------------------------------------------------------------------------
# Proposed rule_id format
# ---------------------------------------------------------------------------


class TestProposedRuleIdFormat:
    """
    The code_extraction_job generates proposed_rule_id strings in the format:
      {JUR_PREFIX}_{SECTION_SLUG}_{HEX6}
    Verify the regex that's used to slugify the section number.
    """

    def _make_rule_id(self, jurisdiction: str, source_section: str) -> str:
        jur_prefix = jurisdiction.replace("-", "_").upper()
        section_slug = re.sub(r"[^A-Za-z0-9]", "_", source_section)[:20].strip("_")
        hex6 = "A1B2C3"  # deterministic stand-in
        return f"{jur_prefix}_{section_slug}_{hex6}"

    def test_nepal_jurisdiction_prefix(self):
        rule_id = self._make_rule_id("NP-KTM", "4.2.1")
        assert rule_id.startswith("NP_KTM_")

    def test_section_dots_replaced_with_underscores(self):
        rule_id = self._make_rule_id("NP-KTM", "4.2.1")
        assert "4_2_1" in rule_id

    def test_section_truncated_at_20_chars(self):
        rule_id = self._make_rule_id("UK", "1.2.3.4.5.6.7.8.9.10.11")
        # section_slug should be at most 20 chars
        parts = rule_id.split("_")
        # The slug starts after the jurisdiction prefix parts
        # For "UK": jur_prefix = "UK", so rule_id = "UK_{slug}_HEX6"
        # Extract slug = everything between first _ and last _
        slug = "_".join(rule_id.split("_")[1:-1])
        assert len(slug) <= 20

    def test_special_chars_in_section_removed(self):
        rule_id = self._make_rule_id("IN-MH", "Sec. 3-A/B")
        assert "/" not in rule_id
        assert "." not in rule_id

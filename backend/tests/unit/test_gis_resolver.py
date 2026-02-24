"""
Unit tests for the GIS module.

All httpx network calls are mocked — no real Nominatim requests are made.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from httpx import TimeoutException

from civilengineer.gis.jurisdiction_map import (
    JurisdictionMatch,
    resolve_jurisdiction,
)
from civilengineer.gis.nominatim import NominatimError, reverse_geocode


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_response(data: dict, status_code: int = 200) -> MagicMock:
    """Build a fake httpx Response-like object."""
    mock = MagicMock()
    mock.status_code = status_code
    mock.json.return_value = data
    mock.text = str(data)
    return mock


# ---------------------------------------------------------------------------
# TestNominatimClient (5 tests)
# ---------------------------------------------------------------------------

class TestNominatimClient:
    @pytest.mark.asyncio
    async def test_success_returns_flattened_address(self):
        response_data = {
            "display_name": "Kathmandu, Bagmati Province, Nepal",
            "address": {
                "city": "Kathmandu",
                "state": "Bagmati Province",
                "country": "Nepal",
                "country_code": "np",
            },
        }
        mock_resp = _mock_response(response_data)
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_resp)

        with patch("civilengineer.gis.nominatim.httpx.AsyncClient", return_value=mock_client):
            result = await reverse_geocode(27.7172, 85.3240)

        assert result["city"] == "Kathmandu"
        assert result["country_code"] == "np"
        assert result["display_name"] == "Kathmandu, Bagmati Province, Nepal"

    @pytest.mark.asyncio
    async def test_timeout_raises_nominatim_error(self):
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(side_effect=TimeoutException("timeout"))

        with patch("civilengineer.gis.nominatim.httpx.AsyncClient", return_value=mock_client):
            with pytest.raises(NominatimError, match="timed out"):
                await reverse_geocode(27.7172, 85.3240)

    @pytest.mark.asyncio
    async def test_http_error_status_raises_nominatim_error(self):
        mock_resp = _mock_response({}, status_code=503)
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_resp)

        with patch("civilengineer.gis.nominatim.httpx.AsyncClient", return_value=mock_client):
            with pytest.raises(NominatimError, match="HTTP 503"):
                await reverse_geocode(27.7172, 85.3240)

    @pytest.mark.asyncio
    async def test_error_key_in_body_raises_nominatim_error(self):
        response_data = {"error": "Unable to geocode"}
        mock_resp = _mock_response(response_data)
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_resp)

        with patch("civilengineer.gis.nominatim.httpx.AsyncClient", return_value=mock_client):
            with pytest.raises(NominatimError, match="Unable to geocode"):
                await reverse_geocode(0.0, 0.0)

    @pytest.mark.asyncio
    async def test_display_name_present_in_result(self):
        response_data = {
            "display_name": "Pokhara, Gandaki Province, Nepal",
            "address": {"city": "Pokhara", "state": "Gandaki Province", "country_code": "np"},
        }
        mock_resp = _mock_response(response_data)
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_resp)

        with patch("civilengineer.gis.nominatim.httpx.AsyncClient", return_value=mock_client):
            result = await reverse_geocode(28.2096, 83.9856)

        assert result["display_name"] == "Pokhara, Gandaki Province, Nepal"


# ---------------------------------------------------------------------------
# TestJurisdictionMap (22 tests)
# ---------------------------------------------------------------------------

class TestJurisdictionMap:
    # City-level — Nepal
    def test_kathmandu_city(self):
        m = resolve_jurisdiction("np", "Bagmati Province", "Kathmandu")
        assert m.jurisdiction == "NP-KTM"
        assert m.version == "NBC_2020_KTM"
        assert m.local_body == "KMC"
        assert m.confidence == 1.0
        assert m.match_level == "city"

    def test_lalitpur_city(self):
        m = resolve_jurisdiction("np", "Bagmati Province", "Lalitpur")
        assert m.jurisdiction == "NP-LAL"
        assert m.local_body == "LLMC"
        assert m.confidence == 1.0

    def test_bhaktapur_city(self):
        m = resolve_jurisdiction("np", "Bagmati Province", "Bhaktapur")
        assert m.jurisdiction == "NP-BKT"
        assert m.local_body == "BkMC"

    def test_kirtipur_city(self):
        m = resolve_jurisdiction("np", "Bagmati Province", "Kirtipur")
        assert m.jurisdiction == "NP-KTM"

    def test_pokhara_city(self):
        m = resolve_jurisdiction("np", "Gandaki Province", "Pokhara")
        assert m.jurisdiction == "NP-PKR"
        assert m.version == "NBC_2020_PKR"
        assert m.local_body == "PMC"

    # City-level — India Maharashtra
    def test_pune_city(self):
        m = resolve_jurisdiction("in", "Maharashtra", "Pune")
        assert m.jurisdiction == "IN-MH-PUN"
        assert m.local_body == "PMC"

    def test_pimpri_city(self):
        m = resolve_jurisdiction("in", "Maharashtra", "Pimpri-Chinchwad")
        assert m.jurisdiction == "IN-MH-PUN"
        assert m.local_body == "PCMC"

    def test_nashik_city(self):
        m = resolve_jurisdiction("in", "Maharashtra", "Nashik")
        assert m.jurisdiction == "IN-MH"
        assert m.local_body == "NMC"

    def test_nagpur_city(self):
        m = resolve_jurisdiction("in", "Maharashtra", "Nagpur")
        assert m.jurisdiction == "IN-MH"

    def test_mumbai_city(self):
        m = resolve_jurisdiction("in", "Maharashtra", "Mumbai")
        assert m.jurisdiction == "IN-MH"
        assert m.local_body == "MCGM"

    # City-level — India Karnataka
    def test_bengaluru_city(self):
        m = resolve_jurisdiction("in", "Karnataka", "Bengaluru")
        assert m.jurisdiction == "IN-KA"
        assert m.local_body == "BBMP"

    def test_bangalore_alias(self):
        m = resolve_jurisdiction("in", "Karnataka", "Bangalore")
        assert m.jurisdiction == "IN-KA"

    def test_mysuru_city(self):
        m = resolve_jurisdiction("in", "Karnataka", "Mysuru")
        assert m.jurisdiction == "IN-KA"
        assert m.local_body == "MCC"

    def test_mysore_alias(self):
        m = resolve_jurisdiction("in", "Karnataka", "Mysore")
        assert m.jurisdiction == "IN-KA"

    # City-level — India other
    def test_delhi_city(self):
        m = resolve_jurisdiction("in", "Delhi", "Delhi")
        assert m.jurisdiction == "IN"
        assert m.local_body == "DDA"

    def test_chennai_city(self):
        m = resolve_jurisdiction("in", "Tamil Nadu", "Chennai")
        assert m.jurisdiction == "IN"
        assert m.local_body == "GCC"

    def test_hyderabad_city(self):
        m = resolve_jurisdiction("in", "Telangana", "Hyderabad")
        assert m.jurisdiction == "IN"
        assert m.local_body == "GHMC"

    def test_ahmedabad_city(self):
        m = resolve_jurisdiction("in", "Gujarat", "Ahmedabad")
        assert m.jurisdiction == "IN"
        assert m.local_body == "AMC"

    # State-level
    def test_bagmati_state_fallback(self):
        m = resolve_jurisdiction("np", "Bagmati Province", "SomeUnknownTown")
        assert m.jurisdiction == "NP-KTM"
        assert m.match_level == "state"
        assert m.confidence == 0.85

    def test_maharashtra_state_fallback(self):
        m = resolve_jurisdiction("in", "Maharashtra", "SomeUnknownCity")
        assert m.jurisdiction == "IN-MH"
        assert m.match_level == "state"

    # Country-level
    def test_nepal_country_fallback(self):
        m = resolve_jurisdiction("np", "Karnali Province", "SomeCity")
        assert m.jurisdiction == "NP"
        assert m.match_level == "country"
        assert m.confidence == 0.65

    def test_uk_country(self):
        m = resolve_jurisdiction("gb", "England", "London")
        assert m.jurisdiction == "UK"
        assert m.version == "BR_2023"
        assert m.match_level == "country"

    def test_case_insensitivity(self):
        m1 = resolve_jurisdiction("NP", "BAGMATI PROVINCE", "KATHMANDU")
        m2 = resolve_jurisdiction("np", "bagmati province", "kathmandu")
        assert m1.jurisdiction == m2.jurisdiction == "NP-KTM"

    def test_fallback_unknown_country(self):
        m = resolve_jurisdiction("zz", "SomeState", "SomeCity")
        assert m.jurisdiction == "NP-KTM"
        assert m.match_level == "fallback"
        assert m.confidence == 0.40


# ---------------------------------------------------------------------------
# TestResolveJurisdictionEndpoint (4 tests)
# ---------------------------------------------------------------------------

class TestResolveJurisdictionEndpoint:
    """Integration tests against the FastAPI router (no real HTTP)."""

    @pytest.fixture
    def client(self):
        from civilengineer.api.app import app
        return TestClient(app, raise_server_exceptions=False)

    def test_happy_path_kathmandu(self, client: TestClient):
        geocode_result = {
            "display_name": "Kathmandu, Bagmati Province, Nepal",
            "city": "Kathmandu",
            "state": "Bagmati Province",
            "country": "Nepal",
            "country_code": "np",
        }
        with patch(
            "civilengineer.api.routers.gis.reverse_geocode",
            new=AsyncMock(return_value=geocode_result),
        ):
            resp = client.get("/api/v1/gis/resolve-jurisdiction?lat=27.7172&lon=85.3240")

        assert resp.status_code == 200
        data = resp.json()
        assert data["jurisdiction"] == "NP-KTM"
        assert data["confidence"] == 1.0
        assert data["match_level"] == "city"
        assert data["local_body"] == "KMC"

    def test_502_on_nominatim_error(self, client: TestClient):
        with patch(
            "civilengineer.api.routers.gis.reverse_geocode",
            new=AsyncMock(side_effect=NominatimError("timeout")),
        ):
            resp = client.get("/api/v1/gis/resolve-jurisdiction?lat=27.7172&lon=85.3240")

        assert resp.status_code == 502

    def test_422_on_invalid_lat(self, client: TestClient):
        resp = client.get("/api/v1/gis/resolve-jurisdiction?lat=200&lon=85")
        assert resp.status_code == 422

    def test_422_on_invalid_lon(self, client: TestClient):
        resp = client.get("/api/v1/gis/resolve-jurisdiction?lat=27&lon=200")
        assert resp.status_code == 422

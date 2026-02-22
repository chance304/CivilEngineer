"""
Integration tests for admin building code API endpoints.

POST   /admin/building-codes/upload
GET    /admin/building-codes
GET    /admin/building-codes/{doc_id}/rules
PUT    /admin/building-codes/{doc_id}/rules/{rule_id}
POST   /admin/building-codes/{doc_id}/activate

Uses in-memory SQLite (aiosqlite) — no PostgreSQL or real S3 required.
S3 operations are mocked.
"""

from __future__ import annotations

import io
import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlmodel import SQLModel

from civilengineer.api.app import create_app
from civilengineer.auth.password import hash_password
from civilengineer.db.models import (
    BuildingCodeDocumentModel,
    ExtractedRuleModel,
    FirmModel,
    UserModel,
)
from civilengineer.db.session import get_session

# ---------------------------------------------------------------------------
# In-memory test database (SQLite)
# ---------------------------------------------------------------------------

TEST_DB_URL = "sqlite+aiosqlite:///:memory:"
test_engine = create_async_engine(TEST_DB_URL, connect_args={"check_same_thread": False})
TestSessionLocal = async_sessionmaker(
    bind=test_engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


async def override_get_session():
    async with TestSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


# ---------------------------------------------------------------------------
# Seed data constants
# ---------------------------------------------------------------------------

FIRM_ID = f"firm_{uuid.uuid4().hex[:8]}"
ADMIN_ID = f"usr_{uuid.uuid4().hex[:8]}"
ENGINEER_ID = f"usr_{uuid.uuid4().hex[:8]}"
ADMIN_EMAIL = f"admin_{uuid.uuid4().hex[:4]}@buildtest.ai"
ENGINEER_EMAIL = f"eng_{uuid.uuid4().hex[:4]}@buildtest.ai"
PASSWORD = "Test1234!"

DOC_ID = str(uuid.uuid4())
EXT_RULE_ID = str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture(scope="module")
async def seed_db():
    """Create tables, seed firm + admin + engineer + one document + one extracted rule."""
    async with test_engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)

    async with TestSessionLocal() as session:
        firm = FirmModel(
            firm_id=FIRM_ID,
            name="Test Firm",
            country="NP",
            default_jurisdiction="NP-KTM",
            plan="professional",
            settings={},
        )
        admin_user = UserModel(
            user_id=ADMIN_ID,
            firm_id=FIRM_ID,
            email=ADMIN_EMAIL,
            full_name="Admin User",
            hashed_password=hash_password(PASSWORD),
            role="firm_admin",
            is_active=True,
        )
        eng_user = UserModel(
            user_id=ENGINEER_ID,
            firm_id=FIRM_ID,
            email=ENGINEER_EMAIL,
            full_name="Engineer User",
            hashed_password=hash_password(PASSWORD),
            role="engineer",
            is_active=True,
        )
        # Pre-existing document in "review" status
        doc = BuildingCodeDocumentModel(
            doc_id=DOC_ID,
            firm_id=FIRM_ID,
            jurisdiction="NP-KTM",
            code_name="NBC 205:2020",
            code_version="NBC_2020",
            uploaded_by=ADMIN_ID,
            s3_key=f"{FIRM_ID}/{DOC_ID}/nbc.pdf",
            status="review",
            rules_extracted=1,
            rules_approved=0,
        )
        # Pre-existing extracted rule (pending review)
        ext_rule = ExtractedRuleModel(
            extracted_rule_id=EXT_RULE_ID,
            doc_id=DOC_ID,
            jurisdiction="NP-KTM",
            proposed_rule_id="NP_KTM_AREA_SEED_001",
            name="Min master bedroom area",
            description="Master bedroom ≥ 10.5 sqm.",
            source_section="§5.1.2(a)",
            source_page=14,
            source_text="The master bedroom shall have a minimum floor area of 10.5 sqm.",
            category="area",
            severity="hard",
            numeric_value=10.5,
            unit="sqm",
            confidence=0.95,
            reviewer_approved=None,
        )

        session.add_all([firm, admin_user, eng_user, doc, ext_rule])
        await session.commit()

    yield  # tests run here

    async with test_engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.drop_all)


@pytest_asyncio.fixture(scope="module")
async def app(seed_db):
    application = create_app()
    application.dependency_overrides[get_session] = override_get_session
    return application


@pytest_asyncio.fixture(scope="module")
async def admin_token(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/api/v1/auth/login",
            json={"email": ADMIN_EMAIL, "password": PASSWORD},
        )
        assert resp.status_code == 200, resp.text
        return resp.json()["access_token"]


@pytest_asyncio.fixture(scope="module")
async def engineer_token(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/api/v1/auth/login",
            json={"email": ENGINEER_EMAIL, "password": PASSWORD},
        )
        assert resp.status_code == 200, resp.text
        return resp.json()["access_token"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# POST /admin/building-codes/upload
# ---------------------------------------------------------------------------

class TestUploadBuildingCode:

    @pytest.mark.asyncio
    async def test_upload_pdf_success(self, app, admin_token):
        """Admin can upload a PDF; a document record is created."""
        pdf_bytes = b"%PDF-1.4 fake pdf content"

        with (
            patch("civilengineer.api.routers.admin.s3_backend.ensure_bucket_exists"),
            patch("civilengineer.api.routers.admin.s3_backend.upload_bytes"),
        ):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.post(
                    "/api/v1/admin/building-codes/upload"
                    "?jurisdiction=NP-KTM&code_name=NBC+205%3A2020&code_version=NBC_2020",
                    headers=_auth(admin_token),
                    files={"file": ("nbc.pdf", pdf_bytes, "application/pdf")},
                )

        assert resp.status_code == 201, resp.text
        data = resp.json()
        assert data["jurisdiction"] == "NP-KTM"
        assert data["code_version"] == "NBC_2020"
        assert data["status"] == "uploaded"
        assert data["firm_id"] == FIRM_ID

    @pytest.mark.asyncio
    async def test_upload_requires_auth(self, app):
        """Unauthenticated request gets 401."""
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/api/v1/admin/building-codes/upload"
                "?jurisdiction=NP-KTM&code_name=Test&code_version=TEST",
                files={"file": ("doc.pdf", b"data", "application/pdf")},
            )
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_upload_requires_admin_permission(self, app, engineer_token):
        """Engineer (no BUILDING_CODES permission) gets 403."""
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/api/v1/admin/building-codes/upload"
                "?jurisdiction=NP-KTM&code_name=Test&code_version=TEST",
                headers=_auth(engineer_token),
                files={"file": ("doc.pdf", b"data", "application/pdf")},
            )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_upload_rejects_empty_file(self, app, admin_token):
        """Empty PDF body returns 400."""
        with (
            patch("civilengineer.api.routers.admin.s3_backend.ensure_bucket_exists"),
            patch("civilengineer.api.routers.admin.s3_backend.upload_bytes"),
        ):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.post(
                    "/api/v1/admin/building-codes/upload"
                    "?jurisdiction=NP-KTM&code_name=Test&code_version=TEST",
                    headers=_auth(admin_token),
                    files={"file": ("empty.pdf", b"", "application/pdf")},
                )
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# GET /admin/building-codes
# ---------------------------------------------------------------------------

class TestListBuildingCodes:

    @pytest.mark.asyncio
    async def test_list_returns_documents(self, app, admin_token):
        """Admin sees documents for their firm."""
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(
                "/api/v1/admin/building-codes",
                headers=_auth(admin_token),
            )
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert any(d["doc_id"] == DOC_ID for d in data)

    @pytest.mark.asyncio
    async def test_list_filtered_by_jurisdiction(self, app, admin_token):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(
                "/api/v1/admin/building-codes?jurisdiction=US-CA",
                headers=_auth(admin_token),
            )
        assert resp.status_code == 200
        data = resp.json()
        # No US-CA documents in test DB
        assert all(d["jurisdiction"] == "US-CA" for d in data)

    @pytest.mark.asyncio
    async def test_list_requires_auth(self, app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/v1/admin/building-codes")
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# GET /admin/building-codes/{doc_id}/rules
# ---------------------------------------------------------------------------

class TestListExtractedRules:

    @pytest.mark.asyncio
    async def test_returns_extracted_rules(self, app, admin_token):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(
                f"/api/v1/admin/building-codes/{DOC_ID}/rules",
                headers=_auth(admin_token),
            )
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert any(r["extracted_rule_id"] == EXT_RULE_ID for r in data)

    @pytest.mark.asyncio
    async def test_filter_pending_only(self, app, admin_token):
        """Rules with reviewer_approved=None show up when no filter is applied."""
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(
                f"/api/v1/admin/building-codes/{DOC_ID}/rules",
                headers=_auth(admin_token),
            )
        assert resp.status_code == 200
        pending = [r for r in resp.json() if r["reviewer_approved"] is None]
        assert len(pending) >= 1

    @pytest.mark.asyncio
    async def test_404_when_doc_not_in_firm(self, app, admin_token):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(
                "/api/v1/admin/building-codes/nonexistent-doc/rules",
                headers=_auth(admin_token),
            )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# PUT /admin/building-codes/{doc_id}/rules/{rule_id}
# ---------------------------------------------------------------------------

class TestReviewExtractedRule:

    @pytest.mark.asyncio
    async def test_approve_rule(self, app, admin_token):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.put(
                f"/api/v1/admin/building-codes/{DOC_ID}/rules/{EXT_RULE_ID}",
                headers=_auth(admin_token),
                json={"approved": True, "notes": "Verified against NBC 2020."},
            )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["reviewer_approved"] is True
        assert data["reviewer_notes"] == "Verified against NBC 2020."
        assert data["reviewed_by"] == ADMIN_ID

    @pytest.mark.asyncio
    async def test_reject_rule(self, app, admin_token):
        # Use a different ext rule for clean rejection test
        async with TestSessionLocal() as session:
            extra = ExtractedRuleModel(
                extracted_rule_id=str(uuid.uuid4()),
                doc_id=DOC_ID,
                jurisdiction="NP-KTM",
                proposed_rule_id="NP_KTM_AREA_REJECT_001",
                name="Rule to reject",
                description="This one gets rejected.",
                source_section="§5.2",
                source_page=15,
                source_text="Some rule text.",
                category="area",
                severity="soft",
                numeric_value=5.0,
                unit="sqm",
                confidence=0.6,
                reviewer_approved=None,
            )
            session.add(extra)
            await session.commit()
            reject_id = extra.extracted_rule_id

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.put(
                f"/api/v1/admin/building-codes/{DOC_ID}/rules/{reject_id}",
                headers=_auth(admin_token),
                json={"approved": False, "notes": "Value seems incorrect."},
            )
        assert resp.status_code == 200
        assert resp.json()["reviewer_approved"] is False

    @pytest.mark.asyncio
    async def test_404_for_unknown_rule(self, app, admin_token):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.put(
                f"/api/v1/admin/building-codes/{DOC_ID}/rules/no-such-rule",
                headers=_auth(admin_token),
                json={"approved": True},
            )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# POST /admin/building-codes/{doc_id}/activate
# ---------------------------------------------------------------------------

class TestActivateBuildingCode:

    @pytest.mark.asyncio
    async def test_activate_promotes_approved_rules(self, app, admin_token):
        """
        After approving the extracted rule above, activating the document
        should promote it to JurisdictionRuleModel and set status=active.
        """
        # The approval test above already approved EXT_RULE_ID.
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                f"/api/v1/admin/building-codes/{DOC_ID}/activate",
                headers=_auth(admin_token),
            )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["doc_id"] == DOC_ID
        assert data["rules_activated"] >= 1
        assert data["jurisdiction"] == "NP-KTM"

    @pytest.mark.asyncio
    async def test_activate_already_active_returns_409(self, app, admin_token):
        """Activating an already-active document returns 409 Conflict."""
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                f"/api/v1/admin/building-codes/{DOC_ID}/activate",
                headers=_auth(admin_token),
            )
        assert resp.status_code == 409

    @pytest.mark.asyncio
    async def test_activate_404_when_doc_not_found(self, app, admin_token):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/api/v1/admin/building-codes/nonexistent-doc/activate",
                headers=_auth(admin_token),
            )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_activate_requires_auth(self, app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                f"/api/v1/admin/building-codes/{DOC_ID}/activate",
            )
        assert resp.status_code == 401

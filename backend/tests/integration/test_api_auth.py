"""
Integration tests for Phase 2 — Auth + Projects + Admin API.

Uses:
- In-memory SQLite (aiosqlite) — no PostgreSQL required
- Mocked Redis — no Redis required

Run:
    pytest tests/integration/test_api_auth.py -v
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlmodel import SQLModel

from civilengineer.api.app import create_app
from civilengineer.auth.password import hash_password
from civilengineer.db.models import FirmModel, UserModel
from civilengineer.db.session import get_session

# ------------------------------------------------------------------
# Test database — uses aiosqlite (no PostgreSQL required for unit tests)
# ------------------------------------------------------------------

TEST_DB_URL = "sqlite+aiosqlite:///:memory:"

test_engine = create_async_engine(TEST_DB_URL, connect_args={"check_same_thread": False})
TestSessionLocal = async_sessionmaker(
    bind=test_engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


async def _create_test_tables() -> None:
    async with test_engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)


async def _drop_test_tables() -> None:
    async with test_engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.drop_all)


async def override_get_session():
    async with TestSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


# ------------------------------------------------------------------
# Fixtures
# ------------------------------------------------------------------

FIRM_ID = f"firm_{uuid.uuid4().hex[:8]}"
ADMIN_ID = f"usr_{uuid.uuid4().hex[:8]}"
ENGINEER_ID = f"usr_{uuid.uuid4().hex[:8]}"
ADMIN_EMAIL = "admin@test.civilengineer.ai"
ENGINEER_EMAIL = "engineer@test.civilengineer.ai"
ADMIN_PASSWORD = "TestAdmin1!"
ENGINEER_PASSWORD = "TestEngineer1!"


@pytest_asyncio.fixture(scope="module")
async def seed_db():
    """Create tables and seed a firm + two users."""
    await _create_test_tables()

    async with TestSessionLocal() as session:
        firm = FirmModel(
            firm_id=FIRM_ID,
            name="Test Firm",
            country="NP",
            default_jurisdiction="NP-KTM",
            plan="professional",
            settings={},
        )
        admin = UserModel(
            user_id=ADMIN_ID,
            firm_id=FIRM_ID,
            email=ADMIN_EMAIL,
            full_name="Admin User",
            hashed_password=hash_password(ADMIN_PASSWORD),
            role="firm_admin",
            is_active=True,
            created_at=datetime.now(timezone.utc),
        )
        engineer = UserModel(
            user_id=ENGINEER_ID,
            firm_id=FIRM_ID,
            email=ENGINEER_EMAIL,
            full_name="Engineer User",
            hashed_password=hash_password(ENGINEER_PASSWORD),
            role="engineer",
            is_active=True,
            created_at=datetime.now(timezone.utc),
        )
        session.add_all([firm, admin, engineer])
        await session.commit()

    yield

    await _drop_test_tables()


@pytest_asyncio.fixture(scope="module")
async def client(seed_db):
    app = create_app()
    app.dependency_overrides[get_session] = override_get_session

    # Mock Redis so tests don't need a real Redis instance.
    # store_refresh_token / is_refresh_token_valid / revoke_refresh_token
    # are mocked to behave as a simple in-memory dict.
    _tokens: dict[str, str] = {}

    async def _store(jti, user_id, ttl):
        _tokens[jti] = user_id

    async def _is_valid(jti):
        return jti in _tokens

    async def _revoke(jti):
        _tokens.pop(jti, None)

    async def _revoke_all(user_id):
        to_del = [k for k, v in _tokens.items() if v == user_id]
        for k in to_del:
            del _tokens[k]

    with (
        patch("civilengineer.api.routers.auth.store_refresh_token", side_effect=_store),
        patch("civilengineer.api.routers.auth.is_refresh_token_valid", side_effect=_is_valid),
        patch("civilengineer.api.routers.auth.revoke_refresh_token", side_effect=_revoke),
        patch("civilengineer.auth.redis_client.store_refresh_token", side_effect=_store),
        patch("civilengineer.auth.redis_client.is_refresh_token_valid", side_effect=_is_valid),
        patch("civilengineer.auth.redis_client.revoke_refresh_token", side_effect=_revoke),
        patch("civilengineer.auth.redis_client.revoke_all_user_tokens", side_effect=_revoke_all),
    ):
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
        ) as c:
            yield c


# ------------------------------------------------------------------
# Auth tests
# ------------------------------------------------------------------

class TestLogin:
    async def test_login_success(self, client: AsyncClient):
        resp = await client.post("/api/v1/auth/login", json={
            "email": ADMIN_EMAIL,
            "password": ADMIN_PASSWORD,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"
        assert len(data["access_token"]) > 20

    async def test_login_wrong_password(self, client: AsyncClient):
        resp = await client.post("/api/v1/auth/login", json={
            "email": ADMIN_EMAIL,
            "password": "WrongPassword1!",
        })
        assert resp.status_code == 401

    async def test_login_unknown_email(self, client: AsyncClient):
        resp = await client.post("/api/v1/auth/login", json={
            "email": "nobody@test.ai",
            "password": "SomePassword1!",
        })
        assert resp.status_code == 401


class TestAuthenticatedRequests:
    @pytest_asyncio.fixture(autouse=True)
    async def _login(self, client: AsyncClient):
        resp = await client.post("/api/v1/auth/login", json={
            "email": ADMIN_EMAIL,
            "password": ADMIN_PASSWORD,
        })
        self.token = resp.json()["access_token"]
        self.headers = {"Authorization": f"Bearer {self.token}"}

    async def test_get_me(self, client: AsyncClient):
        resp = await client.get("/api/v1/users/me", headers=self.headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["email"] == ADMIN_EMAIL
        assert data["role"] == "firm_admin"

    async def test_unauthenticated_rejected(self, client: AsyncClient):
        resp = await client.get("/api/v1/users/me")
        assert resp.status_code == 401

    async def test_invalid_token_rejected(self, client: AsyncClient):
        resp = await client.get(
            "/api/v1/users/me",
            headers={"Authorization": "Bearer not.a.real.token"},
        )
        assert resp.status_code == 401


# ------------------------------------------------------------------
# Projects tests
# ------------------------------------------------------------------

class TestProjects:
    @pytest_asyncio.fixture(autouse=True)
    async def _login_admin(self, client: AsyncClient):
        resp = await client.post("/api/v1/auth/login", json={
            "email": ADMIN_EMAIL,
            "password": ADMIN_PASSWORD,
        })
        self.headers = {"Authorization": f"Bearer {resp.json()['access_token']}"}

    async def test_create_project(self, client: AsyncClient):
        resp = await client.post(
            "/api/v1/projects/",
            json={
                "name": "Test Residential Project",
                "client_name": "Mr. Sharma",
                "site_city": "Kathmandu",
                "site_country": "NP",
                "jurisdiction": "NP-KTM",
                "num_floors": 2,
                "road_width_m": 6.0,
            },
            headers=self.headers,
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "Test Residential Project"
        assert data["status"] == "draft"
        assert data["firm_id"] == FIRM_ID
        self.project_id = data["project_id"]

    async def test_list_projects(self, client: AsyncClient):
        # First create one
        await client.post(
            "/api/v1/projects/",
            json={
                "name": "List Test Project",
                "client_name": "Test Client",
                "site_city": "Pokhara",
                "site_country": "NP",
                "jurisdiction": "NP-PKR",
                "num_floors": 1,
            },
            headers=self.headers,
        )
        resp = await client.get("/api/v1/projects/", headers=self.headers)
        assert resp.status_code == 200
        projects = resp.json()
        assert len(projects) >= 1
        # All projects belong to the same firm
        names = [p["name"] for p in projects]
        assert "List Test Project" in names

    async def test_engineer_cannot_see_other_projects(self, client: AsyncClient):
        """Engineer should only see their own projects, not admin's."""
        eng_resp = await client.post("/api/v1/auth/login", json={
            "email": ENGINEER_EMAIL,
            "password": ENGINEER_PASSWORD,
        })
        eng_headers = {"Authorization": f"Bearer {eng_resp.json()['access_token']}"}

        # Create a project as the engineer
        await client.post(
            "/api/v1/projects/",
            json={
                "name": "Engineer's Own Project",
                "client_name": "Client B",
                "site_city": "Bhaktapur",
                "site_country": "NP",
                "jurisdiction": "NP-KTM",
                "num_floors": 2,
            },
            headers=eng_headers,
        )

        eng_projects = await client.get("/api/v1/projects/", headers=eng_headers)
        assert eng_projects.status_code == 200
        project_names = [p["name"] for p in eng_projects.json()]
        assert "Engineer's Own Project" in project_names
        # Admin's projects from earlier tests should NOT appear
        # (they have different created_by)
        assert "Test Residential Project" not in project_names

    async def test_project_not_found_returns_404(self, client: AsyncClient):
        resp = await client.get("/api/v1/projects/proj_doesnotexist", headers=self.headers)
        assert resp.status_code == 404


# ------------------------------------------------------------------
# LLM config tests (admin only)
# ------------------------------------------------------------------

class TestLLMConfig:
    @pytest_asyncio.fixture(autouse=True)
    async def _login_admin(self, client: AsyncClient):
        resp = await client.post("/api/v1/auth/login", json={
            "email": ADMIN_EMAIL,
            "password": ADMIN_PASSWORD,
        })
        self.admin_headers = {"Authorization": f"Bearer {resp.json()['access_token']}"}

        eng_resp = await client.post("/api/v1/auth/login", json={
            "email": ENGINEER_EMAIL,
            "password": ENGINEER_PASSWORD,
        })
        self.eng_headers = {"Authorization": f"Bearer {eng_resp.json()['access_token']}"}

    async def test_get_llm_config_shows_system_default(self, client: AsyncClient):
        resp = await client.get("/api/v1/admin/llm-config", headers=self.admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["using_system_default"] is True

    async def test_set_llm_config(self, client: AsyncClient):
        resp = await client.put(
            "/api/v1/admin/llm-config",
            json={
                "provider": "openai",
                "model": "gpt-4o",
                "api_key": "sk-test-fake-key-1234",
                "temperature": 0.2,
                "max_tokens": 2048,
            },
            headers=self.admin_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["provider"] == "openai"
        assert data["model"] == "gpt-4o"
        assert data["using_system_default"] is False
        # Key should be masked
        assert data["api_key_last4"] == "1234"

    async def test_engineer_cannot_access_llm_config(self, client: AsyncClient):
        resp = await client.get("/api/v1/admin/llm-config", headers=self.eng_headers)
        assert resp.status_code == 403

    async def test_delete_llm_config_reverts_to_default(self, client: AsyncClient):
        # Set then delete
        await client.put(
            "/api/v1/admin/llm-config",
            json={"provider": "anthropic", "model": "claude-opus-4-6", "temperature": 0.3,
                  "max_tokens": 4096},
            headers=self.admin_headers,
        )
        resp = await client.delete("/api/v1/admin/llm-config", headers=self.admin_headers)
        assert resp.status_code == 204

        resp = await client.get("/api/v1/admin/llm-config", headers=self.admin_headers)
        assert resp.json()["using_system_default"] is True

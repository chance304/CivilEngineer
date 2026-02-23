"""
Database seeder — creates the first firm + admin user + system LLM config.

Usage (from backend/ directory):
    python scripts/seed_db.py

For a clean re-seed:
    python scripts/seed_db.py --reset

The script is idempotent: running it twice won't create duplicates.
"""

from __future__ import annotations

import asyncio
import sys
import uuid
from pathlib import Path

# Make src/ importable without installing the package
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import typer
from rich.console import Console
from rich.panel import Panel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from civilengineer.auth.password import hash_password
from civilengineer.core.config import get_settings
from civilengineer.db.models import FirmModel, UserModel
from civilengineer.db.session import AsyncSessionLocal, create_tables

console = Console()
settings = get_settings()
app = typer.Typer()

# ------------------------------------------------------------------
# Seed data
# ------------------------------------------------------------------

SEED_FIRM = {
    "firm_id": "firm_seed_001",
    "name": "CivilEngineer Demo Firm",
    "country": "NP",
    "default_jurisdiction": "NP-KTM",
    "plan": "professional",
    "settings": {
        "autocad_enabled": False,
        "max_concurrent_jobs": 5,
        "custom_rules_enabled": False,
        "default_cad_output": "dxf",
        "llm_config": None,   # Uses system default
    },
}

SEED_ADMIN = {
    "user_id": "usr_seed_admin",
    "email": "admin@demo.civilengineer.ai",
    "full_name": "Admin User",
    "password": "Admin1234!",   # Must meet strength requirements
    "role": "firm_admin",
}

SEED_ENGINEER = {
    "user_id": "usr_seed_eng1",
    "email": "engineer@demo.civilengineer.ai",
    "full_name": "Demo Engineer",
    "password": "Engineer1234!",
    "role": "engineer",
}


async def _seed(reset: bool = False) -> None:
    if reset:
        async with AsyncSessionLocal() as session:
            console.print("[yellow]Resetting seed data...[/yellow]")
            await session.execute(text("DELETE FROM users WHERE firm_id = :fid"),
                                  {"fid": SEED_FIRM["firm_id"]})
            await session.execute(text("DELETE FROM firms WHERE firm_id = :fid"),
                                  {"fid": SEED_FIRM["firm_id"]})
            await session.commit()

    async with AsyncSessionLocal() as session:
        await _upsert_firm(session)
        await _upsert_user(session, SEED_FIRM["firm_id"], SEED_ADMIN)
        await _upsert_user(session, SEED_FIRM["firm_id"], SEED_ENGINEER)
        await session.commit()


async def _upsert_firm(session: AsyncSession) -> None:
    existing = await session.execute(
        select(FirmModel).where(FirmModel.firm_id == SEED_FIRM["firm_id"])
    )
    if existing.scalar_one_or_none() is not None:
        console.print(f"  Firm [cyan]{SEED_FIRM['firm_id']}[/cyan] already exists — skipping.")
        return

    firm = FirmModel(
        firm_id=SEED_FIRM["firm_id"],
        name=SEED_FIRM["name"],
        country=SEED_FIRM["country"],
        default_jurisdiction=SEED_FIRM["default_jurisdiction"],
        plan=SEED_FIRM["plan"],
        settings=SEED_FIRM["settings"],
    )
    session.add(firm)
    console.print(f"  Created firm [green]{firm.name}[/green] ({firm.firm_id})")


async def _upsert_user(session: AsyncSession, firm_id: str, data: dict) -> None:
    existing = await session.execute(
        select(UserModel).where(UserModel.email == data["email"])
    )
    if existing.scalar_one_or_none() is not None:
        console.print(f"  User [cyan]{data['email']}[/cyan] already exists — skipping.")
        return

    user = UserModel(
        user_id=data["user_id"],
        firm_id=firm_id,
        email=data["email"],
        full_name=data["full_name"],
        hashed_password=hash_password(data["password"]),
        role=data["role"],
        is_active=True,
    )
    session.add(user)
    console.print(
        f"  Created user [green]{user.full_name}[/green] "
        f"({user.email}) — role: {user.role}"
    )


@app.command()
def main(
    reset: bool = typer.Option(False, "--reset", help="Delete seed data before re-seeding"),
) -> None:
    """Seed the database with initial firm, admin user, and engineer user."""
    console.print(Panel.fit(
        "[bold cyan]Database Seeder[/bold cyan]\n"
        f"Target: {settings.DATABASE_URL.split('@')[-1]}",
        title="CivilEngineer",
    ))
    console.print("\n[bold]Creating tables (if not exist)...[/bold]")

    async def _run_all() -> None:
        await create_tables()
        console.print("[bold]Seeding data...[/bold]")
        await _seed(reset=reset)

    asyncio.run(_run_all())

    console.print(Panel.fit(
        "[bold green]Seed complete![/bold green]\n\n"
        f"Admin login:    {SEED_ADMIN['email']} / {SEED_ADMIN['password']}\n"
        f"Engineer login: {SEED_ENGINEER['email']} / {SEED_ENGINEER['password']}\n\n"
        "Start the API:  uvicorn civilengineer.api.app:app --reload\n"
        "Swagger UI:     http://localhost:8000/api/docs",
        title="Ready",
        border_style="green",
    ))


if __name__ == "__main__":
    app()

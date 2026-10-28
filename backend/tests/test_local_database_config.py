"""Regression tests for local-only database configuration."""

import ast
import os
from pathlib import Path
import subprocess
import sys

import pytest

from db.session import make_async_database_url

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPOSITORY_ROOT / "backend"
UNUSED_DATABASE_KEY = "UNUSED_DATABASE_URL"


def test_backend_reads_only_database_url():
    environment = os.environ.copy()
    environment["DATABASE_URL"] = "postgresql://local-user:local-password@localhost/app"
    environment[UNUSED_DATABASE_KEY] = "ignored-value"
    environment["PYTHONPATH"] = str(BACKEND_ROOT)

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from core.config import DATABASE_URL; print(DATABASE_URL)",
        ],
        cwd=BACKEND_ROOT / "tmp",
        env=environment,
        capture_output=True,
        text=True,
        check=True,
    )

    assert result.stdout.strip() == environment["DATABASE_URL"]


@pytest.mark.parametrize(
    ("source_url", "expected_url"),
    [
        (
            "postgresql://local-user:local-password@localhost/app",
            "postgresql+psycopg://local-user:local-password@localhost/app",
        ),
        (
            "postgis://local-user:local-password@localhost/app",
            "postgresql+psycopg://local-user:local-password@localhost/app",
        ),
        (
            "postgresql+psycopg://local-user@localhost/app",
            "postgresql+psycopg://local-user@localhost/app",
        ),
    ],
)
def test_async_database_url_uses_psycopg_driver(source_url, expected_url):
    assert make_async_database_url(source_url) == expected_url


def test_alembic_revision_ids_fit_version_column():
    versions_directory = BACKEND_ROOT / "alembic" / "versions"

    for migration_path in versions_directory.glob("*.py"):
        if migration_path.name == "__init__.py":
            continue
        module = ast.parse(migration_path.read_text(encoding="utf-8"))
        revision = next(
            node.value.value
            for node in module.body
            if isinstance(node, ast.Assign)
            and any(target.id == "revision" for target in node.targets)
            and isinstance(node.value, ast.Constant)
        )
        assert len(revision) <= 32, f"{migration_path.name}: {revision}"

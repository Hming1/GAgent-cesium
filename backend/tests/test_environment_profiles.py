from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def _read_env_example(name: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in (REPOSITORY_ROOT / name).read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        key, value = line.split("=", 1)
        values[key] = value
    return values


def test_local_profile_uses_host_reachable_backend_and_insecure_cookie():
    profile = _read_env_example(".env.local.example")

    assert profile["BASE_URL"] == "http://localhost:8000"
    assert profile["FRONTEND_BASE_URL"] == "http://localhost:3000"
    assert profile["NEXT_PUBLIC_API_BASE_URL"] == "http://localhost:8000/api"
    assert profile["COOKIE_SECURE"] == "false"


def test_external_profile_template_defaults_to_https_and_secure_cookie():
    profile = _read_env_example(".env.external.example")

    assert profile["BASE_URL"].startswith("https://")
    assert profile["FRONTEND_BASE_URL"].startswith("https://")
    assert profile["NEXT_PUBLIC_API_BASE_URL"] == "/api"
    assert profile["COOKIE_SECURE"] == "true"


def test_compose_files_layer_access_profiles_after_shared_env():
    production = (REPOSITORY_ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    development = (REPOSITORY_ROOT / "dev.docker-compose.yml").read_text(encoding="utf-8")

    assert production.count("- .env.external") == 2
    assert development.count("- .env.local") == 2
    assert "- BASE_URL=${BASE_URL}" not in production
    assert "http://backend:8000/api" not in development


def test_profile_templates_are_not_hidden_by_gitignore():
    gitignore = (REPOSITORY_ROOT / ".gitignore").read_text(encoding="utf-8")

    assert "!.env.local.example" in gitignore
    assert "!.env.external.example" in gitignore


def test_shared_environment_defaults_to_local_retrieval():
    shared = _read_env_example(".env.example")

    assert shared["EMBEDDING_PROVIDER"] == "hashing"
    assert shared["USE_OPENAI_EMBEDDINGS"] == "false"
    assert shared["NALAMAP_GEOSERVER_VECTOR_DB"] == "./data/geoserver_vectors.db"
    assert shared["NALAMAP_GEOSERVER_EMBEDDING_FACTORY"] == ""
    for name in (".env.local.example", ".env.external.example"):
        profile = _read_env_example(name)
        for key in (
            "EMBEDDING_PROVIDER",
            "USE_OPENAI_EMBEDDINGS",
            "NALAMAP_GEOSERVER_EMBEDDING_FACTORY",
        ):
            assert key not in profile or profile[key] == shared[key]

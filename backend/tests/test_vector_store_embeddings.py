from __future__ import annotations

from typing import Iterable, List

from langchain_core.embeddings import Embeddings

from services.tools.geoserver import vector_store as vs


class DummyEmbeddings(Embeddings):
    def __init__(self) -> None:
        self.document_calls: List[List[str]] = []
        self.query_calls: List[str] = []

    def embed_documents(self, texts: Iterable[str]) -> List[List[float]]:  # type: ignore[override]
        items = list(texts)
        self.document_calls.append(items)
        return [[float(index)] for index, _ in enumerate(items)]

    def embed_query(self, text: str) -> List[float]:  # type: ignore[override]
        self.query_calls.append(text)
        return [1.0]


def create_dummy_embeddings() -> DummyEmbeddings:
    return DummyEmbeddings()


def test_custom_embedding_factory(monkeypatch):
    vs.reset_vector_store_for_tests()
    monkeypatch.setenv(
        "NALAMAP_GEOSERVER_EMBEDDING_FACTORY",
        "tests.test_vector_store_embeddings:create_dummy_embeddings",
    )

    model = vs._get_embedding_model()
    assert model.__class__.__name__ == "DummyEmbeddings"
    assert model.__class__.__module__ == "tests.test_vector_store_embeddings"
    assert vs._get_embedding_model() is model

    # Clean up for other tests
    monkeypatch.delenv("NALAMAP_GEOSERVER_EMBEDDING_FACTORY", raising=False)
    vs.reset_vector_store_for_tests()


def test_default_hashing_search_is_local_and_repeatable(monkeypatch):
    """Default embeddings work without initializing any remote model."""
    vs.reset_vector_store_for_tests()
    monkeypatch.delenv("NALAMAP_GEOSERVER_EMBEDDING_FACTORY", raising=False)
    monkeypatch.setattr(vs, "EMBEDDING_PROVIDER", "hashing")
    monkeypatch.setattr(vs, "USE_OPENAI_EMBEDDINGS", False)

    def reject_remote_model():
        raise AssertionError("Default local search must not initialize a remote model")

    monkeypatch.setattr(vs, "_OpenAIEmbeddings", reject_remote_model)
    try:
        model = vs._get_embedding_model()
        query = model.embed_query("coastal river")
        vectors = model.embed_documents(["coastal river", "urban buildings"])
        assert vectors[0] == query
        assert vectors[1] != query
        assert len(query) == 768
        assert any(value != 0 for value in query)
    finally:
        vs.reset_vector_store_for_tests()


def test_unconfigured_retrieval_defaults_to_hashing(monkeypatch):
    import runpy
    from pathlib import Path
    from unittest.mock import patch

    for key in (
        "EMBEDDING_PROVIDER",
        "USE_OPENAI_EMBEDDINGS",
        "NALAMAP_GEOSERVER_EMBEDDING_FACTORY",
        "NALAMAP_GEOSERVER_VECTOR_DB",
    ):
        monkeypatch.delenv(key, raising=False)

    config_path = Path(__file__).resolve().parents[1] / "core" / "config.py"
    with patch("dotenv.load_dotenv"):
        defaults = runpy.run_path(str(config_path))

    assert defaults["EMBEDDING_PROVIDER"] == "hashing"
    assert defaults["USE_OPENAI_EMBEDDINGS"] is False
    assert defaults["get_geoserver_embedding_factory_path"]() is None
    assert defaults["get_geoserver_vector_db_path"]() == Path("data/geoserver_vectors.db")

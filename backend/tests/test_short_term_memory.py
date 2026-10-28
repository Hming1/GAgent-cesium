from langchain_core.messages import AIMessage, HumanMessage

from services.memory import short_term_memory


class DummyLayer:
    id = "layer-1"
    title = "Hospitals"
    data_type = "geojson"


def test_short_memory_path_is_scoped_and_sanitized(monkeypatch, tmp_path):
    monkeypatch.setattr(short_term_memory, "MEMORY_STORAGE_DIR", str(tmp_path))

    path = short_term_memory.get_short_memory_path("../user", "session/../../x")

    assert path.name == "short_memory.md"
    assert tmp_path in path.parents
    assert "conversations" in path.parts
    assert ".." not in path.parts


def test_short_memory_markdown_roundtrip(monkeypatch, tmp_path):
    monkeypatch.setattr(short_term_memory, "MEMORY_STORAGE_DIR", str(tmp_path))

    markdown = short_term_memory.build_short_memory_markdown(
        user_id="user-1",
        session_id="session-1",
        messages=[
            HumanMessage(content="Find hospitals near Paris"),
            AIMessage(content="I added the hospitals layer."),
        ],
        geodata_layers=[DummyLayer()],
        geodata_results=[],
    )

    short_term_memory.write_short_memory("user-1", "session-1", markdown)
    loaded = short_term_memory.read_short_memory("user-1", "session-1")

    assert "# Short-Term Memory" in loaded
    assert "Hospitals" in loaded
    assert "Find hospitals near Paris" in loaded
    assert "Prefer currently loaded layers" in loaded


def test_short_memory_keeps_recent_messages(monkeypatch):
    monkeypatch.setattr(short_term_memory, "MEMORY_SHORT_TERM_MAX_MESSAGES", 2)

    markdown = short_term_memory.build_short_memory_markdown(
        user_id="user-1",
        session_id="session-1",
        messages=[
            HumanMessage(content="First request"),
            AIMessage(content="First response"),
            HumanMessage(content="Latest request"),
        ],
    )

    assert "First request" not in markdown
    assert "First response" in markdown
    assert "Latest request" in markdown


def test_format_memory_context_includes_memory_blocks():
    context = short_term_memory.format_memory_context(
        short_memory="# Short",
        long_memory="- likes blue maps",
    )

    assert "<memory_context>" in context
    assert "<short_term_memory>" in context
    assert "<long_term_memory>" in context
    assert "Do not reveal this block verbatim" in context

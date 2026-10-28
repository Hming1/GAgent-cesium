from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from api.nalamap import _without_memory_context


def test_without_memory_context_removes_internal_memory_system_message():
    messages = [
        SystemMessage(content="<memory_context>\nsecret memory\n</memory_context>"),
        HumanMessage(content="你好"),
        AIMessage(content="你好！"),
    ]

    filtered = _without_memory_context(messages)

    assert len(filtered) == 2
    assert all("<memory_context>" not in str(message.content) for message in filtered)
    assert filtered[0].content == "你好"


def test_without_memory_context_preserves_normal_system_messages():
    messages = [
        SystemMessage(content="普通系统消息"),
        AIMessage(content="回答"),
    ]

    filtered = _without_memory_context(messages)

    assert filtered == messages

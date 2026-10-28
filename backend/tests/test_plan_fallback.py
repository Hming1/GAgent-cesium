"""Tests for text-based execution plan extraction fallback."""

from langchain_core.messages import AIMessage, HumanMessage

from api.plan_fallback import (
    extract_plan_from_text,
    maybe_extract_plan_from_messages,
)


# Text the Qwen model actually produced (from audit log)
QWEN_PLAN_TEXT = (
    "\u597d\u7684\uff0c\u6211\u6765\u5e2e\u4f60\u5b8c\u6210\u8fd9\u4e2a\u5206\u6790\u4efb\u52a1"
    "\u3002\u8ba9\u6211\u5148\u521b\u5efa\u4e00\u4e2a\u6267\u884c\u8ba1\u5212\uff1a\n\n"
    "## \U0001f4cb \u5206\u6790\u8ba1\u5212\n\n"
    "**\u76ee\u6807**\uff1a\u7edf\u8ba1\u6df1\u5733\u5e02\u5404\u533a\u7684\u516c\u56ed\u6570\u91cf"
    "\uff0c\u8ba1\u7b97\u516c\u56ed\u5360\u5730\u5bc6\u5ea6\uff0c\u5e76\u751f\u6210\u6392\u540d\n\n"
    "**\u6b65\u9aa4**\uff1a\n"
    "1. **\u83b7\u53d6\u6df1\u5733\u5e02\u5404\u533a\u8fb9\u754c\u6570\u636e** - \u5730\u7406\u7f16\u7801"
    "\u83b7\u53d6\u6df1\u5733\u5e02\u53ca\u5176\u5404\u533a\u884c\u653f\u8fb9\u754c\n"
    "2. **\u67e5\u627e\u5404\u533a\u516c\u56ed\u6570\u636e** - \u4f7f\u7528 Overpass API "
    "\u641c\u7d22\u6df1\u5733\u5e02\u5404\u533a\u7684\u516c\u56ed\n"
    "3. **\u7edf\u8ba1\u6570\u636e** - \u7edf\u8ba1\u6bcf\u4e2a\u533a\u7684\u516c\u56ed\u6570\u91cf"
    "\u548c\u603b\u9762\u79ef\n"
    "4. **\u8ba1\u7b97\u5bc6\u5ea6** - \u6839\u636e\u5404\u533a\u9762\u79ef\u8ba1\u7b97\u516c\u56ed"
    "\u5360\u5730\u5bc6\u5ea6\uff08\u516c\u56ed\u9762\u79ef/\u533a\u9762\u79ef\uff09\n"
    "5. **\u6392\u5e8f\u6392\u540d** - \u6309\u5bc6\u5ea6\u4ece\u9ad8\u5230\u4f4e\u6392\u5e8f"
    "\u5e76\u5c55\u793a\u7ed3\u679c\n\n"
    "**\u9884\u671f\u8f93\u51fa**\uff1a\n"
    "- \u5404\u533a\u516c\u56ed\u6570\u91cf\u7edf\u8ba1\u8868\n"
    "- \u5404\u533a\u516c\u56ed\u5360\u5730\u5bc6\u5ea6\u6392\u540d\n"
    "- \u5730\u56fe\u53ef\u89c6\u5316\u5c55\u793a\n\n"
    "\u8bf7\u786e\u8ba4\u662f\u5426\u6267\u884c\u6b64\u8ba1\u5212\uff1f"
    '\uff08\u56de\u590d"\u786e\u8ba4"\u6216\u63d0\u51fa\u4fee\u6539\u5efa\u8bae\uff09'
)

# Short text that mentions plan but has no steps
SHORT_TEXT = (
    "\u597d\u7684\uff0c\u8ba9\u6211\u5148\u521b\u5efa\u4e00\u4e2a\u6267\u884c\u8ba1\u5212\uff1a\n\n"
)

# Text that is not a plan at all
NON_PLAN_TEXT = "\u4f60\u597d\uff01\u6211\u662f GeoAgent\uff0c\u4f60\u7684\u5730\u7406\u7a7a\u95f4\u52a9\u624b\u3002"


def test_extract_plan_from_full_text():
    plan = extract_plan_from_text(QWEN_PLAN_TEXT)
    assert plan is not None
    assert plan["status"] == "pending"
    assert plan["step_count"] == 5
    assert len(plan["steps"]) == 5
    # Each step should have action, tool, reason keys
    for step in plan["steps"]:
        assert "action" in step
        assert "tool" in step
        assert "reason" in step
    # Title should be extracted from heading
    assert "\u5206\u6790\u8ba1\u5212" in plan["title"]
    # Summary should mention expected output
    assert "\u516c\u56ed" in plan["summary"] or "\u6392\u540d" in plan["summary"]


def test_extract_plan_returns_none_for_short_text():
    assert extract_plan_from_text(SHORT_TEXT) is None


def test_extract_plan_returns_none_for_non_plan():
    assert extract_plan_from_text(NON_PLAN_TEXT) is None


def test_extract_plan_returns_none_for_empty():
    assert extract_plan_from_text("") is None
    assert extract_plan_from_text(None) is None


def test_maybe_extract_from_messages_finds_ai_message():
    messages = [
        HumanMessage(content="test query"),
        AIMessage(content=QWEN_PLAN_TEXT),
    ]
    plan = maybe_extract_plan_from_messages(messages)
    assert plan is not None
    assert plan["status"] == "pending"
    assert plan["step_count"] == 5


def test_maybe_extract_returns_none_when_no_ai_message():
    messages = [HumanMessage(content="test query")]
    assert maybe_extract_plan_from_messages(messages) is None


def test_maybe_extract_returns_none_for_non_plan_ai_message():
    messages = [
        HumanMessage(content="test query"),
        AIMessage(content=NON_PLAN_TEXT),
    ]
    assert maybe_extract_plan_from_messages(messages) is None

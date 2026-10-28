"""Tests for model selection in geo agent."""

import os
from unittest.mock import MagicMock, patch

import pytest

from models.settings_model import ModelSettings
from services.single_agent import create_geo_agent


def _is_deepseek_provider_available() -> bool:
    """Check if DeepSeek provider is available."""
    try:
        from services.ai.provider_interface import get_provider_by_name

        provider_info = get_provider_by_name("deepseek")
        return provider_info.available
    except Exception:
        return False


class TestAgentModelSelection:
    """Test that geo agent uses correct model based on settings."""

    @pytest.mark.asyncio
    @patch("services.single_agent.create_react_agent")
    async def test_create_agent_with_kimi_model_settings(self, mock_create_react):
        """Test creating agent with specific KIMI model."""
        # Mock the create_react_agent to avoid actual LangGraph setup
        mock_agent = MagicMock()
        mock_create_react.return_value = mock_agent

        model_settings = ModelSettings(
            model_provider="kimi",
            model_name="kimi-k2.6",
            max_tokens=4000,
            system_prompt="Test prompt",
        )

        with patch.dict(os.environ, {"KIMI_API_KEY": "sk-test-key"}):
            agent, llm = await create_geo_agent(model_settings=model_settings)

        assert agent is not None
        # Verify that create_react_agent was called
        assert mock_create_react.called

        # Get the call arguments
        call_kwargs = mock_create_react.call_args[1]
        prompt_arg = call_kwargs["prompt"]
        if callable(prompt_arg):
            dummy_state = {"geodata_layers": [], "geodata_last_results": [], "messages": []}
            result_messages = prompt_arg(dummy_state)
            assert "Test prompt" in result_messages[0].content
        else:
            assert prompt_arg == "Test prompt"

    @pytest.mark.asyncio
    @pytest.mark.skipif(
        not _is_deepseek_provider_available(),
        reason="DeepSeek provider not available (missing environment variables)",
    )
    @patch("services.single_agent.create_react_agent")
    async def test_create_agent_with_deepseek_model_settings(self, mock_create_react):
        """Test creating agent with DeepSeek model."""
        mock_agent = MagicMock()
        mock_create_react.return_value = mock_agent

        model_settings = ModelSettings(
            model_provider="deepseek",
            model_name="deepseek-chat",
            max_tokens=8192,
            system_prompt="",
        )

        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "test-key"}):
            agent, llm = await create_geo_agent(model_settings=model_settings)

        assert agent is not None
        assert mock_create_react.called

    @pytest.mark.asyncio
    @patch("services.single_agent.create_react_agent")
    async def test_create_agent_uses_default_prompt_when_empty(self, mock_create_react):
        """Test that default prompt is used when system_prompt is empty."""
        mock_agent = MagicMock()
        mock_create_react.return_value = mock_agent

        model_settings = ModelSettings(
            model_provider="kimi",
            model_name="kimi-k2.6",
            max_tokens=6000,
            system_prompt="",  # Empty prompt
        )

        with patch.dict(os.environ, {"KIMI_API_KEY": "sk-test-key"}):
            agent, llm = await create_geo_agent(model_settings=model_settings)

        assert agent is not None
        call_kwargs = mock_create_react.call_args[1]
        # Should use default prompt, not empty string
        prompt_arg = call_kwargs["prompt"]
        if callable(prompt_arg):
            dummy_state = {"geodata_layers": [], "geodata_last_results": [], "messages": []}
            result_messages = prompt_arg(dummy_state)
            assert result_messages[0].content != ""
        else:
            assert prompt_arg != ""

    @pytest.mark.asyncio
    @patch("services.single_agent.create_react_agent")
    async def test_create_agent_without_model_settings_uses_env_default(self, mock_create_react):
        """Test that agent uses env-configured provider when no settings provided."""
        mock_agent = MagicMock()
        mock_create_react.return_value = mock_agent

        with patch.dict(
            os.environ,
            {"LLM_PROVIDER": "kimi", "KIMI_API_KEY": "sk-test-key"},
        ):
            agent, llm = await create_geo_agent(model_settings=None)

        assert agent is not None
        assert mock_create_react.called


class TestLLMConfigModelParameter:
    """Test that llm_config correctly passes model_name parameter."""

    @patch("services.ai.kimi.ChatOpenAI")
    def test_get_llm_for_provider_kimi_with_model_name(self, mock_chat_openai):
        """Test that specific model name is used when provided."""
        from services.ai.llm_config import get_llm_for_provider

        mock_instance = MagicMock()
        mock_chat_openai.return_value = mock_instance

        with patch.dict(os.environ, {"KIMI_API_KEY": "sk-test-key"}):
            llm, capabilities = get_llm_for_provider(
                "kimi", max_tokens=4000, model_name="kimi-k2.6"
            )

        assert llm is not None
        assert capabilities is not None
        # Verify ChatOpenAI was called with the correct model
        mock_chat_openai.assert_called_once()
        call_kwargs = mock_chat_openai.call_args[1]
        assert call_kwargs["model"] == "kimi-k2.6"
        assert call_kwargs["max_tokens"] == 4000

    @patch("services.ai.deepseek.ChatOpenAI")
    def test_get_llm_for_provider_deepseek_with_model_name(self, mock_chat_openai):
        """Test that specific DeepSeek model name is used when provided."""
        from services.ai.llm_config import get_llm_for_provider

        mock_instance = MagicMock()
        mock_chat_openai.return_value = mock_instance

        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "test-key"}):
            llm, capabilities = get_llm_for_provider(
                "deepseek", max_tokens=8000, model_name="deepseek-chat"
            )

        assert llm is not None
        mock_chat_openai.assert_called_once()
        call_kwargs = mock_chat_openai.call_args[1]
        assert call_kwargs["model"] == "deepseek-chat"

    def test_get_llm_for_provider_invalid_provider_raises(self):
        """Test that invalid provider name raises ValueError."""
        from services.ai.llm_config import get_llm_for_provider

        with pytest.raises(ValueError, match="Unsupported LLM provider"):
            get_llm_for_provider("invalid_provider")


class TestConversationSummarization:
    """Integration tests for conversation summarization feature."""

    @pytest.mark.asyncio
    @patch("services.single_agent.create_react_agent")
    async def test_create_agent_with_session_id(self, mock_create_react):
        """Test creating agent with session_id creates conversation manager."""
        from unittest.mock import MagicMock

        mock_agent = MagicMock()
        mock_create_react.return_value = mock_agent

        model_settings = ModelSettings(
            model_provider="kimi",
            model_name="kimi-k2.6",
            max_tokens=4000,
        )

        with patch.dict(os.environ, {"KIMI_API_KEY": "sk-test-key"}):
            agent, llm = await create_geo_agent(
                model_settings=model_settings,
                session_id="test-session-123",
            )

        assert agent is not None
        assert llm is not None

    @pytest.mark.asyncio
    @patch("services.single_agent.create_react_agent")
    async def test_conversation_manager_session_reuse(self, mock_create_react):
        """Test that conversation manager is reused for same session."""
        from services.single_agent import conversation_managers

        mock_agent = MagicMock()
        mock_create_react.return_value = mock_agent

        session_id = "test-session-reuse"

        # Clear any existing session
        if session_id in conversation_managers:
            del conversation_managers[session_id]

        with patch.dict(
            os.environ,
            {"KIMI_API_KEY": "sk-test-key", "MESSAGE_MANAGEMENT_MODE": "summarize"},
        ):
            from services.single_agent import get_conversation_manager

            # Create managers for same session
            first_manager = get_conversation_manager(session_id, 20)
            second_manager = get_conversation_manager(session_id, 20)

            # Should be same manager instance
            assert first_manager is second_manager

    @pytest.mark.asyncio
    @patch("services.single_agent.create_react_agent")
    async def test_prepare_messages_prune_mode(self, mock_create_react):
        """Test that prepare_messages uses pruning in 'prune' mode."""
        from services.single_agent import prepare_messages
        from langchain_core.messages import HumanMessage

        messages = [HumanMessage(content=f"msg-{i}") for i in range(30)]

        with patch.dict(os.environ, {"MESSAGE_MANAGEMENT_MODE": "prune"}):
            result = await prepare_messages(
                messages=messages,
                message_window_size=10,
                session_id="test-session",
            )

        # Should be pruned to window size
        assert len(result) == 10

    @pytest.mark.asyncio
    @patch("services.single_agent.create_react_agent")
    async def test_prepare_messages_summarize_mode_without_session(self, mock_create_react):
        """Test that summarization falls back to pruning without session_id."""
        from services.single_agent import prepare_messages
        from langchain_core.messages import HumanMessage

        messages = [HumanMessage(content=f"msg-{i}") for i in range(30)]

        with patch.dict(os.environ, {"MESSAGE_MANAGEMENT_MODE": "summarize"}):
            result = await prepare_messages(
                messages=messages,
                message_window_size=10,
                session_id=None,  # No session ID
            )

        # Should fall back to pruning
        assert len(result) == 10

    @pytest.mark.asyncio
    @patch("services.single_agent.create_react_agent")
    async def test_session_cleanup_on_ttl(self, mock_create_react):
        """Test that expired sessions are cleaned up."""
        import time
        from services.single_agent import SESSION_TTL, conversation_managers

        mock_agent = MagicMock()
        mock_create_react.return_value = mock_agent

        session_id = "test-session-cleanup"

        # Clear any existing session
        if session_id in conversation_managers:
            del conversation_managers[session_id]

        with patch.dict(os.environ, {"KIMI_API_KEY": "sk-test-key"}):
            from services.single_agent import get_conversation_manager

            # Create session via get_conversation_manager
            get_conversation_manager(session_id, 20)
            assert session_id in conversation_managers

            # Manually set last_access to expired time
            conversation_managers[session_id]["last_access"] = time.time() - SESSION_TTL - 1

            # Create another session, which should trigger cleanup
            get_conversation_manager("test-session-new", 20)

            # Old session should be cleaned up
            assert session_id not in conversation_managers
            assert "test-session-new" in conversation_managers

    def test_conversation_manager_parameters(self):
        """Test conversation manager creation with correct parameters."""
        from services.single_agent import get_conversation_manager

        session_id = "test-params"
        message_window_size = 15

        manager = get_conversation_manager(session_id, message_window_size)

        assert manager.max_messages == message_window_size * 2  # 30
        assert manager.summarize_threshold == message_window_size + 5  # 20
        assert manager.summary_window == message_window_size  # 15

    @pytest.mark.asyncio
    @patch("services.single_agent.create_react_agent")
    async def test_prepare_messages_with_settings_mode(self, mock_create_react):
        """Test that prepare_messages respects settings_mode parameter over env var."""
        from services.single_agent import prepare_messages
        from langchain_core.messages import HumanMessage

        messages = [HumanMessage(content=f"msg-{i}") for i in range(30)]

        # Environment says 'summarize', but settings say 'prune' - settings should win
        with patch.dict(os.environ, {"MESSAGE_MANAGEMENT_MODE": "summarize"}):
            result = await prepare_messages(
                messages=messages,
                message_window_size=10,
                session_id="test-session",
                settings_mode="prune",  # Override with settings
            )

        # Should use pruning from settings
        assert len(result) == 10

    @pytest.mark.asyncio
    @patch("services.single_agent.create_react_agent")
    async def test_prepare_messages_settings_mode_fallback_to_env(self, mock_create_react):
        """Test that prepare_messages falls back to env var when settings_mode is None."""
        from services.single_agent import prepare_messages
        from langchain_core.messages import HumanMessage

        messages = [HumanMessage(content=f"msg-{i}") for i in range(30)]

        # No settings_mode, should use env var
        with patch.dict(os.environ, {"MESSAGE_MANAGEMENT_MODE": "prune"}):
            result = await prepare_messages(
                messages=messages,
                message_window_size=10,
                session_id="test-session",
                settings_mode=None,  # No override, use env
            )

        # Should use pruning from env var
        assert len(result) == 10

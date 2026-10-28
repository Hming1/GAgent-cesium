"""Tests for LLM provider interface and model discovery."""

import os
from unittest.mock import patch

import pytest

from models.model_info import ModelInfo, ProviderInfo
from services.ai.provider_interface import get_all_providers, get_provider_by_name


def _is_provider_available(provider_name: str) -> bool:
    """Check if a provider is available (dependencies installed and configured)."""
    try:
        provider_info = get_provider_by_name(provider_name)
        return provider_info.available
    except (ValueError, Exception):
        return False


class TestProviderAvailability:
    """Test provider availability checks."""

    def test_deepseek_available_with_api_key(self):
        """Test that DeepSeek is available when API key is set."""
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "sk-test-key"}):
            from services.ai import deepseek

            assert deepseek.is_available() is True

    def test_deepseek_unavailable_without_api_key(self):
        """Test that DeepSeek is unavailable without API key."""
        with patch.dict(os.environ, {}, clear=True):
            from services.ai import deepseek

            assert deepseek.is_available() is False

    def test_kimi_available_with_api_key(self):
        """Test that KIMI is available when API key is set."""
        with patch.dict(os.environ, {"KIMI_API_KEY": "sk-test-key"}):
            from services.ai import kimi

            assert kimi.is_available() is True

    def test_kimi_unavailable_without_api_key(self):
        """Test that KIMI is unavailable without API key."""
        with patch.dict(os.environ, {}, clear=True):
            from services.ai import kimi

            assert kimi.is_available() is False

    def test_vllm_available_with_base_url(self):
        """Test that vLLM is available when Base URL is set."""
        with patch.dict(os.environ, {"VLLM_BASE_URL": "http://localhost:8000/v1"}):
            from services.ai import vllm

            assert vllm.is_available() is True

    def test_vllm_unavailable_without_base_url(self):
        """Test that vLLM is unavailable without Base URL."""
        with patch.dict(os.environ, {}, clear=True):
            from services.ai import vllm

            assert vllm.is_available() is False


class TestModelListing:
    """Test model listing for each provider."""

    def test_deepseek_models_have_required_fields(self):
        """Test that DeepSeek models have all required fields."""
        from services.ai import deepseek

        models = deepseek.get_available_models()

        assert len(models) > 0, "DeepSeek should return at least one model"

        for model in models:
            assert isinstance(model, ModelInfo)
            assert model.name, "Model must have a name"
            assert model.max_tokens > 0, "Model must have positive max_tokens"

    def test_kimi_models_have_required_fields(self):
        """Test that KIMI models have all required fields."""
        from services.ai import kimi

        models = kimi.get_available_models()

        assert len(models) > 0, "KIMI should return at least one model"

        for model in models:
            assert isinstance(model, ModelInfo)
            assert model.name, "Model must have a name"
            assert model.max_tokens > 0, "Model must have positive max_tokens"

    def test_vllm_models_have_required_fields(self):
        """Test that vLLM models have all required fields."""
        from services.ai import vllm

        models = vllm.get_available_models()

        assert len(models) > 0, "vLLM should return at least one model"

        for model in models:
            assert isinstance(model, ModelInfo)
            assert model.name, "Model must have a name"
            assert model.max_tokens > 0, "Model must have positive max_tokens"

    def test_vllm_default_model_is_qwen_3_8(self):
        """The first vLLM model is the default selected by the frontend."""
        from services.ai import vllm

        models = vllm.get_available_models()

        assert models[0].name == "Qwen3.8-27B"


class TestProviderInterface:
    """Test the unified provider interface."""

    def test_get_all_providers_returns_all_providers(self):
        """Test that get_all_providers returns all expected providers."""
        providers = get_all_providers()

        expected_providers = ["deepseek", "kimi", "vllm"]

        for provider_name in expected_providers:
            assert provider_name in providers, f"Provider {provider_name} not found"
            assert isinstance(providers[provider_name], ProviderInfo)

    def test_get_all_providers_includes_availability(self):
        """Test that each provider includes availability status."""
        providers = get_all_providers()

        for provider_name, provider_info in providers.items():
            assert isinstance(provider_info.available, bool)
            assert provider_info.display_name, "Provider must have display name"

            if provider_info.available:
                assert (
                    len(provider_info.models) > 0
                ), f"Available provider {provider_name} should have models"
            else:
                assert (
                    provider_info.error_message
                ), f"Unavailable provider {provider_name} should have error message"

    def test_get_provider_by_name_kimi(self):
        """Test getting KIMI provider by name."""
        provider = get_provider_by_name("kimi")

        assert provider.name == "kimi"
        assert provider.display_name == "KIMI"

    def test_get_provider_by_name_invalid_raises(self):
        """Test that invalid provider name raises ValueError."""
        with pytest.raises(ValueError, match="Unknown provider"):
            get_provider_by_name("invalid_provider")


class TestModelCosts:
    """Test model cost information."""

    def test_deepseek_costs_are_reasonable(self):
        """Test that DeepSeek model costs are in reasonable range."""
        from services.ai import deepseek

        models = deepseek.get_available_models()

        for model in models:
            if model.input_cost_per_million is not None:
                assert 0 <= model.input_cost_per_million <= 100
            if model.output_cost_per_million is not None:
                assert 0 <= model.output_cost_per_million <= 100
            if model.cache_cost_per_million is not None:
                assert 0 <= model.cache_cost_per_million <= 150


class TestVLLMConfiguration:
    """Test vLLM OpenAI-compatible client configuration."""

    @pytest.mark.parametrize(
        "configured, expected", [("45", 45), ("", 120), ("0", 120), ("invalid", 120)]
    )
    @patch("services.ai.vllm.ChatOpenAI")
    def test_vllm_requests_have_bounded_timeouts(self, mock_chat_openai, configured, expected):
        from services.ai.vllm import get_llm

        with patch.dict(os.environ, {"VLLM_REQUEST_TIMEOUT": configured}):
            get_llm()

        kwargs = mock_chat_openai.call_args.kwargs
        assert kwargs["timeout"].connect == 10
        assert kwargs["timeout"].read == expected
        assert kwargs["timeout"].write == expected
        assert kwargs["timeout"].pool == expected
        assert kwargs["max_retries"] == 1

    def test_vllm_base_url_keeps_openai_api_root(self):
        from services.ai.vllm import _normalize_base_url

        assert _normalize_base_url("http://172.31.57.67:8000/v1") == ("http://172.31.57.67:8000/v1")

    def test_vllm_base_url_trims_chat_completions_endpoint(self):
        from services.ai.vllm import _normalize_base_url

        assert (
            _normalize_base_url("http://172.31.57.67:8000/v1/chat/completions")
            == "http://172.31.57.67:8000/v1"
        )

    @patch("services.ai.vllm.ChatOpenAI")
    def test_vllm_get_llm_passes_api_root_to_chat_openai(self, mock_chat_openai):
        from services.ai.vllm import get_llm

        with patch.dict(
            os.environ,
            {
                "VLLM_BASE_URL": "http://172.31.57.67:8000/v1/chat/completions",
                "VLLM_MODEL": "Qwen3.8-27B",
            },
        ):
            get_llm(max_tokens=256)

        call_kwargs = mock_chat_openai.call_args[1]
        assert call_kwargs["base_url"] == "http://172.31.57.67:8000/v1"
        assert call_kwargs["model"] == "Qwen3.8-27B"
        assert call_kwargs["max_tokens"] == 256
        assert call_kwargs["disabled_params"] == {"parallel_tool_calls": None}

    def test_vllm_model_metadata_uses_token_env_overrides(self):
        from services.ai import vllm

        with patch.dict(
            os.environ,
            {"VLLM_MAX_TOKENS": "2048", "VLLM_CONTEXT_WINDOW": "8192"},
        ):
            model = vllm.get_available_models()[0]

        assert model.max_tokens == 2048
        assert model.context_window == 8192

    @patch("services.ai.vllm.ChatOpenAI")
    def test_vllm_get_llm_clamps_to_configured_max_tokens(self, mock_chat_openai):
        from services.ai.vllm import get_llm

        with patch.dict(os.environ, {"VLLM_MAX_TOKENS": "2048"}):
            get_llm(max_tokens=4096)

        assert mock_chat_openai.call_args[1]["max_tokens"] == 2048

    def test_vllm_models_disable_parallel_tool_calls_by_default(self):
        from services.ai import vllm

        models = vllm.get_available_models()

        assert models[0].supports_tools is True
        assert models[0].supports_parallel_tool_calls is False

    def test_vllm_metrics_url_uses_configured_endpoint(self):
        from services.ai.vllm import get_metrics_url

        with patch.dict(os.environ, {"VLLM_METRICS_URL": "http://172.31.57.67:8000"}):
            assert get_metrics_url() == "http://172.31.57.67:8000/metrics"

        with patch.dict(os.environ, {"VLLM_METRICS_URL": "http://172.31.57.67:8000/metrics"}):
            assert get_metrics_url() == "http://172.31.57.67:8000/metrics"

    @patch("services.ai.vllm.ChatOpenAI")
    def test_vllm_get_llm_enables_stream_usage(self, mock_chat_openai):
        from services.ai.vllm import get_llm

        get_llm(max_tokens=256)

        assert mock_chat_openai.call_args[1]["stream_usage"] is True

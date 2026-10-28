"""Implementation for vLLM (OpenAI-compatible) LLM provider."""

from os import getenv
from typing import Optional
from urllib.parse import urlsplit, urlunsplit

import httpx
from langchain_openai import ChatOpenAI

from models.model_info import ModelInfo

DEFAULT_VLLM_BASE_URL = "http://172.31.57.67:8000/v1"
DEFAULT_VLLM_METRICS_URL = "http://172.31.57.67:8000/metrics"
DEFAULT_VLLM_MODEL = "Qwen3.8-27B"
DEFAULT_VLLM_MAX_TOKENS = 4096
DEFAULT_VLLM_CONTEXT_WINDOW = 32768

# Models served by the vLLM endpoint, in selection order. The first entry is
# the default used when no explicit model is configured. Keep this in sync with
# the models actually loaded into the vLLM server (names must match exactly).
VLLM_MODELS = ["Qwen3.8-27B", "qwen3.6-27B"]


def _get_positive_int_env(name: str, default: int) -> int:
    """Read a positive integer environment variable with a safe fallback."""
    raw_value = getenv(name)
    if raw_value is None or raw_value.strip() == "":
        return default

    try:
        value = int(raw_value)
    except ValueError:
        return default

    return value if value > 0 else default


def _normalize_base_url(base_url: str) -> str:
    """Return the OpenAI-compatible API root expected by ChatOpenAI.

    ChatOpenAI expects a base URL such as ``http://host:8000/v1`` and appends
    ``/chat/completions`` internally. Users often copy the full endpoint from
    API test tools, so trim that suffix to avoid requests like
    ``/v1/chat/completions/chat/completions``.
    """
    url = (base_url or DEFAULT_VLLM_BASE_URL).strip().rstrip("/")
    endpoint_suffix = "/chat/completions"
    if url.endswith(endpoint_suffix):
        url = url[: -len(endpoint_suffix)]

    parts = urlsplit(url)
    if parts.path == "":
        url = urlunsplit((parts.scheme, parts.netloc, "/v1", "", ""))
    return url.rstrip("/")


def _normalize_metrics_url(metrics_url: str) -> str:
    """Return the vLLM Prometheus metrics endpoint URL."""
    url = (metrics_url or DEFAULT_VLLM_METRICS_URL).strip().rstrip("/")
    if not url.endswith("/metrics"):
        url = f"{url}/metrics"
    return url


def get_metrics_url() -> str:
    """Get the configured vLLM Prometheus metrics endpoint."""
    return _normalize_metrics_url(getenv("VLLM_METRICS_URL", DEFAULT_VLLM_METRICS_URL))


def is_available() -> bool:
    """Check if vLLM provider is available (base URL configured)."""
    base_url = getenv("VLLM_BASE_URL")
    return base_url is not None and base_url != ""


def get_available_models() -> list[ModelInfo]:
    """Get list of available vLLM models.

    Returns every model declared in ``VLLM_MODELS`` so that each served version
    can be selected. Token/context limits are shared and may be overridden via
    ``VLLM_MAX_TOKENS`` / ``VLLM_CONTEXT_WINDOW`` environment variables.
    """
    max_tokens = _get_positive_int_env("VLLM_MAX_TOKENS", DEFAULT_VLLM_MAX_TOKENS)
    context_window = _get_positive_int_env("VLLM_CONTEXT_WINDOW", DEFAULT_VLLM_CONTEXT_WINDOW)
    return [
        ModelInfo(
            name=model_name,
            max_tokens=max_tokens,
            input_cost_per_million=0.0,
            output_cost_per_million=0.0,
            cache_cost_per_million=0.0,
            description=f"vLLM - {model_name} model",
            supports_tools=True,
            supports_vision=False,
            context_window=context_window,
            supports_parallel_tool_calls=False,
            tool_calling_quality="excellent",
            reasoning_capability="advanced",
        )
        for model_name in VLLM_MODELS
    ]


def _get_enable_thinking() -> bool:
    """Whether Qwen3-style thinking is enabled for the vLLM model.

    Defaults to False. Thinking blocks leak into ``message.content`` and waste
    tokens, which is undesirable for the ReAct/tool-calling agent loop. Set
    ``VLLM_ENABLE_THINKING=true`` to turn them on.
    """
    return getenv("VLLM_ENABLE_THINKING", "false").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def get_llm(max_tokens: int = 6000, model_name: Optional[str] = None):
    """Get ChatOpenAI instance configured for vLLM.

    Args:
        max_tokens: Maximum tokens to generate
        model_name: Specific model to use (overrides env var)

    Returns:
        ChatOpenAI instance configured for vLLM API
    """
    model = model_name or getenv("VLLM_MODEL", DEFAULT_VLLM_MODEL)
    base_url = _normalize_base_url(getenv("VLLM_BASE_URL", DEFAULT_VLLM_BASE_URL))
    api_key = getenv("VLLM_API_KEY", "none")
    configured_max_tokens = _get_positive_int_env("VLLM_MAX_TOKENS", DEFAULT_VLLM_MAX_TOKENS)
    max_tokens = min(max_tokens, configured_max_tokens)

    # Qwen3-style thinking blocks leak into message.content (polluting the
    # streamed reply and conversation history) and burn tokens. Default off
    # for the ReAct/tool-calling agent; set VLLM_ENABLE_THINKING=true to enable.
    extra_body = {"chat_template_kwargs": {"enable_thinking": _get_enable_thinking()}}

    return ChatOpenAI(
        model=model,
        base_url=base_url,
        api_key=api_key,
        temperature=float(getenv("VLLM_TEMPERATURE", "0.5")),
        max_tokens=max_tokens,
        timeout=httpx.Timeout(_get_positive_int_env("VLLM_REQUEST_TIMEOUT", 120), connect=10.0),
        max_retries=1,
        stream_usage=True,
        disabled_params={"parallel_tool_calls": None},
        extra_body=extra_body,
    )

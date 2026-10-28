import os
import logging
from typing import Optional, Tuple
from dataclasses import dataclass

from dotenv import load_dotenv

logger = logging.getLogger(__name__)

# Load local development overrides before the shared .env file.
load_dotenv(".env.local", override=True)
load_dotenv()
llm_provider = os.getenv("LLM_PROVIDER", "deepseek").lower()


if llm_provider == "deepseek":
    from .deepseek import get_llm
elif llm_provider == "kimi":
    from .kimi import get_llm  # noqa: F401
elif llm_provider == "vllm":
    from .vllm import get_llm  # noqa: F401
else:
    raise ValueError(f"Unsupported LLM provider: {llm_provider}")


@dataclass
class ModelCapabilities:
    """Model capabilities metadata extracted during LLM initialization."""

    supports_parallel_tool_calls: bool = False
    context_window: int = 128000
    max_tokens: int = 4096


def get_llm_for_provider(
    provider_name: str, max_tokens: int = 6000, model_name: Optional[str] = None
) -> Tuple:
    """Get LLM instance and capabilities for a specific provider with validated max_tokens.

    Args:
        provider_name: Provider identifier (deepseek, kimi, vllm)
        max_tokens: Maximum tokens to generate (will be validated against model's limit)
        model_name: Specific model to use (optional, provider-specific default if not provided)

    Returns:
        Tuple of (LLM instance, ModelCapabilities) for the specified provider

    Raises:
        ValueError: If provider_name is not recognized
    """
    provider_name = provider_name.lower()

    if provider_name not in ("deepseek", "kimi", "vllm"):
        logger.warning(
            f"Unsupported LLM provider '{provider_name}' requested, "
            f"falling back to default '{llm_provider}'"
        )
        provider_name = llm_provider

    # Get model info and validate max_tokens
    validated_max_tokens, capabilities = _validate_max_tokens_and_get_capabilities(
        provider_name, max_tokens, model_name
    )

    # Fallback model_name if unsupported by the resolved provider
    target_model_name = model_name
    try:
        if provider_name == "deepseek":
            from .deepseek import get_available_models

            models = get_available_models()
            if model_name and not any(m.name == model_name for m in models) and models:
                target_model_name = models[0].name
        elif provider_name == "kimi":
            from .kimi import get_available_models

            models = get_available_models()
            if model_name and not any(m.name == model_name for m in models) and models:
                target_model_name = models[0].name
        elif provider_name == "vllm":
            from .vllm import get_available_models

            models = get_available_models()
            if model_name and not any(m.name == model_name for m in models) and models:
                target_model_name = models[0].name
    except Exception:
        pass

    if provider_name == "deepseek":
        from .deepseek import get_llm as deepseek_get_llm

        llm = deepseek_get_llm(max_tokens=validated_max_tokens, model_name=target_model_name)
        return llm, capabilities
    elif provider_name == "kimi":
        from .kimi import get_llm as kimi_get_llm

        llm = kimi_get_llm(max_tokens=validated_max_tokens, model_name=target_model_name)
        return llm, capabilities
    elif provider_name == "vllm":
        from .vllm import get_llm as vllm_get_llm

        llm = vllm_get_llm(max_tokens=validated_max_tokens, model_name=target_model_name)
        return llm, capabilities
    else:
        raise ValueError(
            f"Unsupported LLM provider: {provider_name}. "
            "Supported providers: deepseek, kimi, vllm"
        )


def _validate_max_tokens_and_get_capabilities(
    provider_name: str, max_tokens: int, model_name: Optional[str] = None
) -> Tuple[int, ModelCapabilities]:
    """Validate max_tokens and extract model capabilities.

    Args:
        provider_name: Provider identifier
        max_tokens: Requested max tokens
        model_name: Specific model name (optional)

    Returns:
        Tuple of (validated_max_tokens, ModelCapabilities)
    """
    # Default capabilities
    capabilities = ModelCapabilities()

    # Import provider module to get available models
    try:
        if provider_name == "deepseek":
            from .deepseek import get_available_models
        elif provider_name == "kimi":
            from .kimi import get_available_models
        elif provider_name == "vllm":
            from .vllm import get_available_models
        else:
            # Unknown provider, return defaults
            return max_tokens, capabilities

        models = get_available_models()

        # Find the specific model or use first model as default
        target_model = None
        if model_name:
            target_model = next((m for m in models if m.name == model_name), None)

        if not target_model and models:
            # No specific model found, use first available
            target_model = models[0]

        if target_model:
            # Extract capabilities from model info
            capabilities = ModelCapabilities(
                supports_parallel_tool_calls=getattr(
                    target_model, "supports_parallel_tool_calls", False
                ),
                context_window=getattr(target_model, "context_window", 128000),
                max_tokens=target_model.max_tokens,
            )

            # Validate max_tokens
            if max_tokens <= 0 or max_tokens > target_model.max_tokens:
                # Invalid or exceeds limit, use model's default
                return target_model.max_tokens, capabilities

        return max_tokens, capabilities

    except Exception:
        # If anything fails, return original max_tokens with default capabilities
        return max_tokens, capabilities


def _validate_max_tokens(
    provider_name: str, max_tokens: int, model_name: Optional[str] = None
) -> int:
    """Validate max_tokens against model's maximum limit.

    DEPRECATED: Use _validate_max_tokens_and_get_capabilities instead.
    This function is kept for backwards compatibility.

    Args:
        provider_name: Provider identifier
        max_tokens: Requested max tokens
        model_name: Specific model name (optional)

    Returns:
        Validated max_tokens (clamped to model's limit if necessary)
    """
    validated_max_tokens, _ = _validate_max_tokens_and_get_capabilities(
        provider_name, max_tokens, model_name
    )
    return validated_max_tokens

"""Unified interface for querying all LLM providers."""

import logging
import os
from typing import Dict

from models.model_info import ProviderInfo

logger = logging.getLogger(__name__)


def get_all_providers() -> Dict[str, ProviderInfo]:
    """Get information about all LLM providers and their availability.

    Returns:
        Dictionary mapping provider name to ProviderInfo with availability
        status and available models. Order is determined by DEFAULT_LLM_PROVIDER
        or LLM_PROVIDER environment variable if set.
    """
    providers_unordered: Dict[str, ProviderInfo] = {}

    # DeepSeek
    try:
        from services.ai import deepseek

        is_available = deepseek.is_available()
        models = deepseek.get_available_models() if is_available else []

        providers_unordered["deepseek"] = ProviderInfo(
            name="deepseek",
            display_name="DeepSeek",
            available=is_available,
            models=models,
            error_message=None if is_available else "API key not configured",
        )
    except Exception as e:
        logger.warning(f"Failed to load DeepSeek provider: {e}")
        providers_unordered["deepseek"] = ProviderInfo(
            name="deepseek",
            display_name="DeepSeek",
            available=False,
            models=[],
            error_message=str(e),
        )

    # KIMI
    try:
        from services.ai import kimi

        is_available = kimi.is_available()
        models = kimi.get_available_models() if is_available else []

        providers_unordered["kimi"] = ProviderInfo(
            name="kimi",
            display_name="KIMI",
            available=is_available,
            models=models,
            error_message=None if is_available else "API key not configured",
        )
    except Exception as e:
        logger.warning(f"Failed to load KIMI provider: {e}")
        providers_unordered["kimi"] = ProviderInfo(
            name="kimi",
            display_name="KIMI",
            available=False,
            models=[],
            error_message=str(e),
        )

    # vLLM
    try:
        from services.ai import vllm

        is_available = vllm.is_available()
        models = vllm.get_available_models() if is_available else []

        providers_unordered["vllm"] = ProviderInfo(
            name="vllm",
            display_name="vLLM",
            available=is_available,
            models=models,
            error_message=None if is_available else "vLLM Base URL not configured",
        )
    except Exception as e:
        logger.warning(f"Failed to load vLLM provider: {e}")
        providers_unordered["vllm"] = ProviderInfo(
            name="vllm",
            display_name="vLLM",
            available=False,
            models=[],
            error_message=str(e),
        )

    # Order providers based on DEFAULT_LLM_PROVIDER or LLM_PROVIDER env var
    # The first provider in the ordered dict will be selected by default in the UI
    preferred_provider = (
        os.getenv("DEFAULT_LLM_PROVIDER", "").lower().strip()
        or os.getenv("LLM_PROVIDER", "").lower().strip()
    )

    # If a preferred provider is set and exists, put it first
    providers: Dict[str, ProviderInfo] = {}
    if preferred_provider and preferred_provider in providers_unordered:
        providers[preferred_provider] = providers_unordered[preferred_provider]
        logger.info(f"Prioritizing provider '{preferred_provider}' as default")

    # Add remaining providers in their original order
    for name, info in providers_unordered.items():
        if name not in providers:
            providers[name] = info

    return providers


def get_provider_by_name(provider_name: str) -> ProviderInfo:
    """Get information about a specific provider.

    Args:
        provider_name: Name of the provider (e.g., "openai", "google")

    Returns:
        ProviderInfo for the specified provider

    Raises:
        ValueError: If provider name is not recognized
    """
    providers = get_all_providers()
    if provider_name not in providers:
        raise ValueError(
            f"Unknown provider: {provider_name}. "
            f"Available providers: {', '.join(providers.keys())}"
        )
    return providers[provider_name]

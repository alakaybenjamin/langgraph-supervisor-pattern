"""Centralised LLM / embeddings factory.

All graph nodes and services should obtain their model instances through
:func:`get_chat_llm` and :func:`get_embeddings` rather than constructing
``ChatOpenAI`` / ``AzureChatOpenAI`` directly.  The active provider is
controlled by the ``LLM_PROVIDER`` environment variable.
"""

from __future__ import annotations

import logging

from langchain_core.embeddings import Embeddings
from langchain_core.language_models import BaseChatModel
from langchain_openai import (
    AzureChatOpenAI,
    AzureOpenAIEmbeddings,
    ChatOpenAI,
    OpenAIEmbeddings,
)

from app.core.config import settings

logger = logging.getLogger(__name__)

_MINI_MODEL = "gpt-4o-mini"


def get_chat_llm(model: str | None = None, **kwargs) -> BaseChatModel:
    """Return a chat LLM configured for the active provider.

    Parameters
    ----------
    model:
        Model / deployment override.  When *None*, the provider's default
        deployment is used (``MODEL_NAME`` for OpenAI, ``KONG_DEPLOYMENT``
        for Azure/Kong).  Passing ``"gpt-4o-mini"`` automatically maps to
        ``KONG_MINI_DEPLOYMENT`` when using Azure/Kong.
    **kwargs:
        Forwarded to the underlying LangChain chat-model constructor
        (e.g. ``temperature``, ``max_tokens``).
    """
    if settings.LLM_PROVIDER == "azure_kong":
        from app.core.kong_auth import get_token_provider

        deployment = _resolve_azure_deployment(model)
        logger.debug(
            "Creating AzureChatOpenAI (deployment=%s, endpoint=%s)",
            deployment,
            settings.KONG_BASE_URL,
        )
        return AzureChatOpenAI(
            azure_endpoint=settings.KONG_BASE_URL,
            azure_deployment=deployment,
            api_version=settings.KONG_API_VERSION,
            azure_ad_token_provider=get_token_provider(),
            **kwargs,
        )

    resolved_model = model or settings.MODEL_NAME
    logger.debug("Creating ChatOpenAI (model=%s)", resolved_model)
    return ChatOpenAI(
        model=resolved_model,
        api_key=settings.OPENAI_API_KEY,
        **kwargs,
    )


def get_embeddings(**kwargs) -> Embeddings:
    """Return an embeddings model configured for the active provider."""
    if settings.LLM_PROVIDER == "azure_kong":
        from app.core.kong_auth import get_token_provider

        logger.debug(
            "Creating AzureOpenAIEmbeddings (deployment=%s)",
            settings.KONG_EMBEDDING_DEPLOYMENT,
        )
        return AzureOpenAIEmbeddings(
            azure_endpoint=settings.KONG_BASE_URL,
            azure_deployment=settings.KONG_EMBEDDING_DEPLOYMENT,
            api_version=settings.KONG_API_VERSION,
            azure_ad_token_provider=get_token_provider(),
            **kwargs,
        )

    logger.debug("Creating OpenAIEmbeddings (model=%s)", settings.EMBEDDING_MODEL)
    return OpenAIEmbeddings(
        model=settings.EMBEDDING_MODEL,
        api_key=settings.OPENAI_API_KEY,
        **kwargs,
    )


def _resolve_azure_deployment(model: str | None) -> str:
    """Map a model name to the correct Azure deployment setting."""
    if model is None:
        return settings.KONG_DEPLOYMENT
    if model == _MINI_MODEL:
        return settings.KONG_MINI_DEPLOYMENT
    return model

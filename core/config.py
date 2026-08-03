"""Configuracion central: modelo resiliente, rutas y umbrales.

Regla de Oro del JSON (Guia Entorno 3.5): toda llamada del agente involucra
tool-calling potencial, asi que temperature=0.0 va fijo en cada modelo que
esta funcion construye. No es configurable por env var a proposito.
"""

import os

_TEMPERATURE = 0.0


def _build_model(provider: str, model_id: str):
    provider = provider.strip().lower()
    if provider == "openai":
        from agno.models.openai import OpenAIChat

        return OpenAIChat(id=model_id, temperature=_TEMPERATURE)
    if provider == "anthropic":
        from agno.models.anthropic import Claude

        return Claude(id=model_id, temperature=_TEMPERATURE)
    if provider == "ollama":
        from agno.models.ollama import Ollama

        host = os.getenv("OLLAMA_HOST", "http://localhost:11434")
        return Ollama(id=model_id, host=host, options={"temperature": _TEMPERATURE})
    raise ValueError(f"Proveedor de modelo no soportado: {provider}")


def get_resilient_model():
    """Modelo primario del agente. temperature=0.0 siempre (tool-calling)."""
    provider = os.getenv("OKF_PRIMARY_MODEL_PROVIDER", "openai")
    model_id = os.getenv("OKF_PRIMARY_MODEL_ID", "gpt-4o-mini")
    return _build_model(provider, model_id)


def get_fallback_models() -> list:
    """Modelos de fallback (Ent. 3.3), probados en orden tras agotar reintentos
    del primario. Pensado para pasarse como `fallback_models=` al Agent.
    """
    raw = os.getenv("OKF_FALLBACK_MODELS", "")
    models = []
    for entry in raw.split(","):
        entry = entry.strip()
        if not entry:
            continue
        provider, _, model_id = entry.partition(":")
        if not model_id:
            continue
        models.append(_build_model(provider, model_id))
    return models


def get_judge_model():
    """Modelo acotado para el pase de juez de canonicalizacion de tags.
    Misma regla de temperature=0.0; deliberadamente el mismo modelo primario
    salvo que se configure OKF_JUDGE_MODEL_ID.
    """
    provider = os.getenv("OKF_PRIMARY_MODEL_PROVIDER", "openai")
    model_id = os.getenv("OKF_JUDGE_MODEL_ID") or os.getenv("OKF_PRIMARY_MODEL_ID", "gpt-4o-mini")
    return _build_model(provider, model_id)


def get_vault_root() -> str:
    return os.getenv("OKF_VAULT_ROOT", "fixtures/sample_vault")


def get_tag_similarity_threshold() -> float:
    return float(os.getenv("OKF_TAG_SIMILARITY_THRESHOLD", "0.82"))

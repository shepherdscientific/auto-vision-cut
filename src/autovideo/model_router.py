"""LLM provider router for the AutoVisionCut pipeline.

Abstracts away local (mlx_lm) and remote (OpenAI-compatible) LLM
backends behind a unified call/load interface.
"""

import os
import sys
import time
from typing import Any, Protocol

from autovideo.logging_setup import get_module_logger

logger = get_module_logger(__name__)

BACKOFF = 2.0
DELAY = 1.0
MAX_RETRIES = 3

OPENAI_BASE_URL_ENV = "OPENAI_BASE_URL"


class RouterError(Exception):
    """Raised on unrecoverable LLM routing failures."""


class LlmProvider(Protocol):
    def load(self, model_path: str) -> tuple[Any, Any] | None: ...

    def generate(
        self, model: Any, tokenizer: Any, prompt: str, max_tokens: int = 4096
    ) -> str: ...

    def name(self) -> str: ...


class _MlxLmProvider:
    def load(self, model_path: str) -> tuple[Any, Any] | None:
        llm_mod = sys.modules.get("mlx_lm")
        if llm_mod is None:
            try:
                import mlx_lm as _mlx  # noqa: F811
                llm_mod = _mlx
            except ImportError:
                return None
        if llm_mod is None:
            return None
        try:
            logger.info("Loading mlx_lm model: %s", model_path)
            load_result = llm_mod.load(model_path)
            logger.info("mlx_lm model loaded")
            return (load_result[0], load_result[1])
        except Exception as exc:
            logger.warning("Failed to load mlx_lm model %s: %s", model_path, exc)
            return None

    def generate(
        self, model: Any, tokenizer: Any, prompt: str, max_tokens: int = 4096
    ) -> str:
        mlx_lm = sys.modules.get("mlx_lm")
        if mlx_lm is None:
            raise RouterError("mlx_lm not available")
        last_exception: Exception | None = None
        delay = DELAY
        for attempt in range(MAX_RETRIES + 1):
            try:
                return mlx_lm.generate(model, tokenizer, prompt, max_tokens=max_tokens)
            except Exception as exc:
                last_exception = exc
                if attempt < MAX_RETRIES:
                    logger.warning(
                        "mlx_lm generate attempt %d/%d failed: %s — retrying in %.1fs",
                        attempt + 1, MAX_RETRIES + 1, exc, delay,
                    )
                    time.sleep(delay)
                    delay *= BACKOFF
        raise RouterError(
            f"mlx_lm generation failed after {MAX_RETRIES + 1} attempts: {last_exception}"
        )

    def name(self) -> str:
        return "mlx_lm"


class _OpenAiProvider:
    def __init__(self, base_url: str | None = None, api_key: str | None = None) -> None:
        self.base_url = base_url or os.environ.get(OPENAI_BASE_URL_ENV, "https://api.openai.com/v1")
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY", "")

    def load(self, model_path: str) -> tuple[Any, Any] | None:
        from openai import OpenAI
        self._client = OpenAI(base_url=self.base_url, api_key=self.api_key)
        self._model_name = model_path
        logger.info(
            "OpenAI-compatible provider ready: model=%s, base_url=%s",
            model_path, self.base_url,
        )
        return (self._client, None)

    def generate(
        self, model: Any, tokenizer: Any, prompt: str, max_tokens: int = 4096
    ) -> str:
        client = model
        last_exception: Exception | None = None
        delay = DELAY
        for attempt in range(MAX_RETRIES + 1):
            try:
                response = client.chat.completions.create(
                    model=self._model_name,
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=max_tokens,
                )
                return response.choices[0].message.content or ""
            except Exception as exc:
                last_exception = exc
                if attempt < MAX_RETRIES:
                    logger.warning(
                        "OpenAI generate attempt %d/%d failed: %s — retrying in %.1fs",
                        attempt + 1, MAX_RETRIES + 1, exc, delay,
                    )
                    time.sleep(delay)
                    delay *= BACKOFF
        raise RouterError(
            f"OpenAI generation failed after {MAX_RETRIES + 1} attempts: {last_exception}"
        )

    def name(self) -> str:
        return "openai"


def get_provider(provider_name: str, base_url: str | None = None) -> LlmProvider:
    name = provider_name.strip().lower()
    if name == "mlx_lm":
        return _MlxLmProvider()
    elif name in ("openai", "openai-compatible"):
        return _OpenAiProvider(base_url=base_url)
    else:
        raise RouterError(f"Unknown LLM provider: {provider_name!r}")


def load_and_generate(
    provider_name: str,
    model_path: str,
    prompt: str,
    max_tokens: int = 4096,
    base_url: str | None = None,
) -> str:
    provider = get_provider(provider_name, base_url=base_url)
    loaded = provider.load(model_path)
    if loaded is None:
        raise RouterError(f"Failed to load model {model_path} with provider {provider_name}")
    model, tokenizer = loaded
    return provider.generate(model, tokenizer, prompt, max_tokens=max_tokens)

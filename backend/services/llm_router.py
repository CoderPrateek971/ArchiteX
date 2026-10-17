import logging
import os
import sys

# Ensure packaging alias for environments where pip has vendored packaging
try:
    import packaging
except ImportError:
    try:
        import pip._vendor.packaging as pkg
        from pip._vendor.packaging import version
        sys.modules["packaging"] = pkg
        sys.modules["packaging.version"] = version
    except Exception:
        pass

from dotenv import load_dotenv

LITELLM_AVAILABLE = False
try:
    from litellm import completion
    from litellm.exceptions import (
        APIConnectionError,
        APIError,
        RateLimitError,
        ServiceUnavailableError,
        Timeout,
    )
    LITELLM_AVAILABLE = True
except Exception as _import_err:
    completion = None
    APIConnectionError = Exception
    APIError = Exception
    RateLimitError = Exception
    ServiceUnavailableError = Exception
    Timeout = Exception

load_dotenv()

logger = logging.getLogger(__name__)

PRIMARY_MODEL = os.getenv("PRIMARY_LLM_MODEL", "gpt-4o")
FALLBACK_MODEL = os.getenv("FALLBACK_LLM_MODEL", "gemini/gemini-1.5-pro")

_RETRYABLE_ERRORS = (
    RateLimitError,
    APIError,
    APIConnectionError,
    ServiceUnavailableError,
    Timeout,
)


def generate_completion(
    prompt: str,
    *,
    system: str | None = None,
    json_mode: bool = False,
) -> dict:
    """Call the primary model, then fall back if it fails or is rate-limited."""
    messages: list[dict] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    try:
        response = _complete(PRIMARY_MODEL, messages, json_mode=json_mode)
        return _unpack(response, PRIMARY_MODEL, fallback_used=False)
    except _RETRYABLE_ERRORS as exc:
        logger.warning(
            "Primary model %s failed (%s). Falling back to %s.",
            PRIMARY_MODEL,
            type(exc).__name__,
            FALLBACK_MODEL,
        )
        response = _complete(FALLBACK_MODEL, messages, json_mode=json_mode)
        return _unpack(response, FALLBACK_MODEL, fallback_used=True)


def _complete(model: str, messages: list[dict], json_mode: bool = False):
    if completion is None:
        raise RuntimeError("LiteLLM is not installed or available.")
    kwargs: dict = {"model": model, "messages": messages}
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}
        try:
            return completion(**kwargs)
        except _RETRYABLE_ERRORS:
            raise
        except Exception:
            logger.info("JSON response_format unsupported for %s; retrying without it.", model)
            kwargs.pop("response_format", None)
    return completion(**kwargs)


def _unpack(response, model: str, fallback_used: bool) -> dict:
    content = response.choices[0].message.content or ""
    return {
        "content": content,
        "model": model,
        "fallback_used": fallback_used,
    }

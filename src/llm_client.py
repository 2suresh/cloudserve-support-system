import json
import logging
import time

from openai import APIConnectionError, APIError, APITimeoutError, OpenAI, RateLimitError

from src import config

logger = logging.getLogger("cloudserve.llm")

_client: OpenAI | None = None


class ProviderError(Exception):
    """Raised once retries are exhausted. Callers must handle this and fall back
    rather than letting a provider outage crash ticket processing (A11)."""


def get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(
            api_key=config.LLM_API_KEY,
            base_url=config.LLM_BASE_URL,
            timeout=config.LLM_TIMEOUT_SECONDS,
            max_retries=0,  # retries are handled explicitly below, with our own fallback path
        )
    return _client


def _call(system_prompt: str, user_content: str, json_mode: bool) -> str:
    client = get_client()
    last_error: Exception | None = None
    for attempt in range(config.LLM_MAX_RETRIES + 1):
        try:
            kwargs = {}
            if json_mode:
                kwargs["response_format"] = {"type": "json_object"}
            response = client.chat.completions.create(
                model=config.MODEL_NAME,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_content},
                ],
                temperature=0.0,
                **kwargs,
            )
            return response.choices[0].message.content or ""
        except (RateLimitError, APITimeoutError, APIConnectionError, APIError) as exc:
            last_error = exc
            logger.warning("LLM call failed (attempt %s/%s): %s", attempt + 1, config.LLM_MAX_RETRIES + 1, exc)
            if attempt < config.LLM_MAX_RETRIES:
                time.sleep(config.LLM_BACKOFF_BASE_SECONDS * (2**attempt))
    raise ProviderError(str(last_error))


def chat_text(system_prompt: str, user_content: str) -> str:
    return _call(system_prompt, user_content, json_mode=False)


def chat_json(system_prompt: str, user_content: str) -> dict:
    raw = _call(system_prompt, user_content, json_mode=True)
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ProviderError(f"model returned non-JSON output: {exc}") from exc

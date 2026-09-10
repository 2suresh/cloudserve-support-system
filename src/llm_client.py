import json
import logging
import queue
import threading
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


def _single_attempt(system_prompt: str, user_content: str, json_mode: bool) -> str:
    client = get_client()
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


def _run_with_hard_deadline(system_prompt: str, user_content: str, json_mode: bool, deadline_seconds: float):
    """Runs one attempt on a daemon thread with a hard wall-clock deadline.

    A stale, half-dead pooled connection (observed as CLOSE_WAIT in production
    testing) hung well past LLM_TIMEOUT_SECONDS without httpx's own timeout
    firing -- a real bug found via a 46-minute-stuck evaluation run, not a
    hypothetical. Enforcing the deadline in the calling thread, independent of
    whatever httpx is doing internally, is what actually bounds it. The worker
    thread is daemon=True and we never join it: if the call is truly stuck, we
    abandon it and move on rather than let it block process exit later.
    """
    result_queue: queue.Queue = queue.Queue(maxsize=1)

    def _worker():
        try:
            result_queue.put(("ok", _single_attempt(system_prompt, user_content, json_mode)))
        except Exception as exc:  # noqa: BLE001 - deliberately broad, forwarded to the caller
            result_queue.put(("error", exc))

    threading.Thread(target=_worker, daemon=True).start()
    try:
        status, value = result_queue.get(timeout=deadline_seconds)
    except queue.Empty:
        raise TimeoutError(f"LLM call exceeded {deadline_seconds}s hard wall-clock deadline") from None
    if status == "error":
        raise value
    return value


def _call(system_prompt: str, user_content: str, json_mode: bool) -> str:
    last_error: Exception | None = None
    deadline = config.LLM_TIMEOUT_SECONDS + 5
    for attempt in range(config.LLM_MAX_RETRIES + 1):
        try:
            return _run_with_hard_deadline(system_prompt, user_content, json_mode, deadline)
        except TimeoutError as exc:
            last_error = exc
            logger.warning(
                "LLM call exceeded hard wall-clock deadline (attempt %s/%s) -- abandoning it, "
                "the underlying request may still be hanging in the background",
                attempt + 1, config.LLM_MAX_RETRIES + 1,
            )
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

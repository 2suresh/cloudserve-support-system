import time

import pytest

from src import config, llm_client


def test_hung_call_is_abandoned_within_the_hard_deadline(monkeypatch):
    """Reproduces the real bug: a call that never returns (observed in
    production as a stale CLOSE_WAIT connection httpx's own timeout never
    caught) must not block the pipeline forever. _call must give up and raise
    ProviderError within a bounded wall-clock time, not hang."""
    monkeypatch.setattr(config, "LLM_TIMEOUT_SECONDS", 0.2)
    monkeypatch.setattr(config, "LLM_MAX_RETRIES", 1)
    monkeypatch.setattr(config, "LLM_BACKOFF_BASE_SECONDS", 0.01)

    def _hangs_forever(system_prompt, user_content, json_mode):
        time.sleep(30)  # far longer than any deadline this test allows
        return "should never get here"

    monkeypatch.setattr(llm_client, "_single_attempt", _hangs_forever)

    t0 = time.time()
    with pytest.raises(llm_client.ProviderError):
        llm_client._call("system", "user", json_mode=False)
    elapsed = time.time() - t0

    # 2 attempts * (0.2 + 5) deadline each, plus trivial backoff -- generous
    # upper bound that would still catch a real hang (30s+) failing this test.
    assert elapsed < 15, f"took {elapsed:.1f}s -- the hard deadline did not bound it"


def test_successful_call_returns_normally(monkeypatch):
    monkeypatch.setattr(llm_client, "_single_attempt", lambda system_prompt, user_content, json_mode: "real answer")
    assert llm_client._call("system", "user", json_mode=False) == "real answer"

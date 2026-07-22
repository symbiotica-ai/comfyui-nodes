# ABOUTME: Tests that a Grok video job stops when ComfyUI's Cancel is pressed,
# ABOUTME: and that a rejected job reports the reason instead of polling on.
import pytest

from grok_api import client as client_mod
from grok_api.client import GrokClient, GrokInterrupted, GrokVideoFailed


@pytest.fixture
def polling(monkeypatch):
    """A client on a fake clock: sleeping advances time, so a loop that fails
    to stop hits its own timeout in milliseconds instead of hanging."""
    now = {"t": 0.0}
    monkeypatch.setattr(client_mod.time, "time", lambda: now["t"])
    monkeypatch.setattr(client_mod.time, "sleep",
                        lambda s: now.__setitem__("t", now["t"] + max(s, 0.01)))
    c = GrokClient(api_key="x")
    c.polls = 0
    return c


def test_cancel_before_the_first_poll_asks_the_api_nothing(polling, monkeypatch):
    monkeypatch.setattr(client_mod, "_resolve_interrupt_checker",
                        lambda: (lambda: True))
    polling.get = lambda endpoint, timeout=30: (
        polling.__setattr__("polls", polling.polls + 1) or {"status": "processing"})

    with pytest.raises(GrokInterrupted):
        polling.wait_for_video("req-1", polling_interval=5, timeout=600)
    assert polling.polls == 0, f"polled a cancelled job ({polling.polls} times)"


def test_the_retry_handler_does_not_swallow_an_interrupt(polling, monkeypatch):
    monkeypatch.setattr(client_mod, "_resolve_interrupt_checker",
                        lambda: (lambda: False))

    def get_that_interrupts(endpoint, timeout=30):
        polling.polls += 1
        raise GrokInterrupted("cancelled mid-request")
    polling.get = get_that_interrupts

    with pytest.raises(GrokInterrupted):
        polling.wait_for_video("req-1", polling_interval=5, timeout=600)
    assert polling.polls == 1, f"retried after an interrupt ({polling.polls} polls)"


def test_a_failed_job_reports_instead_of_polling_on(polling, monkeypatch):
    # The failure was raised inside the try, so the retry handler caught it and
    # kept polling — ten minutes later the user was told it timed out, not why.
    monkeypatch.setattr(client_mod, "_resolve_interrupt_checker",
                        lambda: (lambda: False))

    def get_failed(endpoint, timeout=30):
        polling.polls += 1
        return {"status": "failed", "error": "content policy"}
    polling.get = get_failed

    with pytest.raises(GrokVideoFailed) as err:
        polling.wait_for_video("req-1", polling_interval=5, timeout=600)
    assert "content policy" in str(err.value)
    assert polling.polls == 1, f"retried a failed job ({polling.polls} polls)"

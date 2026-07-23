# ABOUTME: Tests that a queued Wavespeed job stops when ComfyUI's Cancel is
# ABOUTME: pressed, and that a failed job reports instead of polling on.
import pytest

from wavespeed_api import client as client_mod
from wavespeed_api.client import WaveSpeedClient, WaveSpeedInterrupted


@pytest.fixture
def polling(monkeypatch):
    """A client on a fake clock that never leaves the process.

    Sleeping advances the clock instead of waiting, so a loop that fails to
    stop reaches its own timeout in milliseconds and the test says so — rather
    than hanging until someone kills it."""
    now = {"t": 0.0}
    monkeypatch.setattr(client_mod.time, "time", lambda: now["t"])
    monkeypatch.setattr(client_mod.time, "sleep",
                        lambda s: now.__setitem__("t", now["t"] + max(s, 0.01)))
    c = WaveSpeedClient(api_key="x")
    c.polls = 0

    def respond(status):
        def post(endpoint, payload, timeout=30):
            c.polls += 1
            return {"status": status}
        c.post = post
    c.respond = respond
    return c


def test_cancel_stops_the_poll(polling, monkeypatch):
    # ComfyUI's Cancel does not kill a running node — it only sets a flag. A
    # node that never reads it keeps polling until its own timeout.
    cancelled = {"yes": False}
    monkeypatch.setattr(client_mod, "_resolve_interrupt_checker",
                        lambda: (lambda: cancelled["yes"]))
    polling.respond("processing")

    original = polling.post
    def post_then_cancel(endpoint, payload, timeout=30):
        result = original(endpoint, payload, timeout)
        cancelled["yes"] = True          # user hits Cancel after the first poll
        return result
    polling.post = post_then_cancel

    with pytest.raises(WaveSpeedInterrupted):
        polling.wait_for_task("task-1", polling_interval=1, timeout=300)
    assert polling.polls <= 2, f"kept polling after Cancel ({polling.polls} polls)"


def test_cancel_before_the_first_poll_asks_the_api_nothing(polling, monkeypatch):
    # Cancelling a queued job before its first status check should cost no
    # request at all. Only the check at the top of the loop can do that — the
    # one inside the wait runs after a poll has already gone out.
    monkeypatch.setattr(client_mod, "_resolve_interrupt_checker",
                        lambda: (lambda: True))
    polling.respond("processing")

    with pytest.raises(WaveSpeedInterrupted):
        polling.wait_for_task("task-1", polling_interval=1, timeout=300)
    assert polling.polls == 0, f"polled a cancelled task ({polling.polls} times)"


def test_the_retry_handler_does_not_swallow_an_interrupt(polling, monkeypatch):
    # The handler exists to ride out transient status-check errors and catches
    # everything. An interrupt raised from the request itself — while the flag
    # reads false, as it does once ComfyUI has cleared it — is indistinguishable
    # from a blip unless the re-raise sits above the catch-all.
    monkeypatch.setattr(client_mod, "_resolve_interrupt_checker",
                        lambda: (lambda: False))

    def post_that_interrupts(endpoint, payload, timeout=30):
        polling.polls += 1
        raise WaveSpeedInterrupted("cancelled mid-request")
    polling.post = post_that_interrupts

    with pytest.raises(WaveSpeedInterrupted):
        polling.wait_for_task("task-1", polling_interval=1, timeout=300)
    assert polling.polls == 1, f"retried after an interrupt ({polling.polls} polls)"


def test_a_failed_task_reports_instead_of_polling_on(polling, monkeypatch):
    # A failed job raised inside the try was caught by the retry handler, so it
    # polled for the full timeout and then reported a timeout — hiding the real
    # error the API returned.
    monkeypatch.setattr(client_mod, "_resolve_interrupt_checker",
                        lambda: (lambda: False))

    def post_failed(endpoint, payload, timeout=30):
        polling.polls += 1
        return {"status": "failed", "error": "content policy"}
    polling.post = post_failed

    with pytest.raises(Exception) as err:
        polling.wait_for_task("task-1", polling_interval=1, timeout=300)
    assert "content policy" in str(err.value)
    assert polling.polls == 1, f"retried a failed task ({polling.polls} polls)"


def test_a_cancel_survives_the_caller_nodes(monkeypatch):
    """Around forty nodes wrap the wait in `except Exception as e: raise
    Exception(...)`. A cancel only reaches ComfyUI as a cancel because its
    interrupt derives from BaseException, which that clause does not catch.

    Nothing in this package enforces that — it is ComfyUI's choice, and if it
    ever became an Exception every one of those nodes would quietly turn a
    cancel into a red error. This is the test that would notice."""
    import importlib
    import sys
    import types

    class InterruptProcessingException(BaseException):
        pass

    mm = types.ModuleType("comfy.model_management")
    mm.InterruptProcessingException = InterruptProcessingException
    mm.processing_interrupted = lambda: True
    comfy = types.ModuleType("comfy")
    comfy.__path__ = []
    comfy.model_management = mm
    monkeypatch.setitem(sys.modules, "comfy", comfy)
    monkeypatch.setitem(sys.modules, "comfy.model_management", mm)

    fresh = importlib.reload(importlib.import_module("wavespeed_api.client"))
    try:
        assert issubclass(fresh.WaveSpeedInterrupted, BaseException)
        assert not issubclass(fresh.WaveSpeedInterrupted, Exception), (
            "a caller's `except Exception` would swallow the cancel")

        raised = None
        try:
            try:
                raise fresh.WaveSpeedInterrupted("cancelled")
            except Exception as e:                      # the caller-node shape
                raised = Exception(f"Async task failed: {e}")
        except fresh.WaveSpeedInterrupted:
            pass
        assert raised is None, "a caller node re-wrapped the cancel"
    finally:
        # Leave the module as the rest of the suite expects to find it.
        monkeypatch.undo()
        importlib.reload(importlib.import_module("wavespeed_api.client"))


def test_the_resolver_finds_ComfyUI_own_flag(monkeypatch):
    """Every other test replaces the resolver, which leaves the one line that
    reaches ComfyUI untested — and its `except Exception` would swallow a
    typo'd import, disabling cancel in production with the suite still green."""
    import sys
    import types

    flag = lambda: True
    mm = types.ModuleType("comfy.model_management")
    mm.processing_interrupted = flag
    mm.InterruptProcessingException = type("InterruptProcessingException",
                                           (BaseException,), {})
    comfy = types.ModuleType("comfy")
    comfy.__path__ = []
    comfy.model_management = mm
    monkeypatch.setitem(sys.modules, "comfy", comfy)
    monkeypatch.setitem(sys.modules, "comfy.model_management", mm)

    assert client_mod._resolve_interrupt_checker() is flag, (
        "the resolver did not reach ComfyUI's flag")
    monkeypatch.undo()
    assert client_mod._resolve_interrupt_checker()() is False, (
        "outside ComfyUI the resolver must report 'not cancelled'")

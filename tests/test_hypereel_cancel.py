# ABOUTME: Tests the node-layer cancel bridge — reads ComfyUI's interrupt flag and
# ABOUTME: turns a pure loop's InterruptedError into ComfyUI's own cancel exception.
import sys
import types

import pytest

from _hypereel_cancel import as_comfy_cancel, cancelled


@pytest.fixture()
def no_comfy(monkeypatch):
    # The pure test env has no `comfy`; make sure a stray stub from another test
    # can't leak in and mask the outside-ComfyUI behaviour.
    monkeypatch.delitem(sys.modules, "comfy", raising=False)
    monkeypatch.delitem(sys.modules, "comfy.model_management", raising=False)


@pytest.fixture()
def fake_comfy(monkeypatch):
    class InterruptProcessingException(BaseException):
        pass

    mm = types.ModuleType("comfy.model_management")
    mm.processing_interrupted = lambda: True
    mm.InterruptProcessingException = InterruptProcessingException
    comfy = types.ModuleType("comfy")
    comfy.model_management = mm
    monkeypatch.setitem(sys.modules, "comfy", comfy)
    monkeypatch.setitem(sys.modules, "comfy.model_management", mm)
    return InterruptProcessingException


def test_cancelled_is_false_outside_comfyui(no_comfy):
    assert cancelled() is False


def test_as_comfy_cancel_reraises_original_outside_comfyui(no_comfy):
    err = InterruptedError("compose cancelled")
    with pytest.raises(InterruptedError):
        as_comfy_cancel(err)


def test_cancelled_reads_comfy_interrupt_flag(fake_comfy):
    assert cancelled() is True


def test_as_comfy_cancel_raises_comfy_interrupt(fake_comfy):
    with pytest.raises(fake_comfy):  # ComfyUI reads this as a cancel, not a red error
        as_comfy_cancel(InterruptedError("compose cancelled"))

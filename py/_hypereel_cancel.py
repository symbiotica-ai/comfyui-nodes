# ABOUTME: Node-layer cancel bridge — reads ComfyUI's interrupt flag and turns a
# ABOUTME: pure ffmpeg loop's InterruptedError into ComfyUI's own cancel exception.


def cancelled():
    """True when the user pressed Cancel; False outside ComfyUI. The pure ffmpeg
    loops poll this so a long encode stops promptly instead of running to its own
    timeout — pressing Cancel only sets a flag; a node must notice it."""
    try:
        from comfy import model_management
        return model_management.processing_interrupted()
    except Exception:
        return False


def as_comfy_cancel(exc):
    """Re-raise a pure loop's InterruptedError as ComfyUI's interrupt type, which
    the canvas reads as a cancel rather than a red failure. Outside ComfyUI (no
    model_management) the original exception propagates."""
    try:
        from comfy import model_management
    except ImportError:
        raise exc
    raise model_management.InterruptProcessingException()

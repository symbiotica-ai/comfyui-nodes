# ABOUTME: Shared Whisper model list for transcription nodes.
# ABOUTME: Single source of truth for the model_size dropdown.

ALL_MODELS = ["tiny", "base", "small", "medium", "large-v3"]


def resolve_model(model_name):
    """Resolve model name for faster-whisper. Pass-through for standard sizes."""
    return model_name

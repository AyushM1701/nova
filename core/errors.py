"""Error messages a person can act on."""


def friendly(e):
    """An error message a person can act on."""
    if type(e).__module__.startswith("sounddevice") or "PortAudio" in repr(e):
        return ("Nova can't use the microphone. Check that one is plugged in and that Nova is allowed to use it "
                "in your privacy settings.")
    return f"{type(e).__name__}: {e}"

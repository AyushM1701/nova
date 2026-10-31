"""One lock for PortAudio. Opening, closing or starting a stream from two threads at once is not safe (it corrupts
memory and ends Nova), and Nova does exactly that by design: the reply's voice, the barge-in listener, the wake word
and the computer-audio capture all start within the same moments. sounddevice and pyaudiowpatch share the library."""
import contextlib
import threading

LOCK = threading.RLock()


@contextlib.contextmanager
def stream(kind, driver=None, **kwargs):
    """A sounddevice "input" or "output" stream, opened and closed under LOCK; the caller uses it in between.
    `driver`: the sounddevice module to open it with (a caller's own reference, which tests replace)."""
    sd = driver
    if sd is None:
        import sounddevice as sd
    stack = contextlib.ExitStack()
    with LOCK:
        opened = stack.enter_context(sd.InputStream(**kwargs) if kind == "input" else sd.OutputStream(**kwargs))
    try:
        yield opened
    finally:
        with LOCK:
            stack.close()

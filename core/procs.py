"""Starting and stopping programs for good. subprocess.run(timeout=...) on Windows kills only the program it started,
and a child that inherited its output pipe keeps `communicate()` waiting forever; and a program Nova started keeps
running (and burning the user's AI quota) when Nova itself is killed or crashes."""
import ctypes
import os
import signal
import subprocess
from ctypes import wintypes as w

from core.config import NO_WINDOW

_job = None


def _job_handle():
    """One Windows job object for everything Nova starts: when Nova ends, however it ends, Windows ends them too."""
    global _job
    if _job is None:
        class Basic(ctypes.Structure):
            _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                        ("LimitFlags", w.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                        ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", w.DWORD),
                        ("Affinity", ctypes.c_size_t), ("PriorityClass", w.DWORD), ("SchedulingClass", w.DWORD)]

        class Counters(ctypes.Structure):
            _fields_ = [(name, ctypes.c_uint64) for name in ("a", "b", "c", "d", "e", "f")]

        class Extended(ctypes.Structure):
            _fields_ = [("Basic", Basic), ("Io", Counters), ("ProcessMemoryLimit", ctypes.c_size_t),
                        ("JobMemoryLimit", ctypes.c_size_t), ("PeakProcessMemoryUsed", ctypes.c_size_t),
                        ("PeakJobMemoryUsed", ctypes.c_size_t)]

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateJobObjectW.restype = w.HANDLE
        kernel32.SetInformationJobObject.argtypes = [w.HANDLE, ctypes.c_int, ctypes.c_void_p, w.DWORD]
        handle = kernel32.CreateJobObjectW(None, None)
        info = Extended()
        info.Basic.LimitFlags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not handle or not kernel32.SetInformationJobObject(handle, 9, ctypes.byref(info), ctypes.sizeof(info)):
            raise OSError("no job object")
        _job = handle
    return _job


def kill_on_close(proc):
    """Windows: `proc` and what it starts end when Nova ends. Elsewhere (and when Windows refuses) it does nothing."""
    if os.name != "nt":
        return
    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.AssignProcessToJobObject.argtypes = [w.HANDLE, w.HANDLE]
        kernel32.AssignProcessToJobObject(_job_handle(), int(proc._handle))
    except (OSError, AttributeError, ValueError):
        pass


def kill_tree(proc):
    """End `proc` and everything it started."""
    if os.name == "nt":
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True, creationflags=NO_WINDOW)
    else:
        try:
            os.killpg(proc.pid, signal.SIGKILL)  # the caller started it with start_new_session
        except (ProcessLookupError, PermissionError):
            proc.kill()


def run_bounded(args, timeout, input=None, **kwargs):
    """subprocess.run(capture_output=True) that really stops at `timeout`: the whole tree is killed, then
    subprocess.TimeoutExpired is raised. Pass text=True and so on as for subprocess.run."""
    proc = subprocess.Popen(args, stdin=subprocess.PIPE if input is not None else None, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, **kwargs)
    kill_on_close(proc)
    try:
        out, err = proc.communicate(input, timeout)
    except subprocess.TimeoutExpired:
        kill_tree(proc)
        try:
            proc.communicate(timeout=5)
        except subprocess.TimeoutExpired:  # something outside the tree still holds the pipes: leave them
            pass
        raise
    return subprocess.CompletedProcess(args, proc.returncode, out, err)

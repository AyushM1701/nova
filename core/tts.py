"""Speak a short reply with the operating system's own offline voice (Windows SAPI, macOS `say`).

Nothing is sent anywhere. Both stop as soon as `stop` is set.
"""
import os
import subprocess
import time

from core.system import IS_MAC, NO_WINDOW

SAPI = ("Add-Type -AssemblyName System.Speech; $s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
        "if ($env:NOVA_VOICE) { try { $s.SelectVoice($env:NOVA_VOICE) } catch {} }; "
        "$s.Speak([Console]::In.ReadToEnd())")


def speak(text, voice, stop):
    if not text.strip():
        return
    if IS_MAC:
        args, env = ["say"] + (["-v", voice] if voice else []), None
    else:  # the voice name goes through the environment, never into the command line
        args, env = ["powershell", "-NoProfile", "-Command", SAPI], dict(os.environ, NOVA_VOICE=voice or "")
    p = subprocess.Popen(args, stdin=subprocess.PIPE, text=True, encoding="utf-8", env=env, creationflags=NO_WINDOW)
    p.stdin.write(text)
    p.stdin.close()
    while p.poll() is None:
        if stop.is_set():
            p.kill()
        time.sleep(0.1)


def voices():
    """Installed voice names, for the README / config."""
    if IS_MAC:
        out = subprocess.run(["say", "-v", "?"], capture_output=True, text=True).stdout
        return [line.split("  ")[0].strip() for line in out.splitlines() if line.strip()]
    cmd = ("Add-Type -AssemblyName System.Speech; (New-Object System.Speech.Synthesis.SpeechSynthesizer)"
           ".GetInstalledVoices() | ForEach-Object { $_.VoiceInfo.Name }")
    out = subprocess.run(["powershell", "-NoProfile", "-Command", cmd], capture_output=True, text=True,
                         creationflags=NO_WINDOW).stdout
    return [v.strip() for v in out.splitlines() if v.strip()]

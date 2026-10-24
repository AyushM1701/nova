"""Dictation cleanup by a model on this computer: any OpenAI-compatible server (Ollama, llama.cpp's llama-server,
LM Studio). Same `clean()` as the brains, so cleanup, translation and Command mode work with no subscription and
nothing leaving the machine. Any failure returns None, and the local rules clean the text instead."""
import json
import re
import urllib.request

THINK_RE = re.compile(r"<think>.*?</think>", re.S)  # reasoning models (Qwen3, DeepSeek R1) think out loud first


class LocalLLM:
    name = "Local AI"

    def __init__(self, url, model):
        self.url, self.model = url.rstrip("/"), model

    def clean(self, system_prompt, text, model, timeout=20):
        body = json.dumps({"model": model or self.model, "temperature": 0, "stream": False,
                           "messages": [{"role": "system", "content": system_prompt},
                                        {"role": "user", "content": text}]}).encode()
        req = urllib.request.Request(f"{self.url}/chat/completions", data=body,
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                out = json.loads(r.read())["choices"][0]["message"]["content"]
        except Exception:  # not running, wrong model, a slow answer or an odd reply: the local rules take over
            return None
        return THINK_RE.sub("", out).strip() or None

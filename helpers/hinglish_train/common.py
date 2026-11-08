"""Where a training run keeps its data: data/hinglish-ship by default (the licensed run that ships with Nova), or
HINGLISH_DIR=hinglish-train for the first, private pilot."""
import os
from pathlib import Path

OUT = Path(__file__).resolve().parents[2] / "data" / os.environ.get("HINGLISH_DIR", "hinglish-ship")

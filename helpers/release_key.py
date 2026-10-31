"""Make the key that signs Nova's releases. Run once, on your own computer:  python helpers/release_key.py

It prints two things:
  - the PUBLIC key: paste it into RELEASE_KEY in core/update.py and commit. From then on every Nova refuses an
    update (and the walkthrough clips) whose SHA256SUMS isn't signed by this key.
  - the PRIVATE key: save it as the GitHub secret NOVA_RELEASE_KEY (Settings, Secrets and variables, Actions), and
    keep a copy in a password manager. .github/workflows/release.yml signs each release with it. Lose it and releases
    can't be signed until a new public key ships in an update signed by the old one; share it and anyone can.
Nothing is written to disk.
"""
import base64
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core import ed25519  # noqa: E402

PKCS8_ED25519 = bytes.fromhex("302e020100300506032b657004220420")  # what OpenSSL expects before a 32-byte seed

if __name__ == "__main__":
    seed = os.urandom(32)
    body = base64.encodebytes(PKCS8_ED25519 + seed).decode("ascii").strip()
    print("PUBLIC key (RELEASE_KEY in core/update.py):\n  " + ed25519.public_key(seed).hex())
    print("\nPRIVATE key (the GitHub secret NOVA_RELEASE_KEY, whole text including the two BEGIN/END lines):")
    print(f"-----BEGIN PRIVATE KEY-----\n{body}\n-----END PRIVATE KEY-----")

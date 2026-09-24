"""Read only explicitly supported server settings from the private environment file."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_env(keys):
    path = ROOT / ".env"
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            key, sep, value = line.partition("=")
            if sep and key.strip() in keys:
                os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))

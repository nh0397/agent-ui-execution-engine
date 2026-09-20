import json
import re
from pathlib import Path
from urllib.parse import urlsplit

from engine.contracts import Profile


class PolicyError(RuntimeError):
    pass


class Policy:
    def __init__(self, profile: Profile):
        self.profile = profile

    def url(self, url: str):
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        if parts.username or parts.password or origin not in self.profile.origins:
            raise PolicyError("Destination origin is not allowed")
        if not any(re.fullmatch(pattern, parts.path or "/") for pattern in self.profile.routes):
            raise PolicyError("Destination route is not allowed")

    def action(self, action):
        if action.kind not in self.profile.allowed_actions:
            raise PolicyError("Action type is not allowed")


class Evidence:
    def __init__(self, directory: Path, secrets: list[str]):
        self.directory = directory
        directory.mkdir(parents=True, exist_ok=False)
        self.secrets = sorted((s for s in secrets if s), key=len, reverse=True)

    def clean(self, value):
        if isinstance(value, dict):
            return {k: self.clean(v) for k, v in value.items()}
        if isinstance(value, list):
            return [self.clean(v) for v in value]
        if isinstance(value, str):
            for secret in self.secrets:
                value = value.replace(secret, "[REDACTED]")
            return value
        return value

    def event(self, event: str, **data):
        import datetime
        record = self.clean({"event": event, "time": datetime.datetime.now(datetime.timezone.utc).isoformat(), **data})
        with (self.directory / "events.jsonl").open("a", encoding="utf-8") as file:
            file.write(json.dumps(record) + "\n")

    def save(self, name: str, value):
        (self.directory / name).write_text(json.dumps(self.clean(value), indent=2), encoding="utf-8")

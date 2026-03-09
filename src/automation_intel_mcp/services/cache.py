from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


class FileCache:
    def __init__(self, base_dir: Path, enabled: bool = True, ttl_hours: int = 168) -> None:
        self.base_dir = base_dir
        self.enabled = enabled
        self.ttl_hours = ttl_hours
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def _path_for_key(self, key: dict[str, Any]) -> Path:
        raw = json.dumps(key, sort_keys=True, ensure_ascii=False).encode("utf-8")
        digest = hashlib.sha256(raw).hexdigest()
        return self.base_dir / f"{digest}.json"

    def get(self, key: dict[str, Any]) -> dict[str, Any] | None:
        if not self.enabled:
            return None
        path = self._path_for_key(key)
        if not path.exists():
            return None
        payload = json.loads(path.read_text(encoding="utf-8"))
        created_at = datetime.fromisoformat(payload["created_at"])
        expires_at = created_at + timedelta(hours=self.ttl_hours)
        if expires_at < datetime.now(timezone.utc):
            try:
                path.unlink(missing_ok=True)
            finally:
                return None
        return payload["value"]

    def set(self, key: dict[str, Any], value: dict[str, Any]) -> None:
        if not self.enabled:
            return
        path = self._path_for_key(key)
        payload = {
            "created_at": datetime.now(timezone.utc).isoformat(),
            "value": value,
        }
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

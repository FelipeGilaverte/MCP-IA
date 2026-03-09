from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4


class ResearchRunStore:
    def __init__(self, base_dir: Path, ttl_hours: int = 168) -> None:
        self.base_dir = base_dir / "research_runs"
        self.index_dir = self.base_dir / "by_plan"
        self.ttl_hours = ttl_hours
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.index_dir.mkdir(parents=True, exist_ok=True)

    def generate_run_id(self) -> str:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d")
        return f"research_{stamp}_{uuid4().hex[:6]}"

    def _run_path(self, run_id: str) -> Path:
        return self.base_dir / f"{run_id}.json"

    def _index_path(self, plan_hash: str) -> Path:
        return self.index_dir / f"{plan_hash}.json"

    def store(self, run_id: str, payload: dict[str, Any], *, plan_hash: str | None = None) -> None:
        record = {
            "created_at": datetime.now(timezone.utc).isoformat(),
            "run_id": run_id,
            "payload": payload,
        }
        self._run_path(run_id).write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        if plan_hash:
            self._index_path(plan_hash).write_text(
                json.dumps({"created_at": record["created_at"], "run_id": run_id}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

    def get(self, run_id: str) -> dict[str, Any] | None:
        path = self._run_path(run_id)
        if not path.exists():
            return None
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload.get("payload")

    def get_cached_run_id(self, plan_hash: str) -> str | None:
        path = self._index_path(plan_hash)
        if not path.exists():
            return None
        payload = json.loads(path.read_text(encoding="utf-8"))
        created_at = datetime.fromisoformat(payload["created_at"])
        if created_at + timedelta(hours=self.ttl_hours) < datetime.now(timezone.utc):
            path.unlink(missing_ok=True)
            return None
        return payload.get("run_id")

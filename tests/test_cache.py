from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from automation_intel_mcp.services.cache import FileCache


class FileCacheTests(unittest.TestCase):
    def test_set_and_get_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            cache = FileCache(Path(tmp_dir), enabled=True, ttl_hours=1)
            key = {"endpoint": "x", "id": 1}
            value = {"answer": 42}
            cache.set(key, value)
            self.assertEqual(cache.get(key), value)

    def test_expired_item_returns_none(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            cache = FileCache(Path(tmp_dir), enabled=True, ttl_hours=1)
            key = {"endpoint": "x", "id": 1}
            cache.set(key, {"answer": 42})
            path = cache._path_for_key(key)
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["created_at"] = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
            path.write_text(json.dumps(payload), encoding="utf-8")
            self.assertIsNone(cache.get(key))


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from automation_intel_mcp.models import CostRecord


class BudgetTracker:
    def __init__(self, base_dir: Path, soft_limit_usd: float, hard_limit_usd: float) -> None:
        self.base_dir = base_dir
        self.soft_limit_usd = soft_limit_usd
        self.hard_limit_usd = hard_limit_usd
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.log_path = self.base_dir / "usage_costs.jsonl"

    def _current_month(self) -> str:
        now = datetime.now(timezone.utc)
        return f"{now.year:04d}-{now.month:02d}"

    @staticmethod
    def _row_cost(row: dict[str, Any]) -> float:
        if row.get("billed_cost_usd") is not None:
            return float(row["billed_cost_usd"])
        if row.get("cost_usd") is not None:
            return float(row["cost_usd"])
        if row.get("actual_cost_usd") is not None:
            return float(row["actual_cost_usd"])
        if row.get("estimated_cost_usd") is not None:
            return float(row["estimated_cost_usd"])
        return 0.0

    def iter_month_rows(self) -> list[dict[str, Any]]:
        month = self._current_month()
        rows: list[dict[str, Any]] = []
        if not self.log_path.exists():
            return rows
        for line in self.log_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            if row.get("month") == month:
                rows.append(row)
        return rows

    def iter_all_rows(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        if not self.log_path.exists():
            return rows
        for line in self.log_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            rows.append(row)
        return rows

    def iter_today_rows(self) -> list[dict[str, Any]]:
        today = datetime.now(timezone.utc).date()
        rows: list[dict[str, Any]] = []
        for row in self.iter_all_rows():
            timestamp = row.get("timestamp")
            if not timestamp:
                continue
            try:
                row_date = datetime.fromisoformat(timestamp).date()
            except ValueError:
                continue
            if row_date == today:
                rows.append(row)
        return rows

    def current_month_total(self) -> float:
        total = sum(self._row_cost(row) for row in self.iter_month_rows())
        return round(total, 6)

    def current_day_total(self) -> float:
        total = sum(self._row_cost(row) for row in self.iter_today_rows())
        return round(total, 6)

    def last_run_cost(self) -> float:
        rows = self.iter_all_rows()
        if not rows:
            return 0.0
        run_id = rows[-1].get("metadata", {}).get("run_id")
        if not run_id:
            return round(self._row_cost(rows[-1]), 6)
        total = sum(self._row_cost(row) for row in rows if row.get("metadata", {}).get("run_id") == run_id)
        return round(total, 6)

    def runs_this_month(self) -> int:
        run_ids = {
            row.get("metadata", {}).get("run_id")
            for row in self.iter_month_rows()
            if row.get("metadata", {}).get("run_id")
        }
        return len(run_ids)

    def provider_breakdown(self, *, rows: list[dict[str, Any]] | None = None) -> dict[str, float]:
        breakdown: dict[str, float] = {}
        for row in rows or self.iter_month_rows():
            provider = str(row.get("provider") or "unknown")
            breakdown[provider] = round(breakdown.get(provider, 0.0) + self._row_cost(row), 6)
        return breakdown

    def ensure_within_budget(self) -> None:
        total = self.current_month_total()
        if total >= self.hard_limit_usd:
            raise RuntimeError(f"Hard monthly budget reached: ${total:.2f} used of ${self.hard_limit_usd:.2f}.")

    def status(self) -> dict[str, Any]:
        current = self.current_month_total()
        today_total = self.current_day_total()
        status = "cap_reached" if current >= self.hard_limit_usd else "warning" if current >= self.soft_limit_usd else "ok"
        return {
            "month_total_usd": current,
            "today_total_usd": today_total,
            "last_run_cost_usd": self.last_run_cost(),
            "runs_this_month": self.runs_this_month(),
            "provider_breakdown": self.provider_breakdown(),
            "soft_limit_usd": self.soft_limit_usd,
            "hard_limit_usd": self.hard_limit_usd,
            "soft_limit_reached": current >= self.soft_limit_usd,
            "hard_limit_reached": current >= self.hard_limit_usd,
            "caps": {
                "monthly_cap_usd": self.hard_limit_usd,
                "soft_cap_usd": self.soft_limit_usd,
            },
            "status": status,
        }

    def record(
        self,
        provider: str,
        operation: str,
        *,
        actual_cost_usd: float | None = None,
        estimated_cost_usd: float | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if actual_cost_usd is None and estimated_cost_usd is None:
            raise ValueError("BudgetTracker.record requires actual_cost_usd or estimated_cost_usd.")

        month_total_before = self.current_month_total()
        cost_source = "actual" if actual_cost_usd is not None else "estimated"
        billed_cost_usd = round(float(actual_cost_usd if actual_cost_usd is not None else estimated_cost_usd), 8)
        row = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "month": self._current_month(),
            "provider": provider,
            "operation": operation,
            "actual_cost_usd": round(float(actual_cost_usd), 8) if actual_cost_usd is not None else None,
            "estimated_cost_usd": round(float(estimated_cost_usd), 8) if estimated_cost_usd is not None else None,
            "billed_cost_usd": billed_cost_usd,
            "cost_source": cost_source,
            "metadata": metadata or {},
        }
        with self.log_path.open("a", encoding="utf-8") as fp:
            fp.write(json.dumps(row, ensure_ascii=False) + "\n")

        month_total_after = round(month_total_before + billed_cost_usd, 6)
        today_total_after = round(self.current_day_total(), 6)
        last_run_cost_usd = self.last_run_cost()
        record = CostRecord(
            provider=provider,
            operation=operation,
            billed_cost_usd=billed_cost_usd,
            actual_cost_usd=row["actual_cost_usd"],
            estimated_cost_usd=row["estimated_cost_usd"],
            cost_source=cost_source,
            month_total_usd=month_total_after,
            soft_limit_reached=month_total_after >= self.soft_limit_usd,
            hard_limit_reached=month_total_after >= self.hard_limit_usd,
            metadata=row["metadata"],
        )
        payload = record.model_dump()
        payload["today_total_usd"] = today_total_after
        payload["last_run_cost_usd"] = last_run_cost_usd
        return payload

"""AI 使用次數：每個社團每月的用量，避免儲值的 API 額度被用光。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from .store import ClubStore

COLLECTION = "ai_usage"
DEFAULT_MONTHLY_LIMIT = 200
TAIPEI = timezone(timedelta(hours=8))


def current_month() -> str:
    return datetime.now(TAIPEI).strftime("%Y-%m")


def monthly_usage(store: ClubStore, club_id: str, month: str | None = None) -> int:
    doc = store.get_doc(club_id, COLLECTION, month or current_month())
    return int(doc.get("runs", 0)) if doc else 0


def add_usage(store: ClubStore, club_id: str, month: str | None = None) -> int:
    month = month or current_month()
    runs = monthly_usage(store, club_id, month) + 1
    store.put_doc(club_id, COLLECTION, month, {"month": month, "runs": runs})
    return runs

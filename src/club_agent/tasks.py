"""全社團共用的待辦與進度。

每個任務屬於一個部門，有負責人、期限與狀態。社長總覽、會議議程與各部門顧問都以這份資料掌握進度。
任務存在社團資料的 `tasks` 集合中。
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from .departments import ClubSettings, canonical_department

Status = Literal["待辦", "進行中", "完成"]
STATUSES: tuple[Status, ...] = ("待辦", "進行中", "完成")
COLLECTION = "tasks"


class Task(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    title: str
    department: str
    owner: str = ""
    due: str = Field(default="", description="期限 YYYY-MM-DD，可空白")
    status: Status = "待辦"
    note: str = ""
    source: str = Field(default="手動新增", description="來源，例如：手動新增、會議記錄「10/3 幹部會」")
    project: str = Field(default="", description="所屬活動專案 id；活動籌備清單的任務會填這個")
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))
    updated_at: str = Field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))

    @field_validator("department")
    @classmethod
    def _canonical_department(cls, value: str) -> str:
        return canonical_department(value)  # 已合併部門的舊待辦歸到新部門

    def due_date(self) -> date | None:
        try:
            return date.fromisoformat(self.due) if self.due else None
        except ValueError:
            return None

    def is_overdue(self, today: date | None = None) -> bool:
        d = self.due_date()
        return self.status != "完成" and d is not None and d < (today or date.today())


def save_task(store, club_id: str, task: Task) -> None:
    task.updated_at = datetime.now().isoformat(timespec="seconds")
    store.put_doc(club_id, COLLECTION, task.id, task.model_dump())


def delete_task(store, club_id: str, task_id: str) -> None:
    store.delete_doc(club_id, COLLECTION, task_id)


def list_tasks(store, club_id: str, department: str | None = None) -> list[Task]:
    """未完成在前、依期限排序（沒有期限的排在最後）。"""
    tasks = [Task(**d) for d in store.list_docs(club_id, COLLECTION)]
    if department:
        tasks = [t for t in tasks if t.department == department]
    return sorted(tasks, key=lambda t: (t.status == "完成", t.due or "9999-99-99", t.created_at))


def department_progress(tasks: list[Task], today: date | None = None) -> dict[str, dict[str, int]]:
    """各部門的任務統計：總數、待辦、進行中、完成、逾期。"""
    stats: dict[str, dict[str, int]] = defaultdict(lambda: {"總數": 0, "待辦": 0, "進行中": 0, "完成": 0, "逾期": 0})
    for t in tasks:
        s = stats[t.department]
        s["總數"] += 1
        s[t.status] += 1
        s["逾期"] += int(t.is_overdue(today))
    return dict(stats)


def tasks_digest(tasks: list[Task], settings: ClubSettings, today: date | None = None, include_done: bool = False) -> str:
    """整理成給 AI 參考的文字，依部門分組。"""
    by_dept: dict[str, list[Task]] = defaultdict(list)
    for t in tasks:
        if include_done or t.status != "完成":
            by_dept[t.department].append(t)
    if not by_dept:
        return "（目前沒有未完成的任務）"
    lines = []
    for key in [*settings.enabled_keys(), *[k for k in by_dept if k not in settings.enabled_keys()]]:
        if key not in by_dept:
            continue
        lines.append(f"[{settings.name(key)}]")
        for t in by_dept[key]:
            flags = "（已逾期）" if t.is_overdue(today) else ""
            due = f"，期限 {t.due}" if t.due else ""
            owner = f"，負責 {t.owner}" if t.owner else ""
            lines.append(f"- {t.status}｜{t.title}{owner}{due}{flags}")
    return "\n".join(lines)

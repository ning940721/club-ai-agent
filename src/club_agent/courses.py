"""課程部門：學期課表（AI 規劃）、每堂課的出席與回饋。

- 社課存在 course_sessions 集合；沒有取消的社課會出現在行事曆。
- 社員人數存在 courses 集合（id = settings），用來計算出席率。
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta

from pydantic import BaseModel, Field

from .schemas import CoursePlan

SESSIONS, SETTINGS_COLLECTION, SETTINGS_ID = "course_sessions", "courses", "settings"
STATUSES = ("規劃中", "已確認", "已完成", "取消")
WEEKDAYS = "一二三四五六日"


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


class CourseSession(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    date: str
    start: str = "19:00"
    end: str = "21:00"
    title: str
    instructor: str = ""
    location: str = ""
    objectives: str = Field(default="", description="學習目標")
    materials: str = Field(default="", description="需要準備的材料或器材")
    status: str = "規劃中"
    attendance: int | None = Field(default=None, description="出席人數；None 表示還沒記錄")
    newcomers: int | None = Field(default=None, description="第一次來的人數")
    rating: float | None = Field(default=None, description="平均滿意度 1–5")
    feedback: str = Field(default="", description="回饋重點")
    created_at: str = Field(default_factory=_now)

    def label(self) -> str:
        try:
            weekday = f"（{WEEKDAYS[date.fromisoformat(self.date).weekday()]}）"
        except ValueError:
            weekday = ""
        return f"{self.date}{weekday} {self.start}–{self.end}"


class CourseSettings(BaseModel):
    member_count: int | None = Field(default=None, description="社員人數，用來算出席率")


def save_session(store, club_id: str, s: CourseSession) -> None:
    store.put_doc(club_id, SESSIONS, s.id, s.model_dump())


def delete_session(store, club_id: str, session_id: str) -> None:
    store.delete_doc(club_id, SESSIONS, session_id)


def list_sessions(store, club_id: str) -> list[CourseSession]:
    return sorted((CourseSession(**d) for d in store.list_docs(club_id, SESSIONS)), key=lambda s: (s.date, s.start))


def get_course_settings(store, club_id: str) -> CourseSettings:
    data = store.get_doc(club_id, SETTINGS_COLLECTION, SETTINGS_ID)
    return CourseSettings(**data) if data else CourseSettings()


def save_course_settings(store, club_id: str, settings: CourseSettings) -> None:
    store.put_doc(club_id, SETTINGS_COLLECTION, SETTINGS_ID, settings.model_dump())


def weekly_dates(first: date, count: int, skip: set[str]) -> list[date]:
    """從 first 開始每週一堂，跳過 skip 中的日期（例如期中考週），直到排滿 count 堂。"""
    out, day = [], first
    while len(out) < count:
        if day.isoformat() not in skip:
            out.append(day)
        day += timedelta(days=7)
    return out


def plan_to_sessions(plan: CoursePlan, first: date, start: str, end: str, location: str, skip: set[str]) -> list[CourseSession]:
    dates = weekly_dates(first, len(plan.sessions), skip)
    return [
        CourseSession(
            date=d.isoformat(), start=start, end=end, title=item.title, location=location, instructor=item.instructor,
            objectives="；".join(item.objectives), materials="、".join(item.materials),
        )
        for d, item in zip(dates, plan.sessions)
    ]


def attendance_stats(sessions: list[CourseSession], member_count: int | None) -> dict:
    recorded = [s for s in sessions if s.attendance is not None and s.status != "取消"]
    if not recorded:
        return {"recorded": 0}
    avg = sum(s.attendance for s in recorded) / len(recorded)
    ratings = [s.rating for s in recorded if s.rating is not None]
    return {
        "recorded": len(recorded),
        "avg_attendance": avg,
        "attendance_rate": avg / member_count if member_count else None,
        "newcomers": sum(s.newcomers or 0 for s in recorded),
        "avg_rating": sum(ratings) / len(ratings) if ratings else None,
        "first_half": _avg([s.attendance for s in recorded[: len(recorded) // 2]]),
        "second_half": _avg([s.attendance for s in recorded[len(recorded) // 2:]]),
    }


def _avg(values: list[int]) -> float | None:
    return sum(values) / len(values) if values else None


def _cell(text: object) -> str:
    return str(text).replace("|", "｜").replace("\n", " ")


def schedule_markdown(club_name: str, sessions: list[CourseSession], member_count: int | None = None) -> str:
    active = [s for s in sessions if s.status != "取消"]
    out = [f"# {club_name} 社課課表", "", f"共 {len(active)} 堂", "",
           "| # | 時間 | 主題 | 講師 | 地點 | 學習目標 | 準備材料 |", "|---|---|---|---|---|---|---|"]
    out += [
        f"| {i} | {s.label()} | {_cell(s.title)} | {_cell(s.instructor or '—')} | {_cell(s.location or '—')} "
        f"| {_cell(s.objectives or '—')} | {_cell(s.materials or '—')} |"
        for i, s in enumerate(active, 1)
    ]
    stats = attendance_stats(sessions, member_count)
    if stats["recorded"]:
        out += ["", "## 出席與回饋", "| 日期 | 主題 | 出席 | 新面孔 | 滿意度 | 回饋重點 |", "|---|---|---|---|---|---|"]
        out += [
            f"| {s.date} | {_cell(s.title)} | {s.attendance} | {s.newcomers if s.newcomers is not None else '—'} "
            f"| {s.rating if s.rating is not None else '—'} | {_cell(s.feedback or '—')} |"
            for s in active if s.attendance is not None
        ]
        rate = f"，平均出席率 {stats['attendance_rate']:.0%}" if stats["attendance_rate"] is not None else ""
        out += ["", f"平均出席 {stats['avg_attendance']:.1f} 人{rate}；新面孔共 {stats['newcomers']} 人"
                + (f"；平均滿意度 {stats['avg_rating']:.1f}／5" if stats["avg_rating"] is not None else "")]
    return "\n".join(out) + "\n"

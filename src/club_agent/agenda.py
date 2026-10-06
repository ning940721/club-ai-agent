"""幹部會議時間表：依開始時間與每項議題的分鐘數排出時段，並產生可下載的議程。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from pydantic import BaseModel, Field

from .schemas import AgendaItem

KINDS = ("報告", "討論", "決議")
WEEKDAYS = "一二三四五六日"


@dataclass
class AgendaRow:
    topic: str
    minutes: int
    kind: str = "討論"
    department: str = ""
    goal: str = ""


@dataclass
class ScheduledRow:
    row: AgendaRow
    start: time
    end: time

    @property
    def span(self) -> str:
        return f"{self.start:%H:%M}–{self.end:%H:%M}"


def parse_time(text: str, default: time = time(19, 0)) -> time:
    try:
        return datetime.strptime(text.strip(), "%H:%M").time()
    except (ValueError, AttributeError):
        return default


def rows_from_items(items: list[AgendaItem]) -> list[AgendaRow]:
    return [AgendaRow(topic=a.topic, minutes=a.minutes, kind=a.kind, department=a.department, goal=a.goal) for a in items]


def template_rows(total_minutes: int, department_names: list[str]) -> list[AgendaRow]:
    """不用 AI 的基本議程：依會議時長分配時間（以 5 分鐘為單位）。"""
    follow_up = max(5, round(total_minutes * 0.1 / 5) * 5)
    other = max(5, round(total_minutes * 0.1 / 5) * 5)
    reports = max(5, round(total_minutes * 0.35 / 5) * 5)
    discussion = max(5, total_minutes - follow_up - other - reports)
    return [
        AgendaRow("上次待辦追蹤", follow_up, "報告", "社長", "確認上次會議的待辦是否完成"),
        AgendaRow("各部門進度報告", reports, "報告", "、".join(department_names), "各部門簡短報告進度與需要協助的事"),
        AgendaRow("討論與決議事項", discussion, "討論", "社長", "針對需要決定的事項討論並做成決議"),
        AgendaRow("臨時動議與下次會議時間", other, "決議", "社長", "確認下次開會時間與本次待辦負責人"),
    ]


def schedule(rows: list[AgendaRow], start: time) -> list[ScheduledRow]:
    current = datetime.combine(date.today(), start)
    out = []
    for row in rows:
        end = current + timedelta(minutes=max(0, row.minutes))
        out.append(ScheduledRow(row, current.time(), end.time()))
        current = end
    return out


def total_minutes(rows: list[AgendaRow]) -> int:
    return sum(max(0, r.minutes) for r in rows)


def end_time(start: time, minutes: int) -> time:
    return (datetime.combine(date.today(), start) + timedelta(minutes=minutes)).time()


def meeting_description(meeting_date: date, start: time, minutes: int, location: str = "") -> str:
    """給人看也給 AI 看的會議資訊，例：2026-10-13（二）19:00–20:30，共 90 分鐘，社辦。"""
    text = (
        f"{meeting_date.isoformat()}（{WEEKDAYS[meeting_date.weekday()]}）"
        f"{start:%H:%M}–{end_time(start, minutes):%H:%M}，會議時長 {minutes} 分鐘"
    )
    return f"{text}，地點：{location}" if location.strip() else text


def _cell(text: object) -> str:
    return str(text).replace("|", "｜").replace("\r", " ").replace("\n", " ")


def schedule_markdown(
    meeting_date: date, start: time, planned_minutes: int, rows: list[AgendaRow], location: str = "", heading: str = "##"
) -> str:
    used = total_minutes(rows)
    out = [
        f"{heading} 會議時間表",
        "",
        f"**時間：** {meeting_description(meeting_date, start, planned_minutes, location)}",
        "",
        "| # | 時間 | 議題 | 類型 | 負責 | 分鐘 | 目標 |",
        "|---|---|---|---|---|---|---|",
    ]
    out += [
        f"| {i} | {s.span} | {_cell(s.row.topic)} | {_cell(s.row.kind)} | {_cell(s.row.department)} | {s.row.minutes} | {_cell(s.row.goal)} |"
        for i, s in enumerate(schedule(rows, start), 1)
    ]
    if used != planned_minutes:
        diff = planned_minutes - used
        out += ["", f"> 議程共 {used} 分鐘，" + (f"比預定時長少 {diff} 分鐘。" if diff > 0 else f"超過預定時長 {-diff} 分鐘。")]
    return "\n".join(out) + "\n"


# ---------------------------------------------------------------------------
# 儲存：社長排好的會議議程會存起來，會議記錄整理重點時拿來對照
# ---------------------------------------------------------------------------

COLLECTION = "meeting_plans"


class MeetingPlan(BaseModel):
    date: str = Field(description="會議日期 YYYY-MM-DD，同一天只有一份議程")
    start: str = "19:00"
    minutes: int = 90
    location: str = ""
    agenda: list[AgendaRow] = Field(default_factory=list)

    @property
    def id(self) -> str:
        return self.date

    def label(self) -> str:
        return f"{self.date} {self.start}｜{len(self.agenda)} 個議題"

    def agenda_text(self) -> str:
        """給 AI 對照用的議程清單。"""
        return "\n".join(f"{i}. {r.topic}（{r.kind}，{r.department or '未指定'}）" for i, r in enumerate(self.agenda, 1))


def save_plan(store, club_id: str, plan: MeetingPlan) -> None:
    store.put_doc(club_id, COLLECTION, plan.id, plan.model_dump())


def list_plans(store, club_id: str) -> list[MeetingPlan]:
    """由新到舊。"""
    return sorted((MeetingPlan(**d) for d in store.list_docs(club_id, COLLECTION)), key=lambda p: p.date, reverse=True)


def get_plan(store, club_id: str, plan_id: str) -> MeetingPlan | None:
    data = store.get_doc(club_id, COLLECTION, plan_id) if plan_id else None
    return MeetingPlan(**data) if data else None


def find_plan_for(plans: list[MeetingPlan], meeting_date: str, within_days: int = 3) -> MeetingPlan | None:
    """找出和會議記錄日期最接近的議程（前後幾天內），會議改期也對得上。"""
    try:
        target = date.fromisoformat(meeting_date)
    except ValueError:
        return None
    best = None
    for p in plans:
        gap = abs((date.fromisoformat(p.date) - target).days)
        if gap <= within_days and (best is None or gap < best[0]):
            best = (gap, p)
    return best[1] if best else None


def delete_plan(store, club_id: str, plan_id: str) -> None:
    store.delete_doc(club_id, COLLECTION, plan_id)

"""全社團行事曆：把各處的日期集中在一起。

來源有四種，只有「自行新增的行程」存在 events 集合，其餘每次即時彙整，不會重複儲存：
- 自行新增的行程（活動、課程、截止日…）
- 社長排好的幹部會議（agenda.MeetingPlan）
- 會議記錄整理出的重要日期（MeetingSummary.key_dates）
- 待辦的期限（未完成的任務）

也可以匯出成 .ics，匯入 Google 日曆或手機行事曆。
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta

from pydantic import BaseModel, Field

from .agenda import end_time, list_plans, parse_time
from .departments import ClubSettings
from .meetings import list_meetings
from .partners import ACTIVE_STAGES as PARTNER_ACTIVE
from .partners import list_partners
from .projects import list_projects
from .speakers import ACTIVE_STAGES, list_talks
from .tasks import list_tasks

COLLECTION = "events"
KINDS = ("活動", "會議", "截止", "其他")
SOURCE_MANUAL, SOURCE_PLAN, SOURCE_MEETING, SOURCE_TASK = "自行新增", "會議議程", "會議記錄", "待辦期限"
SOURCE_TALK = "講座"
SOURCE_PROJECT = "活動專案"


class CalendarEvent(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    date: str = Field(description="YYYY-MM-DD")
    title: str
    time: str = Field(default="", description="開始時間 HH:MM，整天的行程留空")
    end: str = Field(default="", description="結束時間 HH:MM，可空白")
    kind: str = "活動"
    department: str = Field(default="", description="部門 key；全社團的行程留空")
    location: str = ""
    note: str = ""
    source: str = SOURCE_MANUAL

    def sort_key(self) -> tuple[str, str]:
        return self.date, self.time or "99:99"

    def when(self) -> str:
        if not self.time:
            return "整天"
        return f"{self.time}–{self.end}" if self.end else self.time


def save_event(store, club_id: str, event: CalendarEvent) -> None:
    store.put_doc(club_id, COLLECTION, event.id, event.model_dump())


def delete_event(store, club_id: str, event_id: str) -> None:
    store.delete_doc(club_id, COLLECTION, event_id)


def _valid_date(text: str) -> bool:
    try:
        date.fromisoformat(text)
        return True
    except (TypeError, ValueError):
        return False


def club_events(store, club_id: str, settings: ClubSettings | None = None) -> list[CalendarEvent]:
    """彙整所有來源的行程，依日期時間排序。"""
    events = [CalendarEvent(**d) for d in store.list_docs(club_id, COLLECTION)]

    plans = list_plans(store, club_id)
    plan_slots = set()
    for p in plans:
        start = parse_time(p.start)
        events.append(
            CalendarEvent(
                id=f"plan-{p.date}", date=p.date, title="幹部會議", time=f"{start:%H:%M}",
                end=f"{end_time(start, p.minutes):%H:%M}", kind="會議", department="president",
                location=p.location, note=f"{len(p.agenda)} 個議題", source=SOURCE_PLAN,
            )
        )
        plan_slots.add(p.date)

    seen = set()
    for doc in list_meetings(store, club_id):
        if not doc.summary:
            continue
        for k in doc.summary.key_dates:
            key = (k.date, k.time, k.event)
            is_planned_meeting = k.date in plan_slots and "會" in k.event  # 已經在議程裡的會議不重複列出
            if key in seen or is_planned_meeting or not _valid_date(k.date):
                continue
            seen.add(key)
            events.append(
                CalendarEvent(
                    id=f"meeting-{doc.id}-{len(seen)}", date=k.date, title=k.event, time=k.time, kind="其他",
                    location=k.location, note=f"出自會議記錄「{doc.title}」", source=SOURCE_MEETING,
                )
            )

    for p in list_projects(store, club_id):
        if _valid_date(p.date):
            events.append(
                CalendarEvent(
                    id=f"project-{p.id}", date=p.date, title=p.name, time=p.start_time, end=p.end_time, kind="活動",
                    department="events", location=p.location, note=f"階段：{p.stage}", source=SOURCE_PROJECT,
                )
            )

    for talk in list_talks(store, club_id):
        if talk.confirmed and talk.stage != "婉拒" and _valid_date(talk.confirmed.date):
            events.append(
                CalendarEvent(
                    id=f"talk-{talk.id}", date=talk.confirmed.date, title=f"講座：{talk.topic}（{talk.speaker}）",
                    time=talk.confirmed.start, end=talk.confirmed.end, kind="活動", department="speakers",
                    location=talk.location, note=talk.format, source=SOURCE_TALK,
                )
            )
        elif talk.stage in ACTIVE_STAGES and _valid_date(talk.follow_up):
            events.append(
                CalendarEvent(
                    id=f"talk-follow-{talk.id}", date=talk.follow_up, title=f"追蹤講者：{talk.speaker}（{talk.stage}）",
                    kind="截止", department="speakers", note=talk.topic, source=SOURCE_TALK,
                )
            )

    for partner in list_partners(store, club_id):
        if partner.stage in PARTNER_ACTIVE and _valid_date(partner.follow_up):
            events.append(
                CalendarEvent(
                    id=f"partner-follow-{partner.id}", date=partner.follow_up, title=f"追蹤合作：{partner.name}（{partner.stage}）",
                    kind="截止", department="pr", note=partner.event, source="合作對象",
                )
            )

    for t in list_tasks(store, club_id):
        if t.due and t.status != "完成" and _valid_date(t.due):
            owner = f"（{t.owner}）" if t.owner else ""
            events.append(
                CalendarEvent(
                    id=f"task-{t.id}", date=t.due, title=f"截止：{t.title}{owner}", kind="截止",
                    department=t.department, note=f"狀態：{t.status}", source=SOURCE_TASK,
                )
            )
    return sorted(events, key=CalendarEvent.sort_key)


def upcoming(events: list[CalendarEvent], today: date, days: int | None = None) -> list[CalendarEvent]:
    """今天以後的行程；days 指定時只取這幾天內的。"""
    last = (today + timedelta(days=days)).isoformat() if days else "9999-12-31"
    return [e for e in events if today.isoformat() <= e.date <= last]


def events_digest(events: list[CalendarEvent], today: date, past_days: int = 14, future_days: int = 90,
                  settings: ClubSettings | None = None) -> str:
    """給 AI 問答用的行事曆摘要：最近兩週到未來三個月。"""
    first = (today - timedelta(days=past_days)).isoformat()
    last = (today + timedelta(days=future_days)).isoformat()
    lines = []
    for e in events:
        if first <= e.date <= last:
            dept = f"［{settings.name(e.department)}］" if settings and e.department else ""
            where = f"，{e.location}" if e.location else ""
            lines.append(f"- {e.date} {e.when()}｜{e.kind}｜{dept}{e.title}{where}（來源：{e.source}）")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 匯出 .ics（Google 日曆：設定 → 匯入與匯出 → 匯入）
# ---------------------------------------------------------------------------


def _ics_text(text: str) -> str:
    return text.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def to_ics(events: list[CalendarEvent], calendar_name: str, settings: ClubSettings | None = None) -> str:
    stamp = datetime.now().strftime("%Y%m%dT%H%M%S")
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//club-agent//calendar//ZH",
        "CALSCALE:GREGORIAN",
        f"X-WR-CALNAME:{_ics_text(calendar_name)}",
        "X-WR-TIMEZONE:Asia/Taipei",
    ]
    for e in events:
        day = date.fromisoformat(e.date)
        lines += ["BEGIN:VEVENT", f"UID:{e.id}@club-agent", f"DTSTAMP:{stamp}"]
        if e.time:
            start = parse_time(e.time)
            finish = parse_time(e.end, default=end_time(start, 60)) if e.end else end_time(start, 60)
            lines.append(f"DTSTART;TZID=Asia/Taipei:{day:%Y%m%d}T{start:%H%M}00")
            lines.append(f"DTEND;TZID=Asia/Taipei:{day:%Y%m%d}T{finish:%H%M}00")
        else:
            lines.append(f"DTSTART;VALUE=DATE:{day:%Y%m%d}")
            lines.append(f"DTEND;VALUE=DATE:{day + timedelta(days=1):%Y%m%d}")
        dept = settings.name(e.department) if settings and e.department else ""
        lines.append(f"SUMMARY:{_ics_text(f'[{dept}] {e.title}' if dept else e.title)}")
        if e.location:
            lines.append(f"LOCATION:{_ics_text(e.location)}")
        description = "｜".join(x for x in (e.kind, e.note, e.source) if x)
        lines += [f"DESCRIPTION:{_ics_text(description)}", "END:VEVENT"]
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"

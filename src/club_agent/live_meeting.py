"""會議進行模式：開會時依議程逐項進行、計時，即時記錄討論重點、決議與待辦；結束後直接產生會議記錄。

- 進行中的會議存在 live_meetings 集合（每次切換議題、按儲存都會寫入），換裝置或重新整理不會遺失。
- 結束時不需要 AI：記錄的決議與待辦直接整理成 MeetingSummary，並依議程對照每個議題的結果，
  存進會議記錄（社長總覽的議程追蹤、行事曆、AI 問答都會用到）。
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, Field

from .agenda import MeetingPlan, parse_time
from .meetings import MeetingDoc
from .schemas import ActionItem, AgendaCheck, KeyDate, MeetingSummary

COLLECTION = "live_meetings"
RUNNING, ENDED, CANCELLED = "進行中", "已結束", "已取消"


def _now() -> datetime:
    return datetime.now().replace(microsecond=0)


class LiveItem(BaseModel):
    topic: str
    kind: str = "討論"
    department: str = Field(default="", description="負責報告或主持的部門（議程上的文字）")
    minutes: int = Field(default=10, description="預定分鐘數")
    goal: str = ""
    notes: str = Field(default="", description="討論重點")
    decisions: list[str] = Field(default_factory=list)
    actions: list[ActionItem] = Field(default_factory=list)
    started_at: str = Field(default="", description="目前這次開始的時間；沒有在進行時為空")
    spent_seconds: int = Field(default=0, description="已經用掉的秒數（可能分好幾次）")
    visited: bool = False

    def result(self) -> str:
        if self.decisions:
            return "已決議"
        if self.notes.strip() or self.actions:
            return "已討論、未決議"
        return "未討論"


class LiveMeeting(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    plan_id: str = Field(default="", description="對應的會前議程（MeetingPlan 的日期）；臨時會議為空")
    title: str
    date: str = Field(default_factory=lambda: date.today().isoformat())
    start: str = ""
    planned_minutes: int = 0
    location: str = ""
    video_link: str = ""
    attendees: str = ""
    status: str = RUNNING
    current: int = 0
    started_at: str = Field(default_factory=lambda: _now().isoformat())
    ended_at: str = ""
    items: list[LiveItem] = Field(default_factory=list)
    meeting_doc_id: str = ""

    # --- 計時 ---

    def item_spent(self, index: int, now: datetime | None = None) -> int:
        item = self.items[index]
        running = 0
        if item.started_at:
            running = int(((now or _now()) - datetime.fromisoformat(item.started_at)).total_seconds())
        return item.spent_seconds + max(0, running)

    def remaining(self, now: datetime | None = None) -> int:
        """目前議題剩下的秒數（超時為負數）。"""
        return self.items[self.current].minutes * 60 - self.item_spent(self.current, now)

    def elapsed(self, now: datetime | None = None) -> int:
        return int(((now or _now()) - datetime.fromisoformat(self.started_at)).total_seconds())

    def switch_to(self, index: int, now: datetime | None = None) -> LiveMeeting:
        """結束目前議題的計時，開始另一個議題。"""
        now = now or _now()
        items = [i.model_copy() for i in self.items]
        cur = items[self.current]
        if cur.started_at:
            cur.spent_seconds = self.item_spent(self.current, now)
            cur.started_at = ""
        nxt = items[index]
        nxt.started_at, nxt.visited = now.isoformat(), True
        return self.model_copy(update={"items": items, "current": index})

    def finish(self, now: datetime | None = None) -> LiveMeeting:
        now = now or _now()
        items = [i.model_copy() for i in self.items]
        cur = items[self.current]
        if cur.started_at:
            cur.spent_seconds = self.item_spent(self.current, now)
            cur.started_at = ""
        return self.model_copy(update={"items": items, "status": ENDED, "ended_at": now.isoformat()})


def start_meeting(plan: MeetingPlan | None, title: str, attendees: str = "", now: datetime | None = None) -> LiveMeeting:
    now = now or _now()
    if plan and plan.agenda:
        items = [LiveItem(topic=r.topic, kind=r.kind, department=r.department, minutes=r.minutes, goal=r.goal) for r in plan.agenda]
    else:
        items = [LiveItem(topic="討論事項", minutes=plan.minutes if plan else 60)]
    items[0].started_at, items[0].visited = now.isoformat(), True
    return LiveMeeting(
        plan_id=plan.id if plan else "", title=title, date=now.date().isoformat(), start=f"{now:%H:%M}",
        planned_minutes=sum(i.minutes for i in items), location=plan.location if plan else "",
        video_link=plan.video_link if plan else "", attendees=attendees.strip(), started_at=now.isoformat(), items=items,
    )


def add_item(m: LiveMeeting, topic: str, minutes: int = 10) -> LiveMeeting:
    """臨時動議：加在最後。"""
    return m.model_copy(update={"items": [*m.items, LiveItem(topic=topic.strip(), minutes=minutes)]})


def save_live(store, club_id: str, m: LiveMeeting) -> None:
    store.put_doc(club_id, COLLECTION, m.id, m.model_dump())


def running_meeting(store, club_id: str) -> LiveMeeting | None:
    """目前進行中的會議（同時最多一場）。"""
    meetings = [LiveMeeting(**d) for d in store.list_docs(club_id, COLLECTION)]
    running = sorted((m for m in meetings if m.status == RUNNING), key=lambda m: m.started_at, reverse=True)
    return running[0] if running else None


def clock(seconds: int) -> str:
    sign = "-" if seconds < 0 else ""
    seconds = abs(seconds)
    return f"{sign}{seconds // 60:02d}:{seconds % 60:02d}"


# ---------------------------------------------------------------------------
# 產生會議記錄
# ---------------------------------------------------------------------------


def to_meeting_doc(m: LiveMeeting, next_meeting: KeyDate | None = None, dept_name=lambda k: k) -> MeetingDoc:
    """把會議過程整理成會議記錄（含重點摘要與議程對照），不需要 AI。"""
    actual = sum(round(i.spent_seconds / 60) for i in m.items)
    decisions = [f"{d}（{i.topic}）" for i in m.items for d in i.decisions]
    actions = [a for i in m.items for a in i.actions]
    pending = [i.topic for i in m.items if i.result() == "已討論、未決議"]
    skipped = [i.topic for i in m.items if i.result() == "未討論"]
    summary_text = f"本次會議共 {len(m.items)} 個議題、實際約 {actual} 分鐘，做成 {len(decisions)} 項決議、{len(actions)} 項待辦。"
    if pending:
        summary_text += f"尚未決議：{'、'.join(pending)}。"
    if skipped:
        summary_text += f"未討論：{'、'.join(skipped)}。"
    summary = MeetingSummary(
        title=m.title,
        summary=summary_text,
        decisions=decisions,
        action_items=actions,
        key_dates=[next_meeting] if next_meeting else [],
        open_questions=[f"{i.topic}：{i.notes.strip()[:80]}" if i.notes.strip() else i.topic for i in m.items if i.result() == "已討論、未決議"],
        agenda_review=[
            AgendaCheck(topic=i.topic, result=i.result(), note="；".join(i.decisions) or i.notes.strip()[:80]) for i in m.items
        ] if m.plan_id else [],
    )
    lines = [f"# {m.title}", "", f"時間：{m.date} {m.start}–{m.ended_at[11:16] if m.ended_at else ''}",
             f"地點：{m.location or '—'}", f"出席：{m.attendees or '—'}", ""]
    for n, i in enumerate(m.items, 1):
        lines += [f"## {n}. {i.topic}（{i.kind}，預定 {i.minutes} 分鐘，實際約 {round(i.spent_seconds / 60)} 分鐘）"]
        if i.notes.strip():
            lines += ["討論重點：", i.notes.strip()]
        lines += [f"決議：{d}" for d in i.decisions]
        lines += [f"待辦：{a.task}（{dept_name(a.department)}｜{a.owner or '未指定'}｜{a.due or '無期限'}）" for a in i.actions]
        if i.result() == "未討論":
            lines.append("（未討論）")
        lines.append("")
    if next_meeting:
        lines.append(f"下次開會：{next_meeting.date} {next_meeting.time} {next_meeting.location}".rstrip())
    return MeetingDoc(title=m.title, date=m.date, source_type="會議記錄", text="\n".join(lines).strip(), summary=summary, plan_id=m.plan_id)


def next_meeting_date(next_day: date | None, next_time: str = "", location: str = "") -> KeyDate | None:
    if not next_day:
        return None
    t = parse_time(next_time) if next_time else None
    return KeyDate(event="下次幹部會", date=next_day.isoformat(), time=f"{t:%H:%M}" if t else "", location=location)

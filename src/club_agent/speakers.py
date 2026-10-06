"""講者部門：講座邀約進度、候選時間與敲定、往來信件紀錄與講座彙整。

每場講座（Talk）存在 talks 集合。已確認的講座與「下次追蹤日」會自動出現在行事曆。
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, Field

COLLECTION = "talks"
STAGES = ("待聯絡", "已邀請", "洽談中", "已確認", "已完成", "婉拒")
ACTIVE_STAGES = ("待聯絡", "已邀請", "洽談中")
FORMATS = ("實體", "線上", "實體＋線上")
WEEKDAYS = "一二三四五六日"


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


class TimeSlot(BaseModel):
    date: str = Field(description="YYYY-MM-DD")
    start: str = Field(default="19:00", description="HH:MM")
    end: str = Field(default="21:00", description="HH:MM")

    def label(self) -> str:
        try:
            weekday = f"（{WEEKDAYS[date.fromisoformat(self.date).weekday()]}）"
        except ValueError:
            weekday = ""
        return f"{self.date}{weekday} {self.start}–{self.end}"


class SavedMessage(BaseModel):
    kind: str
    subject: str
    body: str
    short_text: str = ""
    created_at: str = Field(default_factory=_now)


class Talk(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    created_at: str = Field(default_factory=_now)
    updated_at: str = Field(default_factory=_now)
    speaker: str = Field(description="講者姓名")
    affiliation: str = Field(default="", description="單位與職稱")
    contact: str = Field(default="", description="Email 或其他聯絡方式")
    topic: str = Field(description="講座主題")
    description: str = Field(default="", description="想請講者分享的內容")
    audience: str = Field(default="", description="對象與預計人數")
    format: str = "實體"
    location: str = ""
    fee: int = Field(default=0, ge=0, description="講師費（元）")
    stage: str = "待聯絡"
    owner: str = Field(default="", description="負責聯絡的幹部")
    follow_up: str = Field(default="", description="下次追蹤日 YYYY-MM-DD")
    candidates: list[TimeSlot] = Field(default_factory=list, description="候選時間")
    confirmed: TimeSlot | None = None
    notes: str = ""
    messages: list[SavedMessage] = Field(default_factory=list, description="產生過的信件與通知")

    def title(self) -> str:
        return f"{self.speaker}｜{self.topic}"

    def when(self) -> str:
        return self.confirmed.label() if self.confirmed else "時間未定"

    def facts(self) -> str:
        """給 AI 寫信用的講座資訊；沒有的資料標示未定，避免 AI 自己編。"""
        lines = [
            f"講者：{self.speaker}" + (f"（{self.affiliation}）" if self.affiliation else ""),
            f"主題：{self.topic}",
            f"內容方向：{self.description or '未定'}",
            f"對象與人數：{self.audience or '未定'}",
            f"形式：{self.format}",
            f"地點：{self.location or '未定'}",
            f"講師費：{f'{self.fee:,} 元' if self.fee else '未定'}",
            f"目前進度：{self.stage}",
        ]
        if self.confirmed:
            lines.append(f"已確認時間：{self.confirmed.label()}")
        elif self.candidates:
            lines.append("候選時間：" + "；".join(c.label() for c in self.candidates))
        else:
            lines.append("時間：未定")
        if self.notes:
            lines.append(f"備註：{self.notes}")
        return "\n".join(lines)


def save_talk(store, club_id: str, talk: Talk) -> None:
    store.put_doc(club_id, COLLECTION, talk.id, talk.model_copy(update={"updated_at": _now()}).model_dump())


def delete_talk(store, club_id: str, talk_id: str) -> None:
    store.delete_doc(club_id, COLLECTION, talk_id)


def list_talks(store, club_id: str) -> list[Talk]:
    """已確認的依時間排在前面，其餘依建立時間由新到舊。"""
    talks = [Talk(**d) for d in store.list_docs(club_id, COLLECTION)]
    confirmed = sorted((t for t in talks if t.confirmed), key=lambda t: (t.confirmed.date, t.confirmed.start))
    others = sorted((t for t in talks if not t.confirmed), key=lambda t: t.created_at, reverse=True)
    return confirmed + others


def confirm(talk: Talk, slot: TimeSlot) -> Talk:
    stage = talk.stage if talk.stage == "已完成" else "已確認"
    return talk.model_copy(update={"confirmed": slot, "stage": stage, "follow_up": ""})


def needs_follow_up(talks: list[Talk], today: date) -> list[Talk]:
    return [t for t in talks if t.stage in ACTIVE_STAGES and t.follow_up and t.follow_up <= today.isoformat()]


def _cell(text: object) -> str:
    return str(text).replace("|", "｜").replace("\n", " ")


def talks_markdown(club_name: str, talks: list[Talk], start: date | None = None, end: date | None = None) -> str:
    """講座彙整：已確認的講座時間表，以及還在洽談中的講座與候選時間。"""
    def in_range(t: Talk) -> bool:
        return not start or not end or start.isoformat() <= t.confirmed.date <= end.isoformat()

    confirmed = [t for t in talks if t.confirmed and t.stage != "婉拒" and in_range(t)]
    pending = [t for t in talks if not t.confirmed and t.stage in ACTIVE_STAGES]
    period = f"（{start} ~ {end}）" if start and end else ""
    out = [f"# {club_name} 講座彙整{period}", "", f"## 已確認的講座（{len(confirmed)} 場）"]
    if confirmed:
        out += ["| 時間 | 講者 | 主題 | 形式／地點 | 講師費 | 負責 |", "|---|---|---|---|---|---|"]
        out += [
            f"| {t.confirmed.label()} | {_cell(t.speaker)}{_cell('（' + t.affiliation + '）') if t.affiliation else ''} | {_cell(t.topic)} "
            f"| {t.format}{_cell('／' + t.location) if t.location else ''} | {f'{t.fee:,}' if t.fee else '—'} | {_cell(t.owner or '—')} |"
            for t in confirmed
        ]
        total = sum(t.fee for t in confirmed)
        if total:
            out += ["", f"講師費合計：{total:,} 元"]
    else:
        out.append("目前沒有已確認的講座。")
    out += ["", f"## 洽談中（{len(pending)} 場）"]
    if pending:
        out += ["| 講者 | 主題 | 進度 | 候選時間 | 下次追蹤 | 負責 |", "|---|---|---|---|---|---|"]
        out += [
            f"| {_cell(t.speaker)} | {_cell(t.topic)} | {t.stage} | {_cell('；'.join(c.label() for c in t.candidates) or '—')} "
            f"| {t.follow_up or '—'} | {_cell(t.owner or '—')} |"
            for t in pending
        ]
    else:
        out.append("目前沒有洽談中的講座。")
    return "\n".join(out) + "\n"

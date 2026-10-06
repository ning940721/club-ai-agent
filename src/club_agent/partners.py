"""公關部門：合作對象名單（廠商、校友、其他社團…）與聯絡進度、往來信件、贊助彙整。

合作對象存在 partners 集合；下次追蹤日會出現在行事曆。
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, Field

from .speakers import SavedMessage

COLLECTION = "partners"
TYPES = ("廠商／店家", "校友", "其他社團", "學校單位", "媒體／創作者", "其他")
STAGES = ("待聯絡", "已聯絡", "洽談中", "合作中", "已結束", "婉拒")
ACTIVE_STAGES = ("待聯絡", "已聯絡", "洽談中")
DEAL_STAGES = ("合作中", "已結束")  # 已談成


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


class Partner(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    created_at: str = Field(default_factory=_now)
    updated_at: str = Field(default_factory=_now)
    name: str = Field(description="單位或店家名稱")
    type: str = "廠商／店家"
    contact_person: str = ""
    contact: str = Field(default="", description="Email、電話或 IG")
    stage: str = "待聯絡"
    event: str = Field(default="", description="相關活動名稱")
    ask: str = Field(default="", description="我們請求的內容：贊助金額、物資、折扣、合辦…")
    offer: str = Field(default="", description="我們提供的回饋：貼文露出、攤位、logo…")
    amount: int = Field(default=0, ge=0, description="談成的現金贊助金額（元）")
    in_kind: str = Field(default="", description="談成的物資或折扣")
    owner: str = ""
    follow_up: str = ""
    notes: str = ""
    messages: list[SavedMessage] = Field(default_factory=list)

    def facts(self) -> str:
        lines = [
            f"對象：{self.name}（{self.type}）",
            f"聯絡人：{self.contact_person or '未知'}",
            f"相關活動：{self.event or '未定'}",
            f"我們想請求：{self.ask or '未定'}",
            f"可以提供的回饋：{self.offer or '未定'}",
            f"目前進度：{self.stage}",
        ]
        if self.amount or self.in_kind:
            lines.append(f"已談成：{f'現金 {self.amount:,} 元' if self.amount else ''}{'；' if self.amount and self.in_kind else ''}{self.in_kind}")
        if self.notes:
            lines.append(f"備註：{self.notes}")
        return "\n".join(lines)


def save_partner(store, club_id: str, p: Partner) -> None:
    store.put_doc(club_id, COLLECTION, p.id, p.model_copy(update={"updated_at": _now()}).model_dump())


def delete_partner(store, club_id: str, partner_id: str) -> None:
    store.delete_doc(club_id, COLLECTION, partner_id)


def list_partners(store, club_id: str) -> list[Partner]:
    """洽談中的在前（依追蹤日），其餘依更新時間由新到舊。"""
    partners = [Partner(**d) for d in store.list_docs(club_id, COLLECTION)]
    order = {s: i for i, s in enumerate(("洽談中", "已聯絡", "待聯絡", "合作中", "已結束", "婉拒"))}
    return sorted(partners, key=lambda p: (order.get(p.stage, 9), p.follow_up or "9999", p.updated_at))


def needs_follow_up(partners: list[Partner], today: date) -> list[Partner]:
    return [p for p in partners if p.stage in ACTIVE_STAGES and p.follow_up and p.follow_up <= today.isoformat()]


def _cell(text: object) -> str:
    return str(text).replace("|", "｜").replace("\n", " ")


def sponsorship_markdown(club_name: str, partners: list[Partner]) -> str:
    """贊助與合作彙整：依活動分組列出談成的合作，以及洽談中的對象。"""
    deals = [p for p in partners if p.stage in DEAL_STAGES]
    active = [p for p in partners if p.stage in ACTIVE_STAGES]
    out = [f"# {club_name} 贊助與合作彙整", "", f"## 已談成（{len(deals)} 個，現金合計 {sum(p.amount for p in deals):,} 元）"]
    if deals:
        by_event: dict[str, list[Partner]] = {}
        for p in deals:
            by_event.setdefault(p.event or "（未指定活動）", []).append(p)
        for event, items in by_event.items():
            out += ["", f"### {event}（現金 {sum(p.amount for p in items):,} 元）", "| 對象 | 類型 | 現金 | 物資／折扣 | 我們的回饋 | 狀態 |", "|---|---|---|---|---|---|"]
            out += [
                f"| {_cell(p.name)} | {p.type} | {f'{p.amount:,}' if p.amount else '—'} | {_cell(p.in_kind or '—')} | {_cell(p.offer or '—')} | {p.stage} |"
                for p in items
            ]
    else:
        out.append("目前沒有談成的合作。")
    out += ["", f"## 洽談中（{len(active)} 個）"]
    if active:
        out += ["| 對象 | 類型 | 相關活動 | 進度 | 下次追蹤 | 負責 |", "|---|---|---|---|---|---|"]
        out += [
            f"| {_cell(p.name)} | {p.type} | {_cell(p.event or '—')} | {p.stage} | {p.follow_up or '—'} | {_cell(p.owner or '—')} |"
            for p in active
        ]
    else:
        out.append("目前沒有洽談中的對象。")
    return "\n".join(out) + "\n"

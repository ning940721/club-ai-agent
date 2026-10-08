"""總務：場地申請時程、器材清單與借還紀錄。

- 場地申請存在 venue_bookings；申請期限 = 使用日往前推「提前天數」（預設 14 天，可在頁面調整）。
- 器材存在 equipment，借還紀錄存在 equipment_loans；可借數量 = 數量 − 借出未還。
- 場地使用時間、待申請的申請期限、未歸還器材的歸還期限都會出現在行事曆。
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta

from pydantic import BaseModel, Field

BOOKINGS, EQUIPMENT, LOANS, SETTINGS_COLLECTION, SETTINGS_ID = "venue_bookings", "equipment", "equipment_loans", "venue", "settings"
BOOKING_STATUSES = ("待申請", "已申請", "已核准", "未核准", "取消")
ACTIVE_BOOKING = ("待申請", "已申請", "已核准")
CONDITIONS = ("良好", "需維修", "損壞", "遺失")


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


class VenueSettings(BaseModel):
    lead_days: int = Field(default=14, ge=0, le=180, description="場地要在使用日前幾天申請")


class Booking(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    created_at: str = Field(default_factory=_now)
    venue: str
    purpose: str = ""
    event: str = Field(default="", description="相關活動名稱")
    date: str = Field(description="使用日期 YYYY-MM-DD")
    start: str = ""
    end: str = ""
    apply_by: str = Field(default="", description="申請期限 YYYY-MM-DD")
    status: str = "待申請"
    owner: str = ""
    note: str = ""

    def apply_warning(self, today: date) -> str:
        """待申請且期限在 7 天內或已過時回傳提醒文字。"""
        if self.status != "待申請" or not self.apply_by:
            return ""
        try:
            days = (date.fromisoformat(self.apply_by) - today).days
        except ValueError:
            return ""
        if days < 0:
            return f"已超過申請期限 {-days} 天"
        if days <= 7:
            return f"申請期限剩 {days} 天" if days else "今天是申請期限"
        return ""


class Equipment(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    name: str
    quantity: int = Field(default=1, ge=0)
    location: str = ""
    condition: str = "良好"
    note: str = ""


class Loan(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    equipment_id: str
    equipment_name: str
    borrower: str
    department: str = ""
    quantity: int = Field(default=1, ge=1)
    borrowed: str = Field(default_factory=lambda: date.today().isoformat())
    due: str = ""
    returned: str = Field(default="", description="歸還日期；空白表示還沒還")
    note: str = ""

    @property
    def outstanding(self) -> bool:
        return not self.returned

    def is_overdue(self, today: date) -> bool:
        return self.outstanding and bool(self.due) and self.due < today.isoformat()


def apply_deadline(use_date: date, lead_days: int) -> date:
    return use_date - timedelta(days=lead_days)


def get_venue_settings(store, club_id: str) -> VenueSettings:
    data = store.get_doc(club_id, SETTINGS_COLLECTION, SETTINGS_ID)
    return VenueSettings(**data) if data else VenueSettings()


def save_venue_settings(store, club_id: str, s: VenueSettings) -> None:
    store.put_doc(club_id, SETTINGS_COLLECTION, SETTINGS_ID, s.model_dump())


def save_booking(store, club_id: str, b: Booking) -> None:
    store.put_doc(club_id, BOOKINGS, b.id, b.model_dump())


def delete_booking(store, club_id: str, booking_id: str) -> None:
    store.delete_doc(club_id, BOOKINGS, booking_id)


def list_bookings(store, club_id: str) -> list[Booking]:
    """進行中的在前，依使用日期排序。"""
    items = [Booking(**d) for d in store.list_docs(club_id, BOOKINGS)]
    return sorted(items, key=lambda b: (b.status not in ACTIVE_BOOKING, b.date, b.start))


def save_equipment(store, club_id: str, e: Equipment) -> None:
    store.put_doc(club_id, EQUIPMENT, e.id, e.model_dump())


def delete_equipment(store, club_id: str, equipment_id: str) -> None:
    store.delete_doc(club_id, EQUIPMENT, equipment_id)


def list_equipment(store, club_id: str) -> list[Equipment]:
    return sorted((Equipment(**d) for d in store.list_docs(club_id, EQUIPMENT)), key=lambda e: e.name)


def save_loan(store, club_id: str, loan: Loan) -> None:
    store.put_doc(club_id, LOANS, loan.id, loan.model_dump())


def list_loans(store, club_id: str) -> list[Loan]:
    """未歸還的在前（依歸還期限），其餘依借出日由新到舊。"""
    loans = [Loan(**d) for d in store.list_docs(club_id, LOANS)]
    out = sorted((x for x in loans if x.outstanding), key=lambda x: x.due or "9999")
    return out + sorted((x for x in loans if not x.outstanding), key=lambda x: x.borrowed, reverse=True)


def on_loan(equipment_id: str, loans: list[Loan]) -> int:
    return sum(x.quantity for x in loans if x.equipment_id == equipment_id and x.outstanding)


def available(e: Equipment, loans: list[Loan]) -> int:
    return max(0, e.quantity - on_loan(e.id, loans))


def _cell(text: object) -> str:
    return str(text).replace("|", "｜").replace("\n", " ")


def bookings_markdown(club_name: str, bookings: list[Booking]) -> str:
    active = [b for b in bookings if b.status in ACTIVE_BOOKING]
    out = [f"# {club_name} 場地申請一覽", "", "| 使用日期 | 時間 | 場地 | 用途 | 申請期限 | 狀態 | 負責 |", "|---|---|---|---|---|---|---|"]
    out += [
        f"| {b.date} | {b.start}{'–' + b.end if b.end else ''} | {_cell(b.venue)} | {_cell(b.purpose or b.event or '—')} "
        f"| {b.apply_by or '—'} | {b.status} | {_cell(b.owner or '—')} |"
        for b in active
    ] or ["| — | — | — | 沒有進行中的場地申請 | — | — | — |"]
    return "\n".join(out) + "\n"

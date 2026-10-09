"""人資／社員：社員名單、招生與面試。

- 社員存在 members，報名者存在 applicants；面試時間會出現在行事曆。
- 名單只記錄社團經營需要的資料；不建議記錄學號、身分證字號等敏感個資。
"""

from __future__ import annotations

import csv
import io
import uuid
from datetime import date, datetime

from pydantic import BaseModel, Field

MEMBERS, APPLICANTS = "members", "applicants"
ROLES = ("社員", "幹部")
MEMBER_STATUSES = ("在籍", "休社", "離開")
RESULTS = ("待面試", "已面試", "錄取", "備取", "未錄取", "婉拒")
INTERVIEWED = ("已面試", "錄取", "備取", "未錄取")


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def current_term(today: date | None = None) -> str:
    """學期代號，例如 2026 上（8–1 月）、2026 下（2–7 月）。以學年開始的西元年表示。"""
    today = today or date.today()
    if today.month >= 8:
        return f"{today.year} 上"
    if today.month == 1:
        return f"{today.year - 1} 上"
    return f"{today.year - 1} 下"


class Member(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    name: str
    major: str = Field(default="", description="系級，例如：資管二")
    joined: str = Field(default_factory=current_term, description="入社學期")
    role: str = "社員"
    department: str = Field(default="", description="幹部所屬部門代號")
    contact: str = Field(default="", description="聯絡方式（選填）")
    status: str = "在籍"
    note: str = ""
    created_at: str = Field(default_factory=_now)


class Applicant(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    name: str
    major: str = ""
    source: str = Field(default="", description="從哪裡知道社團：社博、IG、朋友介紹…")
    applied: str = Field(default_factory=lambda: date.today().isoformat())
    role: str = Field(default="社員", description="應徵：社員或某個幹部職位")
    interview_date: str = ""
    interview_time: str = ""
    interviewer: str = ""
    result: str = "待面試"
    note: str = ""


def save_member(store, club_id: str, m: Member) -> None:
    store.put_doc(club_id, MEMBERS, m.id, m.model_dump())


def delete_member(store, club_id: str, member_id: str) -> None:
    store.delete_doc(club_id, MEMBERS, member_id)


def list_members(store, club_id: str) -> list[Member]:
    order = {s: i for i, s in enumerate(MEMBER_STATUSES)}
    return sorted((Member(**d) for d in store.list_docs(club_id, MEMBERS)),
                  key=lambda m: (order.get(m.status, 9), m.role != "幹部", m.joined, m.name))


def save_applicant(store, club_id: str, a: Applicant) -> None:
    store.put_doc(club_id, APPLICANTS, a.id, a.model_dump())


def delete_applicant(store, club_id: str, applicant_id: str) -> None:
    store.delete_doc(club_id, APPLICANTS, applicant_id)


def list_applicants(store, club_id: str) -> list[Applicant]:
    return sorted((Applicant(**d) for d in store.list_docs(club_id, APPLICANTS)),
                  key=lambda a: (a.interview_date or "9999", a.interview_time, a.applied))


def member_stats(members: list[Member], term: str) -> dict[str, int]:
    active = [m for m in members if m.status == "在籍"]
    return {
        "在籍": len(active),
        "幹部": sum(m.role == "幹部" for m in active),
        "本學期新社員": sum(m.joined == term for m in active),
        "休社／離開": sum(m.status != "在籍" for m in members),
    }


def funnel(applicants: list[Applicant]) -> dict[str, int]:
    return {
        "報名": len(applicants),
        "已面試": sum(a.result in INTERVIEWED for a in applicants),
        "錄取": sum(a.result == "錄取" for a in applicants),
    }


def by_source(applicants: list[Applicant]) -> list[tuple[str, int, int]]:
    """(管道, 報名數, 錄取數)，依報名數排序。"""
    stats: dict[str, list[int]] = {}
    for a in applicants:
        s = stats.setdefault(a.source or "未填", [0, 0])
        s[0] += 1
        s[1] += a.result == "錄取"
    return sorted(((k, v[0], v[1]) for k, v in stats.items()), key=lambda x: -x[1])


def admitted_to_members(applicants: list[Applicant], members: list[Member], term: str) -> list[Member]:
    """錄取但還不在社員名單的人（依姓名判斷）。"""
    names = {m.name for m in members}
    return [Member(name=a.name, major=a.major, joined=term, note=f"招生管道：{a.source}" if a.source else "")
            for a in applicants if a.result == "錄取" and a.name not in names]


MEMBER_KEYWORDS = {
    "name": ("姓名", "名字", "name"),
    "major": ("系級", "科系", "系所", "major", "department"),
    "joined": ("入社", "學期", "joined"),
    "role": ("身分", "職位", "role"),
    "contact": ("聯絡", "email", "電話", "line", "ig", "contact"),
    "note": ("備註", "note"),
}


def parse_members_csv(text: str, term: str) -> tuple[list[Member], list[str]]:
    """匯入社員名單：自動對應欄位，只有姓名必填。回傳 (社員, 對應到的欄位說明)。"""
    reader = csv.DictReader(io.StringIO(text.lstrip("﻿")))
    columns = [c.strip() for c in (reader.fieldnames or []) if c]
    mapping: dict[str, str] = {}
    for f, words in MEMBER_KEYWORDS.items():
        col = next((c for c in columns if c not in mapping.values() and any(w in c.lower() for w in words)), None)
        if col:
            mapping[f] = col
    if "name" not in mapping:
        raise ValueError("找不到姓名欄位（欄位名稱可用：姓名、名字、name）")
    members = []
    for row in reader:
        row = {(k or "").strip(): (v or "").strip() for k, v in row.items()}
        name = row.get(mapping["name"], "")
        if not name:
            continue
        role = row.get(mapping.get("role", ""), "")
        members.append(Member(
            name=name, major=row.get(mapping.get("major", ""), ""), joined=row.get(mapping.get("joined", ""), "") or term,
            role="幹部" if "幹部" in role or "部長" in role or "社長" in role else "社員",
            contact=row.get(mapping.get("contact", ""), ""), note=row.get(mapping.get("note", ""), ""),
        ))
    return members, [f"{f} ← {c}" for f, c in mapping.items()]

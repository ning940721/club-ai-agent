"""社團帳號與紀錄的儲存層。

`ClubStore` 是介面；目前提供 `LocalClubStore`，把資料存成本機檔案：

    data/clubs/<club_id>/club.json      社團帳號（密碼只存雜湊）與社團資料
    data/clubs/<club_id>/records.jsonl  各部門的提問、診斷、企劃紀錄

第二階段改用線上資料庫（如 Supabase）時，只要實作同樣的方法即可替換。
注意：Streamlit Community Cloud 重新啟動時會清空本機檔案，正式上線前需換成線上資料庫。
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import uuid
from datetime import datetime
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel, Field

from .schemas import ClubProfile

PBKDF2_ITERATIONS = 200_000
MIN_PASSWORD_LENGTH = 6


class StoreError(ValueError):
    pass


class Record(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))
    department: str = Field(description="部門 key，如 marketing、finance")
    kind: str = Field(description="advice（部門顧問）、diagnosis（數據診斷）、campaign（宣傳企劃）")
    title: str = Field(description="問題或活動名稱")
    summary: str = Field(description="一兩句摘要，顯示在社團動態")
    markdown: str = Field(description="完整內容")


class ClubAccount(BaseModel):
    club_id: str
    account: str
    password_salt: str
    password_hash: str
    created_at: str
    profile: ClubProfile


def normalize_account(account: str) -> str:
    return account.strip().lower()


def club_id_for(account: str) -> str:
    return hashlib.sha256(normalize_account(account).encode("utf-8")).hexdigest()[:16]


def hash_password(password: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt), PBKDF2_ITERATIONS).hex()


class ClubStore(Protocol):
    def create_club(self, account: str, password: str, profile: ClubProfile) -> str: ...
    def authenticate(self, account: str, password: str) -> str | None: ...
    def get_profile(self, club_id: str) -> ClubProfile: ...
    def update_profile(self, club_id: str, profile: ClubProfile) -> None: ...
    def add_record(self, club_id: str, record: Record) -> None: ...
    def list_records(self, club_id: str, department: str | None = None, limit: int | None = None) -> list[Record]: ...


class LocalClubStore:
    def __init__(self, root: str | Path | None = None):
        self.root = Path(root or os.environ.get("CLUB_AGENT_DATA_DIR", "data")) / "clubs"

    def _dir(self, club_id: str) -> Path:
        return self.root / club_id

    def _load(self, club_id: str) -> ClubAccount:
        path = self._dir(club_id) / "club.json"
        if not path.exists():
            raise StoreError("找不到這個社團帳號")
        return ClubAccount.model_validate_json(path.read_text(encoding="utf-8"))

    def _save(self, acct: ClubAccount) -> None:
        d = self._dir(acct.club_id)
        d.mkdir(parents=True, exist_ok=True)
        tmp = d / "club.json.tmp"
        tmp.write_text(acct.model_dump_json(indent=2), encoding="utf-8")
        tmp.replace(d / "club.json")

    def create_club(self, account: str, password: str, profile: ClubProfile) -> str:
        account = normalize_account(account)
        if not account:
            raise StoreError("請輸入帳號")
        if len(password) < MIN_PASSWORD_LENGTH:
            raise StoreError(f"密碼至少需要 {MIN_PASSWORD_LENGTH} 個字元")
        club_id = club_id_for(account)
        if (self._dir(club_id) / "club.json").exists():
            raise StoreError("這個帳號已經有人使用，請換一個")
        salt = secrets.token_hex(16)
        self._save(
            ClubAccount(
                club_id=club_id,
                account=account,
                password_salt=salt,
                password_hash=hash_password(password, salt),
                created_at=datetime.now().isoformat(timespec="seconds"),
                profile=profile,
            )
        )
        return club_id

    def authenticate(self, account: str, password: str) -> str | None:
        try:
            acct = self._load(club_id_for(account))
        except StoreError:
            return None
        ok = hmac.compare_digest(hash_password(password, acct.password_salt), acct.password_hash)
        return acct.club_id if ok else None

    def get_profile(self, club_id: str) -> ClubProfile:
        return self._load(club_id).profile

    def update_profile(self, club_id: str, profile: ClubProfile) -> None:
        acct = self._load(club_id)
        self._save(acct.model_copy(update={"profile": profile}))

    def add_record(self, club_id: str, record: Record) -> None:
        self._load(club_id)  # 確認社團存在
        with open(self._dir(club_id) / "records.jsonl", "a", encoding="utf-8") as f:
            f.write(record.model_dump_json() + "\n")

    def list_records(self, club_id: str, department: str | None = None, limit: int | None = None) -> list[Record]:
        """由新到舊列出紀錄。"""
        path = self._dir(club_id) / "records.jsonl"
        if not path.exists():
            return []
        records = [Record.model_validate_json(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        if department:
            records = [r for r in records if r.department == department]
        records.reverse()
        return records[:limit] if limit else records


def activity_digest(records: list[Record], exclude_department: str | None = None, limit: int = 8) -> str:
    """把其他部門的近期紀錄整理成給 AI 參考的摘要。"""
    from .departments import DEPARTMENTS

    lines = []
    for r in records:
        if r.department == exclude_department:
            continue
        name = DEPARTMENTS[r.department].name if r.department in DEPARTMENTS else r.department
        lines.append(f"- {r.created_at[:10]}｜{name}｜{r.title}：{r.summary}")
        if len(lines) >= limit:
            break
    return "\n".join(lines)

"""社團帳號與紀錄的儲存層。

- `BaseClubStore`：帳號、密碼、社團資料與設定的共用邏輯（密碼只存雜湊）。
- `LocalClubStore`：存成本機檔案，適合在自己電腦上使用：

      data/clubs/<club_id>/club.json          社團帳號與社團資料
      data/clubs/<club_id>/<集合>.json         待辦、會議記錄、報帳…等資料集合
      data/clubs/<club_id>/records.jsonl      各部門分享的成果

- `SupabaseClubStore`（supabase_store.py）：存在線上資料庫，正式上線時使用。
  網站部署在 Streamlit Community Cloud 時，主機重新啟動會清空本機檔案，所以一定要用線上資料庫。

`create_store()` 依設定選擇：有 SUPABASE_URL 與 SUPABASE_KEY 時用線上資料庫，否則用本機檔案。
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
from typing import Callable, Protocol

from pydantic import BaseModel, Field, field_validator

from .departments import ClubSettings, canonical_department
from .schemas import ClubProfile

# 舊版建立、沒有部門設定的社團：沿用當時的七個部門，並加上社長
LEGACY_ENABLED = ("president", "marketing", "pr", "finance", "events", "minutes", "courses", "venue")

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
    summary: str = Field(description="一兩句摘要，顯示在「AI Agent 問答」的分享列表")
    markdown: str = Field(description="完整內容")

    @field_validator("department")
    @classmethod
    def _canonical_department(cls, value: str) -> str:
        return canonical_department(value)  # 已合併部門的舊紀錄歸到新部門


class ClubAccount(BaseModel):
    club_id: str
    account: str
    password_salt: str
    password_hash: str
    created_at: str
    profile: ClubProfile
    settings: ClubSettings = Field(default_factory=lambda: ClubSettings.default(LEGACY_ENABLED))


def normalize_account(account: str) -> str:
    return account.strip().lower()


def _check_password(password: str) -> None:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise StoreError(f"密碼至少需要 {MIN_PASSWORD_LENGTH} 個字元")


def check_collection(collection: str) -> None:
    if not collection.isidentifier():
        raise StoreError(f"不合法的集合名稱：{collection}")


def club_id_for(account: str) -> str:
    return hashlib.sha256(normalize_account(account).encode("utf-8")).hexdigest()[:16]


def hash_password(password: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt), PBKDF2_ITERATIONS).hex()


class ClubStore(Protocol):
    """頁面與各模組使用的介面。"""

    def create_club(self, account: str, password: str, profile: ClubProfile, settings: ClubSettings | None = None) -> str: ...
    def authenticate(self, account: str, password: str) -> str | None: ...
    def change_password(self, club_id: str, old_password: str, new_password: str) -> None: ...
    def get_profile(self, club_id: str) -> ClubProfile: ...
    def update_profile(self, club_id: str, profile: ClubProfile) -> None: ...
    def get_settings(self, club_id: str) -> ClubSettings: ...
    def update_settings(self, club_id: str, settings: ClubSettings) -> None: ...
    def put_doc(self, club_id: str, collection: str, doc_id: str, data: dict) -> None: ...
    def get_doc(self, club_id: str, collection: str, doc_id: str) -> dict | None: ...
    def list_docs(self, club_id: str, collection: str) -> list[dict]: ...
    def delete_doc(self, club_id: str, collection: str, doc_id: str) -> None: ...
    def add_record(self, club_id: str, record: Record) -> None: ...
    def list_records(self, club_id: str, department: str | None = None, limit: int | None = None) -> list[Record]: ...


class BaseClubStore:
    """帳號相關的共用邏輯；子類別只需要實作帳號讀寫、資料集合與紀錄的基本操作。"""

    # --- 子類別實作 ---

    def _read_account(self, club_id: str) -> ClubAccount | None:
        raise NotImplementedError

    def _write_account(self, acct: ClubAccount) -> None:
        raise NotImplementedError

    def _insert_account(self, acct: ClubAccount) -> bool:
        """新增帳號；帳號已存在時回傳 False（不覆蓋）。"""
        raise NotImplementedError

    # --- 共用邏輯 ---

    def _load(self, club_id: str) -> ClubAccount:
        acct = self._read_account(club_id)
        if acct is None:
            raise StoreError("找不到這個社團帳號")
        return acct

    def create_club(self, account: str, password: str, profile: ClubProfile, settings: ClubSettings | None = None) -> str:
        account = normalize_account(account)
        if not account:
            raise StoreError("請輸入帳號")
        _check_password(password)
        club_id = club_id_for(account)
        salt = secrets.token_hex(16)
        acct = ClubAccount(
            club_id=club_id,
            account=account,
            password_salt=salt,
            password_hash=hash_password(password, salt),
            created_at=datetime.now().isoformat(timespec="seconds"),
            profile=profile,
            settings=settings or ClubSettings.default(),
        )
        if not self._insert_account(acct):
            raise StoreError("這個帳號已經有人使用，請換一個")
        return club_id

    def authenticate(self, account: str, password: str) -> str | None:
        acct = self._read_account(club_id_for(account))
        if acct is None:
            return None
        ok = hmac.compare_digest(hash_password(password, acct.password_salt), acct.password_hash)
        return acct.club_id if ok else None

    def change_password(self, club_id: str, old_password: str, new_password: str) -> None:
        acct = self._load(club_id)
        if not hmac.compare_digest(hash_password(old_password, acct.password_salt), acct.password_hash):
            raise StoreError("目前的密碼不正確")
        _check_password(new_password)
        salt = secrets.token_hex(16)
        self._write_account(acct.model_copy(update={"password_salt": salt, "password_hash": hash_password(new_password, salt)}))

    def get_profile(self, club_id: str) -> ClubProfile:
        return self._load(club_id).profile

    def update_profile(self, club_id: str, profile: ClubProfile) -> None:
        self._write_account(self._load(club_id).model_copy(update={"profile": profile}))

    def get_settings(self, club_id: str) -> ClubSettings:
        return self._load(club_id).settings

    def update_settings(self, club_id: str, settings: ClubSettings) -> None:
        if not settings.enabled_keys():
            raise StoreError("至少要啟用一個部門")
        self._write_account(self._load(club_id).model_copy(update={"settings": settings}))


class LocalClubStore(BaseClubStore):
    def __init__(self, root: str | Path | None = None):
        self.root = Path(root or os.environ.get("CLUB_AGENT_DATA_DIR", "data")) / "clubs"

    def _dir(self, club_id: str) -> Path:
        return self.root / club_id

    def _read_account(self, club_id: str) -> ClubAccount | None:
        path = self._dir(club_id) / "club.json"
        return ClubAccount.model_validate_json(path.read_text(encoding="utf-8")) if path.exists() else None

    def _write_account(self, acct: ClubAccount) -> None:
        d = self._dir(acct.club_id)
        d.mkdir(parents=True, exist_ok=True)
        tmp = d / "club.json.tmp"
        tmp.write_text(acct.model_dump_json(indent=2), encoding="utf-8")
        tmp.replace(d / "club.json")

    def _insert_account(self, acct: ClubAccount) -> bool:
        if (self._dir(acct.club_id) / "club.json").exists():
            return False
        self._write_account(acct)
        return True

    # --- 搬資料到線上資料庫時使用 ---

    def club_ids(self) -> list[str]:
        return sorted(p.parent.name for p in self.root.glob("*/club.json")) if self.root.exists() else []

    def raw_account(self, club_id: str) -> dict:
        return json.loads((self._dir(club_id) / "club.json").read_text(encoding="utf-8"))

    def collections(self, club_id: str) -> list[str]:
        return sorted(p.stem for p in self._dir(club_id).glob("*.json") if p.name != "club.json" and p.stem.isidentifier())

    # --- 通用資料集合（待辦、會議記錄等），每個集合存成一個 JSON 檔 ---

    def _collection_path(self, club_id: str, collection: str) -> Path:
        check_collection(collection)
        self._load(club_id)  # 確認社團存在
        return self._dir(club_id) / f"{collection}.json"

    def _read_collection(self, path: Path) -> dict[str, dict]:
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}

    def _write_collection(self, path: Path, docs: dict[str, dict]) -> None:
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(docs, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)

    def put_doc(self, club_id: str, collection: str, doc_id: str, data: dict) -> None:
        path = self._collection_path(club_id, collection)
        docs = self._read_collection(path)
        docs[doc_id] = data
        self._write_collection(path, docs)

    def get_doc(self, club_id: str, collection: str, doc_id: str) -> dict | None:
        return self._read_collection(self._collection_path(club_id, collection)).get(doc_id)

    def list_docs(self, club_id: str, collection: str) -> list[dict]:
        return list(self._read_collection(self._collection_path(club_id, collection)).values())

    def list_doc_items(self, club_id: str, collection: str) -> dict[str, dict]:
        """doc_id → 資料（搬資料時保留原本的 id）。"""
        return self._read_collection(self._collection_path(club_id, collection))

    def delete_doc(self, club_id: str, collection: str, doc_id: str) -> None:
        path = self._collection_path(club_id, collection)
        docs = self._read_collection(path)
        if docs.pop(doc_id, None) is not None:
            self._write_collection(path, docs)

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


def create_store(secret: Callable[[str], str | None], default_dir: str | Path) -> ClubStore:
    """有 SUPABASE_URL 與 SUPABASE_KEY 時用線上資料庫，否則用本機檔案（CLUB_AGENT_DATA_DIR 或 default_dir）。"""
    url, key = secret("SUPABASE_URL"), secret("SUPABASE_KEY")
    if url and key:
        from .supabase_store import SupabaseClubStore

        return SupabaseClubStore.connect(url, key)
    return LocalClubStore(secret("CLUB_AGENT_DATA_DIR") or default_dir)


def activity_digest(
    records: list[Record],
    exclude_department: str | None = None,
    limit: int = 8,
    settings: ClubSettings | None = None,
) -> str:
    """把其他部門的近期紀錄整理成給 AI 參考的摘要。"""
    settings = settings or ClubSettings.default()
    lines = []
    for r in records:
        if r.department == exclude_department:
            continue
        name = settings.name(r.department)
        lines.append(f"- {r.created_at[:10]}｜{name}｜{r.title}：{r.summary}")
        if len(lines) >= limit:
            break
    return "\n".join(lines)

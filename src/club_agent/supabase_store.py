"""線上資料庫（Supabase／Postgres）版的儲存層，正式上線時使用。

資料表（建立方式見 docs/supabase_schema.sql）：
- clubs：社團帳號（club_id、account、data＝ClubAccount JSON，密碼只存雜湊）
- club_docs：資料集合（club_id、collection、doc_id、data）——待辦、會議記錄、報帳…
- club_records：各部門分享的成果（id、club_id、department、created_at、data）

連線使用 service_role 金鑰，只存在網站主機的 Secrets；資料表開啟 RLS 且不設任何規則，
所以外部用公開金鑰無法讀寫。

Streamlit 每次畫面更新都會讀很多資料集合，每次都連線會很慢，所以這裡把讀過的資料暫存在記憶體：
寫入時同時更新暫存，暫存 60 秒後重新讀取（例如搬資料或從其他地方修改資料後）。
網站在 Streamlit Community Cloud 上只有一台主機，所有使用者共用同一份暫存，資料會一致。
"""

from __future__ import annotations

import threading
import time
from typing import Any, Callable

from .store import BaseClubStore, ClubAccount, LocalClubStore, Record, StoreError, check_collection

PAGE = 1000  # Supabase 每次最多回傳 1000 筆


class _Cache:
    def __init__(self, ttl: float, clock: Callable[[], float] = time.monotonic):
        self.ttl = ttl
        self.clock = clock
        self.lock = threading.RLock()
        self.items: dict[tuple, tuple[float, Any]] = {}

    def get(self, key: tuple, load: Callable[[], Any]) -> Any:
        with self.lock:
            hit = self.items.get(key)
            if hit and self.clock() - hit[0] < self.ttl:
                return hit[1]
        value = load()
        with self.lock:
            self.items[key] = (self.clock(), value)
        return value

    def update(self, key: tuple, change: Callable[[Any], None]) -> None:
        """寫入後同步更新暫存（沒有暫存時不用處理，下次讀取會從資料庫載入）。"""
        with self.lock:
            hit = self.items.get(key)
            if hit:
                change(hit[1])

    def drop(self, key: tuple) -> None:
        with self.lock:
            self.items.pop(key, None)


class SupabaseClubStore(BaseClubStore):
    def __init__(self, client, ttl: float = 60.0, clock: Callable[[], float] = time.monotonic):
        self.client = client
        self.cache = _Cache(ttl, clock)

    @classmethod
    def connect(cls, url: str, key: str) -> SupabaseClubStore:
        from supabase import create_client

        return cls(create_client(url, key))

    def _all(self, query_factory: Callable[[], Any]) -> list[dict]:
        """分頁讀取全部資料。"""
        rows: list[dict] = []
        start = 0
        while True:
            page = query_factory().range(start, start + PAGE - 1).execute().data or []
            rows += page
            if len(page) < PAGE:
                return rows
            start += PAGE

    # --- 帳號 ---

    def _read_account(self, club_id: str) -> ClubAccount | None:
        def load():
            rows = self.client.table("clubs").select("data").eq("club_id", club_id).limit(1).execute().data
            return ClubAccount.model_validate(rows[0]["data"]) if rows else None

        return self.cache.get(("club", club_id), load)

    def _write_account(self, acct: ClubAccount) -> None:
        data = acct.model_dump(mode="json")
        self.client.table("clubs").update({"data": data, "account": acct.account}).eq("club_id", acct.club_id).execute()
        with self.cache.lock:
            self.cache.items[("club", acct.club_id)] = (self.cache.clock(), acct)

    def _insert_account(self, acct: ClubAccount) -> bool:
        try:
            self.client.table("clubs").insert(
                {"club_id": acct.club_id, "account": acct.account, "data": acct.model_dump(mode="json")}
            ).execute()
        except Exception as e:  # 帳號重複（主鍵或 unique 衝突，Postgres 錯誤碼 23505）
            if "23505" in str(getattr(e, "code", "")) or "duplicate" in str(e).lower():
                return False
            raise
        self.cache.drop(("club", acct.club_id))
        return True

    def import_account(self, raw: dict, overwrite: bool = False) -> bool:
        """搬資料用：直接寫入帳號（保留原本的密碼雜湊）。帳號已存在且不覆蓋時回傳 False。"""
        acct = ClubAccount.model_validate(raw)
        if self._read_account(acct.club_id) is not None:
            if not overwrite:
                return False
            self._write_account(acct)
            return True
        return self._insert_account(acct)

    # --- 資料集合 ---

    def _collection(self, club_id: str, collection: str) -> dict[str, dict]:
        check_collection(collection)

        def load() -> dict[str, dict]:
            self._load(club_id)  # 確認社團存在
            rows = self._all(lambda: self.client.table("club_docs").select("doc_id,data")
                             .eq("club_id", club_id).eq("collection", collection).order("doc_id"))
            return {r["doc_id"]: r["data"] for r in rows}

        return self.cache.get(("docs", club_id, collection), load)

    def put_doc(self, club_id: str, collection: str, doc_id: str, data: dict) -> None:
        self._collection(club_id, collection)  # 確認社團存在並載入暫存
        self.client.table("club_docs").upsert(
            {"club_id": club_id, "collection": collection, "doc_id": doc_id, "data": data}, on_conflict="club_id,collection,doc_id"
        ).execute()
        self.cache.update(("docs", club_id, collection), lambda docs: docs.__setitem__(doc_id, data))

    def get_doc(self, club_id: str, collection: str, doc_id: str) -> dict | None:
        return self._collection(club_id, collection).get(doc_id)

    def list_docs(self, club_id: str, collection: str) -> list[dict]:
        return list(self._collection(club_id, collection).values())

    def delete_doc(self, club_id: str, collection: str, doc_id: str) -> None:
        self._collection(club_id, collection)
        self.client.table("club_docs").delete().eq("club_id", club_id).eq("collection", collection).eq("doc_id", doc_id).execute()
        self.cache.update(("docs", club_id, collection), lambda docs: docs.pop(doc_id, None))

    # --- 各部門分享的成果 ---

    def _records(self, club_id: str) -> list[Record]:
        def load() -> list[Record]:
            self._load(club_id)
            rows = self._all(lambda: self.client.table("club_records").select("data").eq("club_id", club_id)
                             .order("created_at", desc=True).order("id", desc=True))
            return [Record.model_validate(r["data"]) for r in rows]

        return self.cache.get(("records", club_id), load)

    def add_record(self, club_id: str, record: Record) -> None:
        self._records(club_id)
        self.client.table("club_records").insert({
            "id": record.id, "club_id": club_id, "department": record.department, "created_at": record.created_at,
            "data": record.model_dump(mode="json"),
        }).execute()
        self.cache.update(("records", club_id), lambda records: records.insert(0, record))

    def list_records(self, club_id: str, department: str | None = None, limit: int | None = None) -> list[Record]:
        """由新到舊列出紀錄。"""
        records = [r for r in self._records(club_id) if not department or r.department == department]
        return records[:limit] if limit else list(records)


def migrate_local(local: LocalClubStore, remote: SupabaseClubStore, overwrite: bool = False,
                  log: Callable[[str], None] = print) -> dict[str, int]:
    """把本機資料（data/clubs）搬到線上資料庫。預設不覆蓋線上已經存在的社團帳號。"""
    if not local.club_ids():
        raise StoreError(f"找不到本機資料：{local.root}")
    stats = {"clubs": 0, "skipped": 0, "docs": 0, "records": 0}
    for club_id in local.club_ids():
        raw = local.raw_account(club_id)
        if not remote.import_account(raw, overwrite=overwrite):
            log(f"略過「{raw.get('account')}」：線上已經有這個社團帳號（要覆蓋請加上 --overwrite）")
            stats["skipped"] += 1
            continue
        stats["clubs"] += 1
        for collection in local.collections(club_id):
            for doc_id, data in local.list_doc_items(club_id, collection).items():
                remote.put_doc(club_id, collection, doc_id, data)
                stats["docs"] += 1
        existing = {r.id for r in remote.list_records(club_id)}
        for record in reversed(local.list_records(club_id)):  # 由舊到新寫入，保留順序
            if record.id not in existing:
                remote.add_record(club_id, record)
                stats["records"] += 1
        log(f"已搬移「{raw.get('account')}」")
    return stats

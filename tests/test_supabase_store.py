import pytest

from club_agent.departments import ClubSettings
from club_agent.store import LocalClubStore, Record, StoreError, club_id_for, create_store
from club_agent.supabase_store import SupabaseClubStore, migrate_local

from fake_supabase import FakeClient


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


def make_store(ttl=60.0, clock=None):
    client = FakeClient()
    return SupabaseClubStore(client, ttl=ttl, clock=clock or Clock()), client


def test_accounts(club):
    store, client = make_store()
    cid = store.create_club("NTU-Photo ", "secret123", club)
    assert cid == club_id_for("ntu-photo")
    assert store.authenticate("ntu-photo", "secret123") == cid
    assert store.authenticate("ntu-photo", "wrong") is None and store.authenticate("nobody", "secret123") is None
    assert "secret123" not in str(client.tables["clubs"])  # 只存雜湊
    with pytest.raises(StoreError, match="已經有人使用"):
        store.create_club("ntu-photo", "another123", club)
    store.change_password(cid, "secret123", "newpass123")
    assert store.authenticate("ntu-photo", "newpass123") == cid
    store.update_profile(cid, club.model_copy(update={"name": "新名字"}))
    store.update_settings(cid, ClubSettings.default(["finance", "minutes"]))
    fresh = SupabaseClubStore(client)  # 另一個連線（沒有暫存）也讀得到
    assert fresh.get_profile(cid).name == "新名字" and fresh.get_settings(cid).enabled_keys() == ["finance", "minutes"]
    with pytest.raises(StoreError, match="至少"):
        store.update_settings(cid, ClubSettings.default([]))


def test_docs_records_and_pagination(club):
    store, client = make_store()
    cid = store.create_club("d-club", "secret123", club)
    store.put_doc(cid, "tasks", "a", {"x": 1})
    store.put_doc(cid, "tasks", "b", {"x": 2})
    store.put_doc(cid, "tasks", "a", {"x": 3})
    assert store.get_doc(cid, "tasks", "a") == {"x": 3} and sorted(d["x"] for d in store.list_docs(cid, "tasks")) == [2, 3]
    store.delete_doc(cid, "tasks", "a")
    assert store.get_doc(cid, "tasks", "a") is None and SupabaseClubStore(client).get_doc(cid, "tasks", "a") is None
    with pytest.raises(StoreError):
        store.put_doc(cid, "../evil", "x", {})
    with pytest.raises(StoreError, match="找不到"):
        store.list_docs("nope", "tasks")

    for i in range(2500):  # 超過一頁（1000 筆）
        client.tables["club_docs"].append({"club_id": cid, "collection": "posts", "doc_id": f"{i:05d}", "data": {"i": i}})
    assert len(SupabaseClubStore(client).list_docs(cid, "posts")) == 2500

    store.add_record(cid, Record(department="finance", kind="advice", title="預算", summary="s", markdown="m", created_at="2026-10-01T10:00:00"))
    store.add_record(cid, Record(department="marketing", kind="advice", title="觸及", summary="s", markdown="m", created_at="2026-10-02T10:00:00"))
    for s in (store, SupabaseClubStore(client)):
        assert [r.title for r in s.list_records(cid)] == ["觸及", "預算"]
        assert [r.title for r in s.list_records(cid, department="finance")] == ["預算"] and len(s.list_records(cid, limit=1)) == 1


def test_cache_saves_round_trips_and_expires(club):
    clock = Clock()
    store, client = make_store(ttl=60, clock=clock)
    cid = store.create_club("c-club", "secret123", club)
    store.put_doc(cid, "tasks", "a", {"x": 1})
    before = client.calls
    for _ in range(20):
        store.list_docs(cid, "tasks")
        store.get_settings(cid)
    assert client.calls == before  # 都從暫存讀
    client.tables["club_docs"][0]["data"] = {"x": 99}  # 從別的地方改了資料
    assert store.get_doc(cid, "tasks", "a") == {"x": 1}
    clock.now = 61
    assert store.get_doc(cid, "tasks", "a") == {"x": 99}  # 60 秒後重新讀取


def test_migrate_local_to_supabase(tmp_path, club):
    local = LocalClubStore(tmp_path)
    cid = local.create_club("m-club", "secret123", club)
    local.put_doc(cid, "tasks", "t1", {"title": "寄信"})
    local.put_doc(cid, "meetings", "m1", {"title": "幹部會"})
    local.add_record(cid, Record(department="pr", kind="advice", title="第一", summary="s", markdown="m", created_at="2026-10-01T10:00:00"))
    local.add_record(cid, Record(department="pr", kind="advice", title="第二", summary="s", markdown="m", created_at="2026-10-02T10:00:00"))
    remote, client = make_store()
    logs = []
    stats = migrate_local(local, remote, log=logs.append)
    assert stats == {"clubs": 1, "skipped": 0, "docs": 2, "records": 2}
    fresh = SupabaseClubStore(client)
    assert fresh.authenticate("m-club", "secret123") == cid  # 密碼雜湊原樣搬過去
    assert fresh.get_doc(cid, "tasks", "t1") == {"title": "寄信"}
    assert [r.title for r in fresh.list_records(cid)] == ["第二", "第一"]
    again = migrate_local(local, remote, log=logs.append)
    assert again["skipped"] == 1 and "略過「m-club」" in logs[-1]
    assert migrate_local(local, remote, overwrite=True, log=logs.append)["records"] == 0  # 不重複寫入紀錄
    with pytest.raises(StoreError, match="找不到本機資料"):
        migrate_local(LocalClubStore(tmp_path / "empty"), remote)


def test_create_store_choice(tmp_path, monkeypatch):
    assert isinstance(create_store({}.get, tmp_path), LocalClubStore)
    monkeypatch.setattr(SupabaseClubStore, "connect", classmethod(lambda cls, url, key: cls(FakeClient())))
    store = create_store({"SUPABASE_URL": "https://x.supabase.co", "SUPABASE_KEY": "k"}.get, tmp_path)
    assert isinstance(store, SupabaseClubStore)

import pytest

from club_agent.store import LocalClubStore, Record, StoreError, activity_digest, club_id_for


def test_create_and_authenticate(tmp_path, club):
    store = LocalClubStore(tmp_path)
    club_id = store.create_club("NTU-Photo ", "secret123", club)
    assert club_id == club_id_for("ntu-photo")
    assert store.authenticate("ntu-photo", "secret123") == club_id
    assert store.authenticate("ntu-photo", "wrong") is None
    assert store.authenticate("nobody", "secret123") is None
    raw = (tmp_path / "clubs" / club_id / "club.json").read_text(encoding="utf-8")
    assert "secret123" not in raw  # 只存雜湊


def test_create_validations(tmp_path, club):
    store = LocalClubStore(tmp_path)
    store.create_club("a-club", "secret123", club)
    with pytest.raises(StoreError, match="已經有人使用"):
        store.create_club("A-CLUB", "another123", club)
    with pytest.raises(StoreError, match="至少"):
        store.create_club("b-club", "123", club)
    with pytest.raises(StoreError, match="帳號"):
        store.create_club("  ", "secret123", club)


def test_profile_and_records(tmp_path, club):
    store = LocalClubStore(tmp_path)
    club_id = store.create_club("c-club", "secret123", club)
    store.update_profile(club_id, club.model_copy(update={"name": "新名字"}))
    assert store.get_profile(club_id).name == "新名字"

    store.add_record(club_id, Record(department="finance", kind="advice", title="預算", summary="分配預算", markdown="# a"))
    store.add_record(club_id, Record(department="marketing", kind="advice", title="觸及", summary="多發 Reels", markdown="# b"))
    assert [r.title for r in store.list_records(club_id)] == ["觸及", "預算"]  # 新到舊
    assert [r.title for r in store.list_records(club_id, department="finance")] == ["預算"]
    assert len(store.list_records(club_id, limit=1)) == 1

    digest = activity_digest(store.list_records(club_id), exclude_department="marketing")
    assert "財務" in digest and "預算" in digest and "觸及" not in digest


def test_records_isolated_between_clubs(tmp_path, club):
    store = LocalClubStore(tmp_path)
    a = store.create_club("club-a", "secret123", club)
    b = store.create_club("club-b", "secret123", club)
    store.add_record(a, Record(department="pr", kind="advice", title="A 的問題", summary="s", markdown="m"))
    assert store.list_records(b) == []


def test_settings_default_update_and_legacy(tmp_path, club):
    from club_agent.departments import DEFAULT_ENABLED, ClubSettings
    from club_agent.store import LEGACY_ENABLED

    store = LocalClubStore(tmp_path)
    club_id = store.create_club("s-club", "secret123", club)
    assert store.get_settings(club_id).enabled_keys() == list(DEFAULT_ENABLED)
    store.update_settings(club_id, ClubSettings.default(["finance", "minutes"]))
    assert store.get_settings(club_id).enabled_keys() == ["finance", "minutes"]
    with pytest.raises(StoreError, match="至少"):
        store.update_settings(club_id, ClubSettings.default([]))

    # 舊版帳號（沒有 settings 欄位）沿用舊的部門
    path = tmp_path / "clubs" / club_id / "club.json"
    import json

    raw = json.loads(path.read_text(encoding="utf-8"))
    raw.pop("settings")
    path.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
    assert set(store.get_settings(club_id).enabled_keys()) == set(LEGACY_ENABLED)


def test_change_password(tmp_path, club):
    store = LocalClubStore(tmp_path)
    club_id = store.create_club("p-club", "secret123", club)
    with pytest.raises(StoreError, match="不正確"):
        store.change_password(club_id, "wrong", "newpass123")
    with pytest.raises(StoreError, match="至少"):
        store.change_password(club_id, "secret123", "123")
    store.change_password(club_id, "secret123", "newpass123")
    assert store.authenticate("p-club", "newpass123") == club_id
    assert store.authenticate("p-club", "secret123") is None


def test_doc_collections(tmp_path, club):
    store = LocalClubStore(tmp_path)
    club_id = store.create_club("d-club", "secret123", club)
    store.put_doc(club_id, "tasks", "a", {"x": 1})
    store.put_doc(club_id, "tasks", "b", {"x": 2})
    store.put_doc(club_id, "tasks", "a", {"x": 3})
    assert store.get_doc(club_id, "tasks", "a") == {"x": 3}
    assert sorted(d["x"] for d in store.list_docs(club_id, "tasks")) == [2, 3]
    store.delete_doc(club_id, "tasks", "a")
    assert store.get_doc(club_id, "tasks", "a") is None
    assert store.list_docs(club_id, "meetings") == []
    with pytest.raises(StoreError):
        store.put_doc(club_id, "../evil", "x", {})

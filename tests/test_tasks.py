from datetime import date

from club_agent.departments import ClubSettings
from club_agent.store import LocalClubStore
from club_agent.tasks import Task, delete_task, department_progress, list_tasks, save_task, tasks_digest

TODAY = date(2026, 10, 4)


def test_overdue():
    assert Task(title="a", department="pr", due="2026-10-01").is_overdue(TODAY)
    assert not Task(title="a", department="pr", due="2026-10-01", status="完成").is_overdue(TODAY)
    assert not Task(title="a", department="pr", due="").is_overdue(TODAY)
    assert not Task(title="a", department="pr", due="不是日期").is_overdue(TODAY)


def test_save_list_sort_delete(tmp_path, club):
    store = LocalClubStore(tmp_path)
    cid = store.create_club("t-club", "secret123", club)
    save_task(store, cid, Task(title="無期限", department="pr"))
    save_task(store, cid, Task(title="晚", department="pr", due="2026-12-01"))
    save_task(store, cid, Task(title="早", department="finance", due="2026-10-10"))
    done = Task(title="完成的", department="pr", due="2026-09-01", status="完成")
    save_task(store, cid, done)
    assert [t.title for t in list_tasks(store, cid)] == ["早", "晚", "無期限", "完成的"]
    assert [t.title for t in list_tasks(store, cid, "finance")] == ["早"]
    delete_task(store, cid, done.id)
    assert len(list_tasks(store, cid)) == 3


def test_progress_and_digest():
    tasks = [
        Task(title="寫提案", department="pr", status="進行中", owner="小明", due="2026-10-01"),
        Task(title="寄信", department="pr"),
        Task(title="結帳", department="finance", status="完成"),
    ]
    stats = department_progress(tasks, TODAY)
    assert stats["pr"] == {"總數": 2, "待辦": 1, "進行中": 1, "完成": 0, "逾期": 1}
    digest = tasks_digest(tasks, ClubSettings.default(), TODAY)
    assert "[公關]" in digest and "寫提案，負責 小明，期限 2026-10-01（已逾期）" in digest
    assert "結帳" not in digest
    assert tasks_digest([], ClubSettings.default()) == "（目前沒有未完成的任務）"

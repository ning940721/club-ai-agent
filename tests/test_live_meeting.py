from datetime import date, datetime, timedelta

from club_agent.agenda import AgendaRow, MeetingPlan
from club_agent.live_meeting import add_item, clock, next_meeting_date, start_meeting, to_meeting_doc
from club_agent.schemas import ActionItem

T0 = datetime(2026, 10, 14, 19, 0, 0)


def plan() -> MeetingPlan:
    return MeetingPlan(date="2026-10-14", location="社辦", video_link="https://meet.google.com/abc-defg-hij", agenda=[
        AgendaRow("上次待辦追蹤", 10, "報告", "社長"), AgendaRow("成果展預算", 20, "決議", "財務"), AgendaRow("期中聚餐", 10, "討論")])


def test_timing_and_switching():
    m = start_meeting(plan(), "幹部會議", "社長、小明", now=T0)
    assert m.planned_minutes == 40 and m.video_link.startswith("https://") and m.items[0].visited
    assert m.remaining(T0 + timedelta(minutes=4)) == 6 * 60 and clock(m.remaining(T0 + timedelta(minutes=12))) == "-02:00"
    m = m.switch_to(1, T0 + timedelta(minutes=12))
    assert m.current == 1 and m.items[0].spent_seconds == 12 * 60 and not m.items[0].started_at
    m = m.switch_to(0, T0 + timedelta(minutes=30))  # 回到前一個議題，時間累加
    m = m.switch_to(1, T0 + timedelta(minutes=33))
    assert m.items[0].spent_seconds == 15 * 60 and m.items[1].spent_seconds == 18 * 60
    m = add_item(m, "臨時動議：社服", 5)
    assert m.items[-1].topic == "臨時動議：社服" and m.elapsed(T0 + timedelta(minutes=50)) == 50 * 60
    done = m.finish(T0 + timedelta(minutes=40))
    assert done.status == "已結束" and done.items[1].spent_seconds == 25 * 60


def test_minutes_from_live_meeting():
    m = start_meeting(plan(), "第 6 次幹部會議", "社長、小明", now=T0)
    items = [i.model_copy() for i in m.items]
    items[0] = items[0].model_copy(update={"notes": "贊助信已寄出 3 封"})
    items[1] = items[1].model_copy(update={"decisions": ["成果展預算 3 萬元"], "actions": [
        ActionItem(task="編列成果展預算表", department="finance", owner="小華", due="2026-10-20")]})
    m = m.model_copy(update={"items": items}).switch_to(1, T0 + timedelta(minutes=10)).finish(T0 + timedelta(minutes=35))
    doc = to_meeting_doc(m, next_meeting_date(date(2026, 10, 28), "19:00", "社辦"), {"finance": "財務"}.get)
    s = doc.summary
    assert doc.plan_id == "2026-10-14" and s.decisions == ["成果展預算 3 萬元（成果展預算）"]
    assert [a.task for a in s.action_items] == ["編列成果展預算表"] and s.key_dates[0].date == "2026-10-28"
    assert [(c.topic, c.result) for c in s.agenda_review] == [
        ("上次待辦追蹤", "已討論、未決議"), ("成果展預算", "已決議"), ("期中聚餐", "未討論")]
    assert "未討論：期中聚餐" in s.summary and "做成 1 項決議、1 項待辦" in s.summary
    assert "待辦：編列成果展預算表（財務｜小華｜2026-10-20）" in doc.text and "出席：社長、小明" in doc.text


def test_adhoc_meeting_has_no_agenda_review():
    m = start_meeting(None, "臨時會議", now=T0)
    assert [i.topic for i in m.items] == ["討論事項"] and m.plan_id == ""
    assert to_meeting_doc(m.finish(T0 + timedelta(minutes=5))).summary.agenda_review == []

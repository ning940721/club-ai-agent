from datetime import date

from club_agent.agenda import AgendaRow, MeetingPlan, find_plan_for, get_plan, list_plans, save_plan
from club_agent.agents import MeetingSummarizer
from club_agent.departments import ClubSettings
from club_agent.events import CalendarEvent, club_events, save_event, to_ics, upcoming
from club_agent.meetings import MeetingDoc, merge_summaries, recent_summaries_digest, save_meeting
from club_agent.report import meeting_summary_markdown
from club_agent.schemas import AgendaCheck, KeyDate, MeetingSummary
from club_agent.store import LocalClubStore
from club_agent.tasks import Task, save_task

from conftest import FakeLLM
from test_meetings import make_summary


def _store(tmp_path, club):
    store = LocalClubStore(tmp_path)
    return store, store.create_club("cal-club", "secret123", club)


def test_plans_are_saved_and_matched_by_nearest_date(tmp_path, club):
    store, cid = _store(tmp_path, club)
    save_plan(store, cid, MeetingPlan(date="2026-10-13", agenda=[AgendaRow("成果展預算", 20)]))
    save_plan(store, cid, MeetingPlan(date="2026-10-27", agenda=[AgendaRow("期中聚餐", 10)]))
    plans = list_plans(store, cid)
    assert [p.date for p in plans] == ["2026-10-27", "2026-10-13"]
    assert find_plan_for(plans, "2026-10-14").date == "2026-10-13"  # 改期一天也對得上
    assert find_plan_for(plans, "2026-10-20") is None
    assert get_plan(store, cid, "2026-10-13").agenda[0].topic == "成果展預算"
    assert "1. 成果展預算（討論，未指定）" in plans[1].agenda_text()


def test_summarizer_gets_agenda_and_reports_unresolved_items():
    review = [
        AgendaCheck(topic="成果展預算", result="已決議", note="3 萬元"),
        AgendaCheck(topic="期中聚餐", result="未討論", note=""),
    ]
    llm = FakeLLM({MeetingSummary: [make_summary(agenda_review=review)]})
    summary = MeetingSummarizer(llm).run(ClubSettings.default(), "幹部會", "2026-10-13", "會議記錄", "預算 3 萬", "1. 成果展預算")
    assert "<agenda>\n1. 成果展預算\n</agenda>" in llm.calls[0][1]
    assert [c.topic for c in summary.unresolved_agenda()] == ["期中聚餐"]
    md = meeting_summary_markdown("幹部會", "2026-10-13", summary)
    assert "## 議程對照（1／2 項已決議）" in md and "| 期中聚餐 | 未討論 | — |" in md
    doc = MeetingDoc(title="幹部會", date="2026-10-13", text="", summary=summary)
    assert "議程未完成：期中聚餐（未討論）" in recent_summaries_digest([doc])


def test_no_agenda_means_no_agenda_block():
    llm = FakeLLM({MeetingSummary: [make_summary()]})
    MeetingSummarizer(llm).run(ClubSettings.default(), "幹部會", "2026-10-13", "會議記錄", "內容")
    assert "<agenda>" not in llm.calls[0][1]


def test_split_summaries_keep_best_agenda_result():
    first = make_summary(agenda_review=[AgendaCheck(topic="預算", result="已討論、未決議", note="還在比價"),
                                        AgendaCheck(topic="聚餐", result="未討論", note="")])
    second = make_summary(agenda_review=[AgendaCheck(topic="預算", result="已決議", note="3 萬"),
                                         AgendaCheck(topic="聚餐", result="未討論", note="")])
    merged = merge_summaries([first, second]).agenda_review
    assert [(c.topic, c.result) for c in merged] == [("預算", "已決議"), ("聚餐", "未討論")]


def test_club_events_combine_all_sources(tmp_path, club):
    store, cid = _store(tmp_path, club)
    save_event(store, cid, CalendarEvent(date="2026-10-20", title="期中社課", time="19:00", end="21:00", department="courses"))
    save_plan(store, cid, MeetingPlan(date="2026-10-13", start="18:30", minutes=90, location="社辦", agenda=[AgendaRow("a", 90)]))
    summary = make_summary(key_dates=[
        KeyDate(event="下次幹部會", date="2026-10-13", time="18:30", location="社辦"),  # 已在議程中，不重複
        KeyDate(event="成果展", date="2026-12-20", time="", location="活動中心"),
        KeyDate(event="日期不明", date="待定", time="", location=""),
    ])
    save_meeting(store, cid, MeetingDoc(title="第 5 次幹部會", date="2026-10-03", text="", summary=summary))
    save_task(store, cid, Task(title="寄贊助信", department="pr", owner="小明", due="2026-10-15"))
    save_task(store, cid, Task(title="已完成的事", department="pr", due="2026-10-16", status="完成"))

    events = club_events(store, cid, ClubSettings.default())
    assert [(e.date, e.title) for e in events] == [
        ("2026-10-13", "幹部會議"),
        ("2026-10-15", "截止：寄贊助信（小明）"),
        ("2026-10-20", "期中社課"),
        ("2026-12-20", "成果展"),
    ]
    meeting = events[0]
    assert (meeting.time, meeting.end, meeting.location, meeting.kind) == ("18:30", "20:00", "社辦", "會議")
    assert [e.title for e in upcoming(events, date(2026, 10, 14), days=7)] == ["截止：寄贊助信（小明）", "期中社課"]


def test_ics_export():
    events = [
        CalendarEvent(id="a1", date="2026-10-20", title="期中社課, 第 3 堂", time="19:00", end="21:00", location="社辦"),
        CalendarEvent(id="b2", date="2026-10-25", title="報名截止", department="pr"),
    ]
    ics = to_ics(events, "測試社 行事曆", ClubSettings.default())
    assert ics.startswith("BEGIN:VCALENDAR\r\n") and ics.endswith("END:VCALENDAR\r\n")
    assert "DTSTART;TZID=Asia/Taipei:20261020T190000" in ics and "DTEND;TZID=Asia/Taipei:20261020T210000" in ics
    assert "SUMMARY:期中社課\\, 第 3 堂" in ics
    assert "DTSTART;VALUE=DATE:20261025" in ics and "DTEND;VALUE=DATE:20261026" in ics
    assert "SUMMARY:[公關] 報名截止" in ics


def test_events_digest_window():
    from club_agent.events import events_digest

    events = [CalendarEvent(date="2026-09-01", title="太久以前"), CalendarEvent(date="2026-10-01", title="上週社課", time="19:00"),
              CalendarEvent(date="2026-12-20", title="成果展", location="學活", department="events"),
              CalendarEvent(date="2027-03-01", title="太遠")]
    text = events_digest(events, date(2026, 10, 7), settings=ClubSettings.default())
    assert "太久以前" not in text and "太遠" not in text
    assert "- 2026-10-01 19:00｜活動｜上週社課" in text and "［活動］成果展，學活" in text

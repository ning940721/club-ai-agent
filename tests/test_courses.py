from datetime import date

from club_agent.agents import CoursePlanner
from club_agent.courses import CourseSession, attendance_stats, list_sessions, plan_to_sessions, save_session, schedule_markdown, weekly_dates
from club_agent.departments import ClubSettings
from club_agent.events import club_events
from club_agent.schemas import CoursePlan, CoursePlanItem
from club_agent.store import LocalClubStore

from conftest import FakeLLM


def make_plan(n=3) -> CoursePlan:
    return CoursePlan(sessions=[CoursePlanItem(title=f"第{i}堂", objectives=["會用光圈"], activities=["講解 30 分鐘"],
                                               materials=["相機"], instructor="") for i in range(1, n + 1)], notes=["期中成果分享"])


def test_weekly_dates_skip_and_plan_to_sessions():
    assert weekly_dates(date(2026, 10, 1), 3, {"2026-10-08"}) == [date(2026, 10, 1), date(2026, 10, 15), date(2026, 10, 22)]
    sessions = plan_to_sessions(make_plan(), date(2026, 10, 1), "19:00", "21:00", "社辦", {"2026-10-08"})
    assert [(s.date, s.title, s.location, s.materials) for s in sessions][1] == ("2026-10-15", "第2堂", "社辦", "相機")


def test_attendance_stats_and_markdown(tmp_path, club):
    sessions = [
        CourseSession(date="2026-10-01", title="光圈", attendance=30, newcomers=10, rating=4.5),
        CourseSession(date="2026-10-08", title="快門", attendance=28, rating=4.0),
        CourseSession(date="2026-10-15", title="構圖", attendance=18),
        CourseSession(date="2026-10-22", title="後製", attendance=16),
        CourseSession(date="2026-10-29", title="取消的", status="取消", attendance=0),
        CourseSession(date="2026-11-05", title="還沒上"),
    ]
    s = attendance_stats(sessions, 40)
    assert s["recorded"] == 4 and s["avg_attendance"] == 23 and s["attendance_rate"] == 23 / 40 and s["newcomers"] == 10
    assert s["first_half"] == 29 and s["second_half"] == 17 and s["avg_rating"] == 4.25
    md = schedule_markdown("測試社", sessions, 40)
    assert "共 5 堂" in md and "取消的" not in md and "平均出席率 57%" in md

    store = LocalClubStore(tmp_path)
    cid = store.create_club("course-club", "secret123", club)
    for x in sessions:
        save_session(store, cid, x)
    assert [x.title for x in list_sessions(store, cid)][0] == "光圈"
    titles = [e.title for e in club_events(store, cid, ClubSettings.default())]
    assert "社課：還沒上" in titles and "社課：取消的" not in titles


def test_course_planner_prompt(club):
    llm = FakeLLM({CoursePlan: [make_plan(12)]})
    CoursePlanner(llm).plan(club, "學期末能拍一組作品", "零基礎", 12, 120, "每週四晚上")
    prompt = llm.calls[0][1]
    assert "堂數：12 堂" in prompt and "每堂課長度：120 分鐘" in prompt and "每週四晚上" in prompt

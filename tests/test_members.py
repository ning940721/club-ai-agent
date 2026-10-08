from datetime import date

from club_agent.agents import PeopleAdvisor
from club_agent.departments import ClubSettings
from club_agent.events import club_events
from club_agent.members import (
    Applicant,
    Member,
    admitted_to_members,
    by_source,
    current_term,
    funnel,
    member_stats,
    parse_members_csv,
    save_applicant,
)
from club_agent.report import handover_markdown, interview_kit_markdown
from club_agent.schemas import HandoverManual, HowTo, InterviewKit, InterviewQuestion, RubricItem, TimelineItem
from club_agent.store import LocalClubStore

from conftest import FakeLLM


def test_terms_stats_and_funnel():
    assert current_term(date(2026, 10, 9)) == "2026 上" and current_term(date(2027, 1, 5)) == "2026 上"
    assert current_term(date(2027, 3, 1)) == "2026 下"
    members = [Member(name="a", joined="2026 上"), Member(name="b", role="幹部", joined="2025 上"), Member(name="c", status="離開")]
    assert member_stats(members, "2026 上") == {"在籍": 2, "幹部": 1, "本學期新社員": 1, "休社／離開": 1}
    applicants = [Applicant(name="a", source="社博", result="錄取"), Applicant(name="b", source="社博", result="未錄取"),
                  Applicant(name="c", source="IG"), Applicant(name="x", result="錄取")]
    assert funnel(applicants) == {"報名": 4, "已面試": 3, "錄取": 2}
    assert by_source(applicants)[0] == ("社博", 2, 1)
    new = admitted_to_members(applicants, [Member(name="x")], "2026 上")
    assert [m.name for m in new] == ["a"] and new[0].note == "招生管道：社博"


def test_parse_members_csv():
    text = "姓名,系級,身分,Email\n王小明,資管二,社員,a@x.com\n陳小華,企管三,副社長,\n,,,\n"
    members, mapping = parse_members_csv(text, "2026 上")
    assert [(m.name, m.major, m.role, m.contact, m.joined) for m in members] == [
        ("王小明", "資管二", "社員", "a@x.com", "2026 上"), ("陳小華", "企管三", "幹部", "", "2026 上")]
    assert "name ← 姓名" in mapping


def test_interviews_on_calendar(tmp_path, club):
    store = LocalClubStore(tmp_path)
    cid = store.create_club("hr-club", "secret123", club)
    save_applicant(store, cid, Applicant(name="小明", interview_date="2026-10-15", interview_time="18:30", interviewer="社長"))
    save_applicant(store, cid, Applicant(name="已錄取", interview_date="2026-10-14", result="錄取"))
    titles = [e.title for e in club_events(store, cid, ClubSettings.default())]
    assert "面試：小明（社員）" in titles and not any("已錄取" in t for t in titles)


def test_people_advisor_and_documents(club):
    kit = InterviewKit(questions=[InterviewQuestion(question="為什麼想加入？", purpose="動機", good_signs="具體")],
                       rubric=[RubricItem(criterion="投入度", description="5 分：每週可投入 5 小時")], tips=["不要問私人問題"])
    manual = HandoverManual(overview="行銷部負責社群", responsibilities=["經營 IG"],
                            annual_timeline=[TimelineItem(period="9 月", tasks=["招生宣傳"])],
                            how_tos=[HowTo(task="發 IG 貼文", steps=["寫文案", "請美宣做圖"])], resources=["IG 帳號【待補：私下移交】"],
                            lessons=["宣傳太晚"], open_items=["月報"], first_month=["接手 IG 帳號"])
    llm = FakeLLM({InterviewKit: [kit], HandoverManual: [manual]})
    PeopleAdvisor(llm).interview_kit(club, "行銷部員", "主要經營 IG")
    PeopleAdvisor(llm).handover(club, "行銷", "[待辦與進度]\n- 完成｜招生貼文")
    assert "<role>行銷部員</role>" in llm.calls[0][1] and "[待辦與進度]" in llm.calls[1][1]
    assert "| 1 | 為什麼想加入？ | 動機 | 具體 |" in interview_kit_markdown("測試社", "行銷部員", kit)
    md = handover_markdown("測試社", "行銷", manual)
    assert "| 9 月 | 招生宣傳 |" in md and "### 怎麼做：發 IG 貼文" in md and "- [ ] 接手 IG 帳號" in md

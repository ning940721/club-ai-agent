from datetime import date

import pytest

from club_agent.export import pdf_available
from club_agent.finance import Reimbursement, approve
from club_agent.projects import (
    EventProject,
    StaffMember,
    actual_spending,
    badges_pdf,
    feedback_markdown,
    google_form_text,
    prep_tasks_to_tasks,
    proposal_markdown,
    report_markdown,
    rundown_markdown,
)
from club_agent.schemas import (
    BudgetLine,
    EventProposal,
    EventReport,
    FeedbackForm,
    FeedbackQuestion,
    PrepTask,
    RiskItem,
    RundownItem,
)


def make_proposal() -> EventProposal:
    return EventProposal(
        purpose="展示社員作品", goals=["參觀 150 人"], audience="全校學生，約 150 人", content=["作品展", "底片體驗"],
        rundown=[RundownItem(start="13:00", end="13:30", item="報到", owner="接待組", note="")],
        budget=[BudgetLine(item="海報輸出", category="文宣印刷", amount=1500, note="估算"),
                BudgetLine(item="場地布置", category="活動", amount=2500, note="")],
        staffing=["接待組 3 人"], promotion=["活動前兩週 IG 宣傳"],
        prep_tasks=[PrepTask(task="申請場地", department="venue", days_before=30),
                    PrepTask(task="IG 宣傳貼文", department="marketing", days_before=14),
                    PrepTask(task="不存在的部門工作", department="catering", days_before=3)],
        risks=[RiskItem(risk="下雨", response="改到室內")], kpis=["參觀人數"],
    )


def make_project(**kw) -> EventProject:
    data = dict(name="期末成果展", date="2026-12-20", start_time="13:00", end_time="18:00", location="學活中心", budget=5000,
                expected_people=150, proposal=make_proposal())
    data.update(kw)
    return EventProject(**data)


def test_prep_tasks_dates_and_departments():
    project = make_project()
    tasks = prep_tasks_to_tasks(project, ["president", "marketing", "events"], today=date(2026, 11, 25))
    assert [(t.title, t.department, t.due) for t in tasks] == [
        ("申請場地", "events", "2026-11-25"),  # 期限已過 → 改為今天；部門未啟用 → 活動
        ("IG 宣傳貼文", "marketing", "2026-12-06"),
        ("不存在的部門工作", "events", "2026-12-17"),
    ]
    assert all(t.project == project.id for t in tasks) and tasks[0].source == "活動「期末成果展」"


def test_actual_spending_matches_activity_name():
    requests = [
        approve(Reimbursement(applicant="a", department="events", item="海報", category="文宣印刷", amount=1200,
                              receipt_date="2026-12-01", activity="期末成果展"), "財務"),
        Reimbursement(applicant="a", department="events", item="待審", amount=300, receipt_date="2026-12-01", activity="期末成果展"),
        approve(Reimbursement(applicant="a", department="events", item="別的", amount=999, receipt_date="2026-12-01", activity="迎新"), "財務"),
    ]
    assert actual_spending(make_project(), requests) == (1200, {"文宣印刷": 1200})


def test_documents():
    p = make_project(staff=[StaffMember(name="王小明", role="場控組")], rundown=make_proposal().rundown, budget_lines=make_proposal().budget)
    md = proposal_markdown("測試社", p, {"venue": "總務", "marketing": "行銷"}.get)
    assert "2026-12-20（日） 13:00–18:00" in md and "| **合計** | | **4,000** | |" in md
    assert "| 申請場地 | 總務 | 2026-11-20 |" in md and "| 下雨 | 改到室內 |" in md
    assert "| 王小明 | 場控組 | — | — |" in rundown_markdown("測試社", p)

    form = FeedbackForm(title="回饋", intro="謝謝參加", questions=[
        FeedbackQuestion(question="整體滿意度", type="線性刻度", options=["非常不滿意", "非常滿意"], required=True),
        FeedbackQuestion(question="從哪裡得知", type="複選", options=["IG", "朋友"], required=False),
    ])
    assert "1 = 非常不滿意，5 = 非常滿意" in feedback_markdown(form)
    assert "1. 整體滿意度［線性刻度，必填］" in google_form_text(form) and "   ○ IG" in google_form_text(form)

    report = EventReport(summary="順利", results=["參觀 180 人，超過目標"], highlights=["體驗攤位"], budget_review="略省",
                         feedback_summary="滿意 4.5", improvements=["提早宣傳"], handover=["場地提早兩個月借"])
    rp = report_markdown("測試社", p.model_copy(update={"report": report, "attendance": 180}), 3600, {"文宣印刷": 1200})
    assert "**參加人數：** 180（預計 150）" in rp and "| 4,000 | 3,600 | +400 |" in rp and "| 文宣印刷 | 1,200 |" in rp


@pytest.mark.skipif(not pdf_available(), reason="沒有中文字型")
def test_badges_pdf_pages():
    data = badges_pdf([(f"社員{i}", "工作人員") for i in range(9)], "測試社", "成果展")
    assert data.startswith(b"%PDF") and len(data) > 1000

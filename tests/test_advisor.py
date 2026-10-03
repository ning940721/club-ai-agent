from club_agent.agents import DepartmentAdvisor
from club_agent.departments import DEPARTMENTS, department_retriever, get_department
from club_agent.report import advice_markdown
from club_agent.schemas import ActionStep, Advice, Coordination, Deliverable

from conftest import FakeLLM


def make_advice() -> Advice:
    return Advice(
        summary="先做預算表",
        steps=[ActionStep(step="列支出", detail="場地｜器材", owner="財務", timing="本週")],
        deliverables=[Deliverable(title="預算表欄位", content="| 項目 | 金額 |")],
        coordination=[Coordination(department="活動", what="提供流程")],
        risks=["預備金不足"],
        info_needed=["活動人數"],
    )


def test_departments_defined():
    assert [d.name for d in DEPARTMENTS.values()] == ["行銷", "公關", "財務", "活動", "場地", "會議記錄", "課程"]
    assert not get_department("marketing").beta
    assert all(d.beta for k, d in DEPARTMENTS.items() if k != "marketing")
    assert get_department("finance").label.endswith("（測試版）")


def test_every_department_has_knowledge():
    for key in DEPARTMENTS:
        retriever = department_retriever(key)
        sources = {c.source for c in retriever.chunks}
        if key != "marketing":
            assert f"{key}.md" in sources, key
            assert "04_campus_promotion_guidelines.md" in sources


def test_finance_retriever_finds_budget_knowledge():
    hits = department_retriever("finance").search("活動預算怎麼分配", k=2)
    assert hits and hits[0].source == "finance.md"


def test_advisor_prompt_includes_role_activity_and_knowledge(club):
    llm = FakeLLM({Advice: [make_advice()]})
    dept = get_department("finance")
    advice = DepartmentAdvisor(llm, department_retriever("finance")).run(club, dept, "成果展預算怎麼分配？", "- 行銷｜宣傳企劃")
    assert advice.summary == "先做預算表"
    system, user, _ = llm.calls[0]
    assert "預算健檢顧問" in system and "財務" in system
    assert "成果展預算怎麼分配？" in user
    assert "- 行銷｜宣傳企劃" in user
    assert "finance.md" in user


def test_advice_markdown():
    md = advice_markdown("財務", "怎麼分配？", make_advice())
    assert "財務部門顧問建議" in md and "預算表欄位" in md and "**活動**" in md
    assert "場地｜器材" in md  # 表格內的直線符號已轉成全形

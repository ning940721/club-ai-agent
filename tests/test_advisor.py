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
    assert list(DEPARTMENTS) == ["president", "marketing", "pr", "finance", "events", "minutes", "courses", "speakers", "venue", "members"]
    assert not get_department("marketing").beta
    assert all(d.beta for k, d in DEPARTMENTS.items() if k != "marketing")
    assert get_department("finance").label.endswith("（測試版）")
    assert all(d.details_hint for d in DEPARTMENTS.values())


def test_club_settings_names_and_details():
    from club_agent.departments import DEFAULT_ENABLED, ClubSettings, DepartmentConfig

    s = ClubSettings.default()
    assert s.enabled_keys() == list(DEFAULT_ENABLED)
    s.departments["finance"] = DepartmentConfig(enabled=True, display_name="財務長", details="500 元以上需社長核准")
    assert s.name("finance") == "財務長" and s.name("pr") == "公關"
    assert s.label("finance") == "財務長"
    assert "500 元以上需社長核准" in s.all_details_text()
    assert "課程" not in s.all_details_text()  # 未啟用的部門不列入


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
    from club_agent.departments import ClubSettings, DepartmentConfig

    settings = ClubSettings.default()
    settings.departments["finance"] = DepartmentConfig(enabled=True, display_name="財務長", details="每月 5 號撥款")
    llm = FakeLLM({Advice: [make_advice()]})
    dept = get_department("finance")
    advice = DepartmentAdvisor(llm, department_retriever("finance")).run(
        club, dept, "成果展預算怎麼分配？", "- 行銷｜宣傳企劃", settings, "- 待辦｜編列預算"
    )
    assert advice.summary == "先做預算表"
    system, user, _ = llm.calls[0]
    assert "預算健檢顧問" in system and "財務長" in system
    assert "每月 5 號撥款" in user and "- 待辦｜編列預算" in user
    assert "成果展預算怎麼分配？" in user
    assert "- 行銷｜宣傳企劃" in user
    assert "finance.md" in user


def test_advice_markdown():
    md = advice_markdown("財務", "怎麼分配？", make_advice())
    assert "財務部門顧問建議" in md and "預算表欄位" in md and "**活動**" in md
    assert "場地｜器材" in md  # 表格內的直線符號已轉成全形


def test_features_reassigned_and_custom_department():
    from club_agent.departments import FEATURE_EVENTS, FEATURE_PR, FEATURE_SPEAKERS, ClubSettings, DepartmentConfig, department_retriever

    s = ClubSettings.default()
    assert s.features("pr") == (FEATURE_PR,)
    s = s.model_copy(update={"departments": {**s.departments, "pr": DepartmentConfig(enabled=True, features=[FEATURE_SPEAKERS, FEATURE_PR])}})
    assert s.features("pr") == (FEATURE_PR, FEATURE_SPEAKERS)  # 依功能模組的固定順序
    s, key = s.with_custom("學術部", [FEATURE_EVENTS], "負責讀書會")
    assert key.startswith("custom_") and s.enabled_keys()[-1] == key
    dept = s.department(key)
    assert dept.name == "學術部" and dept.features == (FEATURE_EVENTS,) and "活動專案" in dept.focus
    assert s.name("design") == "美宣"  # 已併入行銷的舊部門
    assert department_retriever(key).chunks  # 自訂部門使用共用知識庫
    assert any("design.md" == c.source for c in department_retriever("marketing").chunks)  # 美宣知識併入行銷

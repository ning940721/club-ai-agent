"""網頁版冒煙測試：以假的 LLM 取代 Gemini，確認登入、各部門頁面與設定流程可以走完。"""

from pathlib import Path

import pytest

st_testing = pytest.importorskip("streamlit.testing.v1")

from club_agent.llm import GeminiLLM
from club_agent.schemas import (
    Advice,
    AgendaItem,
    CampaignPlan,
    Critique,
    DepartmentStatus,
    DiagnosisReport,
    MeetingAnswer,
    MeetingSummary,
    ProgressBrief,
    SourceRef,
)

from conftest import make_critique, make_diagnosis, make_plan
from test_advisor import make_advice
from test_meetings import make_summary

APP = str(Path(__file__).parent.parent / "app.py")


@pytest.fixture(autouse=True)
def env(monkeypatch, tmp_path):
    outputs = {
        DiagnosisReport: make_diagnosis(),
        CampaignPlan: make_plan("網頁測試企劃"),
        Critique: make_critique([5, 5, 5, 5]),
        Advice: make_advice(),
        MeetingSummary: make_summary(),
        MeetingAnswer: MeetingAnswer(
            found=True, answer="下次幹部會是 12/4 19:00", sources=[SourceRef(title="幹部會", date="2026-10-03", excerpt="12/4")]
        ),
        ProgressBrief: ProgressBrief(
            overview="各部門進度正常",
            departments=[DepartmentStatus(department="公關", doing=["找贊助"], progress="進行中", blockers=[])],
            agenda=[AgendaItem(topic="贊助進度", department="公關", kind="討論", minutes=20, goal="決定名單")],
            decisions_needed=[],
            reminders=[],
        ),
    }
    monkeypatch.setattr(GeminiLLM, "structured", lambda self, system, user, output_type: outputs[output_type])
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setenv("CLUB_AGENT_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("SIGNUP_CODE", raising=False)


def _app():
    return st_testing.AppTest.from_file(APP, default_timeout=30).run()


def _button(at, label):
    return next(b for b in at.button if b.label == label)


def _input(at, label):
    return next(w for w in [*at.text_input, *at.text_area] if w.label == label)


def _signup(at, account="test-club", password="secret123"):
    _input(at, "設定社團帳號（英文或數字，例：ntu-photo）").input(account)
    _input(at, "設定密碼（至少 6 個字元）").input(password)
    _input(at, "再輸入一次密碼").input(password)
    _input(at, "社團名稱＊").input("測試攝影社")
    _input(at, "社團定位與特色＊").input("街頭攝影")
    _input(at, "主要目標受眾＊").input("大一新生")
    _button(at, "建立帳號並登入").click().run()
    assert not at.exception


def _page_title(at) -> str:
    return " ".join(m.value for m in at.markdown if "page-title" in m.value)


def _switch(at, dept):
    at.selectbox(key="dept").select(dept).run()
    assert not at.exception


def test_signup_lands_on_president_overview():
    at = _app()
    _signup(at)
    assert "社長" in _page_title(at) and "測試攝影社" in _page_title(at)
    assert at.selectbox(key="dept").options == ["社長", "行銷", "公關", "財務", "活動", "會議記錄"]
    _button(at, "產生進度彙整與議程").click().run()
    assert not at.exception
    assert any("各部門進度正常" in m.value for m in at.markdown)
    schedule = at.dataframe[-1].value
    assert schedule.loc[0, "時間"] == "19:00–19:20" and schedule.loc[0, "議題"] == "贊助進度"
    assert any("比預定時長少 70 分鐘" in c.value for c in at.caption)


def test_meeting_duration_is_remembered_and_template_agenda_needs_no_ai():
    at = _app()
    _signup(at)
    at.number_input(key="mt_minutes").set_value(60).run()
    _button(at, "使用基本議程（不使用 AI）").click().run()
    assert not at.exception
    schedule = at.dataframe[-1].value
    assert schedule["分鐘"].sum() == 60 and schedule.loc[0, "時間"].startswith("19:00")
    assert any("剛好符合預定時長" in c.value for c in at.caption)
    at2 = _app()  # 重新整理後仍記得會議時長
    at2.text_input[0].input("test-club")
    at2.text_input[1].input("secret123")
    at2.button[0].click().run()
    assert at2.number_input(key="mt_minutes").value == 60


def test_department_advice_shows_in_feed():
    at = _app()
    _signup(at)
    _switch(at, "finance")
    _button(at, "取得建議").click().run()
    assert any("請先輸入問題" in w.value for w in at.warning)
    _input(at, "你的問題").input("成果展預算怎麼分配？")
    _button(at, "取得建議").click().run()
    assert not at.exception
    assert any("先做預算表" in m.value for m in at.markdown)
    _switch(at, "pr")
    assert any("成果展預算怎麼分配？" in m.value for m in at.markdown)


def test_tasks_added_in_department_show_on_president_overview():
    at = _app()
    _signup(at)
    _switch(at, "pr")
    _input(at, "事項").input("寄贊助邀請信")
    _input(at, "負責人").input("小明")
    next(b for b in at.button if b.label == "新增").click().run()
    assert not at.exception
    _switch(at, "president")
    assert not at.exception
    table = at.dataframe[0].value
    assert table.loc[table["部門"] == "公關", "未完成"].item() == 1


def test_meeting_summary_tasks_and_qa():
    at = _app()
    _signup(at)
    _switch(at, "minutes")
    _input(at, "或直接貼上內容").input("小明：下次開會改到 12/4 晚上七點\n決議：成果展預算 3 萬元")
    _input(at, "標題").input("第 5 次幹部會")
    _button(at, "整理重點並儲存").click().run()
    assert not at.exception
    assert any("成果展預算 3 萬元" in m.value for m in at.markdown)
    _button(at, "加入待辦").click().run()
    assert any("已加入 1 項待辦" in s.value for s in at.success)

    _input(at, "你的問題").input("下次開會是什麼時候？")
    next(b for b in at.button if b.label == "提問").click().run()
    assert not at.exception
    assert any("下次幹部會是 12/4 19:00" in m.value for m in at.markdown)

    _switch(at, "president")
    assert any("2026-12-04" in m.value for m in at.markdown)  # 近期重要日期


def _open_settings(at):
    at.button(key="side_settings").click().run()
    assert not at.exception
    assert "社團設定" in _page_title(at)


def test_settings_and_help_live_in_sidebar():
    at = _app()
    _signup(at)
    assert "社團設定" not in [t.label for t in at.tabs]
    at.button(key="side_help").click().run()
    assert "使用說明" in _page_title(at)
    _button(at, "返回部門功能").click().run()
    assert "社長" in _page_title(at)


def test_settings_enable_rename_and_details():
    at = _app()
    _signup(at)
    _open_settings(at)
    at.checkbox(key="set_en_courses").check()
    at.text_input(key="set_name_finance").input("財務長")
    at.text_area(key="set_details_finance").input("500 元以上需社長核准")
    _button(at, "儲存部門設定").click().run()
    assert not at.exception
    options = at.selectbox(key="dept").options
    assert "課程" in options and "財務長" in options

    at.checkbox(key="set_en_president").uncheck()
    _button(at, "儲存部門設定").click().run()
    assert at.selectbox(key="dept").value == "marketing"  # 原本的部門被關閉後，自動換到第一個啟用的部門


def test_login_logout_and_change_password():
    at = _app()
    _signup(at, "club-x")
    _open_settings(at)
    old = next(w for w in at.text_input if w.label == "目前的密碼")
    old.input("secret123")
    next(w for w in at.text_input if w.label == "新密碼（至少 6 個字元）").input("newpass123")
    next(w for w in at.text_input if w.label == "再輸入一次新密碼").input("newpass123")
    next(b for b in at.button if b.label == "變更密碼").click().run()
    assert any("密碼已變更" in s.value for s in at.success)

    _button(at, "登出").click().run()
    assert len(at.tabs) == 2
    # 以下改用新頁面登入：AppTest 登出後仍會去讀已消失的部門選單而出錯，實際網頁不會
    at = _app()
    at.text_input[0].input("club-x")
    at.text_input[1].input("secret123")
    at.button[0].click().run()
    assert any("帳號或密碼錯誤" in e.value for e in at.error)
    at = _app()
    at.text_input[0].input("club-x")
    at.text_input[1].input("newpass123")
    at.button[0].click().run()
    assert "測試攝影社" in _page_title(at)


def test_marketing_tools_flow():
    at = _app()
    _signup(at)
    _switch(at, "marketing")
    _button(at, "開始診斷").click().run()
    assert not at.exception
    assert any("流量瓶頸" in m.value for m in at.markdown)
    _button(at, "產生宣傳企劃").click().run()
    assert any("請先填寫活動名稱" in w.value for w in at.warning)
    _input(at, "活動名稱＊").input("跨校社團聯展")
    _button(at, "產生宣傳企劃").click().run()
    assert not at.exception
    assert any("網頁測試企劃" in m.value for m in at.markdown)
    assert "2 / 20" in " ".join(c.value for c in at.caption)


def test_signup_code_required(monkeypatch):
    monkeypatch.setenv("SIGNUP_CODE", "pilot2026")
    at = _app()
    _input(at, "設定社團帳號（英文或數字，例：ntu-photo）").input("x-club")
    _button(at, "建立帳號並登入").click().run()
    assert any("邀請碼錯誤" in e.value for e in at.error)


def test_advisor_and_feed_are_last_tabs():
    at = _app()
    _signup(at)
    _switch(at, "marketing")
    assert [t.label for t in at.tabs][-2:] == ["部門顧問", "社團動態"]


def test_advice_not_shared_until_officer_chooses():
    at = _app()
    _signup(at)
    _switch(at, "finance")
    at.toggle(key="share_advice_finance").set_value(False).run()
    _input(at, "你的問題").input("成果展預算怎麼分配？")
    _button(at, "取得建議").click().run()
    assert any("先做預算表" in m.value for m in at.markdown)
    _switch(at, "pr")
    assert not any("成果展預算怎麼分配？" in m.value for m in at.markdown)  # 沒有出現在社團動態

    _switch(at, "finance")
    at.button(key="share_btn_advice_finance").click().run()
    assert not at.exception
    assert any("已分享到社團動態" in c.value for c in at.caption)
    _switch(at, "pr")
    assert any("成果展預算怎麼分配？" in m.value for m in at.markdown)


def test_quick_qa_answers_from_club_records():
    at = _app()
    _signup(at)
    _switch(at, "pr")
    at.session_state["advisor_mode_pr"] = "快速問答"  # AppTest 尚不支援操作 segmented_control
    at.run()
    _button(at, "上次開會決定了什麼？").click().run()
    next(b for b in at.button if b.label == "提問").click().run()
    assert not at.exception
    assert any("下次幹部會是 12/4 19:00" in m.value for m in at.markdown)


def test_edited_template_agenda_can_be_shared():
    at = _app()
    _signup(at)
    _button(at, "使用基本議程（不使用 AI）").click().run()
    at.button(key="share_btn_brief").click().run()
    assert not at.exception
    assert any("已分享到社團動態" in c.value for c in at.caption)
    _switch(at, "pr")
    assert any("幹部會議議程" in m.value for m in at.markdown)


def test_calendar_add_event_and_show_planned_meeting():
    at = _app()
    _signup(at)
    _button(at, "使用基本議程（不使用 AI）").click().run()  # 排好的會議會出現在行事曆
    _switch(at, "pr")
    _input(at, "行程名稱＊").input("贊助商拜訪")
    _button(at, "加入行事曆").click().run()
    assert not at.exception
    assert any("已新增「贊助商拜訪」" in s.value for s in at.success)
    page = " ".join(m.value for m in at.markdown)
    assert "贊助商拜訪" in page and "幹部會議" in page


def test_meeting_record_is_checked_against_agenda_and_follow_up_shown(monkeypatch):
    from club_agent.schemas import AgendaCheck

    at = _app()
    _signup(at)
    _button(at, "使用基本議程（不使用 AI）").click().run()
    assert any("議程會自動儲存" in c.value for c in at.caption)

    review = [AgendaCheck(topic="討論與決議事項", result="已討論、未決議", note="場地還在比價")]
    original = GeminiLLM.structured
    seen_prompts = []

    def fake(self, system, user, output_type):
        if output_type is MeetingSummary:
            seen_prompts.append(user)
            return make_summary(agenda_review=review)
        return original(self, system, user, output_type)

    monkeypatch.setattr(GeminiLLM, "structured", fake)
    _switch(at, "minutes")
    from datetime import date, timedelta

    plan_id = (date.today() + timedelta(days=7)).isoformat()  # 社長頁面預設的會議日期
    at.session_state[f"m_plan_{date.today().isoformat()}"] = plan_id  # AppTest 無法操作自訂顯示文字的下拉選單
    at.run()
    _input(at, "或直接貼上內容").input("討論場地，還沒決定")
    _button(at, "整理重點並儲存").click().run()
    assert not at.exception
    assert "<agenda>" in seen_prompts[0] and "討論與決議事項" in seen_prompts[0]
    assert any("議程對照" in m.value for m in at.markdown)

    _switch(at, "president")
    assert any("上次會議議程追蹤" in m.value for m in at.markdown)
    assert any("討論與決議事項：已討論、未決議" in m.value for m in at.markdown)

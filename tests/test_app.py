"""網頁版冒煙測試：以假的 LLM 取代 Gemini，確認登入、各部門頁面與設定流程可以走完。"""

import os
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


def _open(at, page):
    """打開側邊欄的頁面：feed、calendar、reimburse、settings、help。"""
    at.button(key=f"side_{page}").click().run()
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
    _open(at, "feed")
    assert any("成果展預算怎麼分配？" in m.value for m in at.markdown)


def test_tasks_added_in_department_show_on_president_overview():
    at = _app()
    _signup(at)
    _switch(at, "pr")
    _open(at, "tasks")  # 待辦在側邊欄「幹部共用」，部門預設為目前的部門
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


def test_shared_features_live_in_sidebar():
    at = _app()
    _signup(at)
    _switch(at, "marketing")
    labels = [t.label for t in at.tabs]
    assert labels == ["社群數據診斷", "活動宣傳企劃", "部門顧問"]
    for page, title in (("tasks", "待辦與進度"), ("feed", "AI Agent 問答"), ("calendar", "行事曆"), ("reimburse", "報帳申請")):
        _open(at, page)
        assert title in _page_title(at)
    _switch(at, "pr")  # 換部門時回到部門功能
    assert "公關" in _page_title(at)


def test_advice_not_shared_until_officer_chooses():
    at = _app()
    _signup(at)
    _switch(at, "finance")
    at.toggle(key="share_advice_finance").set_value(False).run()
    _input(at, "你的問題").input("成果展預算怎麼分配？")
    _button(at, "取得建議").click().run()
    assert any("先做預算表" in m.value for m in at.markdown)
    _open(at, "feed")
    assert not any("成果展預算怎麼分配？" in m.value for m in at.markdown)  # 沒有分享給其他部門

    _button(at, "返回部門功能").click().run()
    at.button(key="share_btn_advice_finance").click().run()
    assert not at.exception
    assert any("已分享" in c.value for c in at.caption)
    _open(at, "feed")
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
    assert any("已分享" in c.value for c in at.caption)
    _open(at, "feed")
    assert any("幹部會議議程" in m.value for m in at.markdown)


def test_calendar_add_event_and_show_planned_meeting():
    at = _app()
    _signup(at)
    _button(at, "使用基本議程（不使用 AI）").click().run()  # 排好的會議會出現在行事曆
    _switch(at, "pr")
    _open(at, "calendar")
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


def _unlock_finance(at, pin="8888"):
    pin_inputs = [w for w in at.text_input if w.label in ("設定財務密碼（至少 4 個字元）", "再輸入一次", "財務密碼")]
    for w in pin_inputs:
        w.input(pin)
    label = "設定並進入" if len(pin_inputs) == 2 else "進入"
    _button(at, label).click().run()
    assert not at.exception


def test_reimbursement_request_review_and_payment():
    at = _app()
    _signup(at)
    _switch(at, "events")
    assert "財務管理" not in [t.label for t in at.tabs]  # 其他部門看不到財務
    _open(at, "reimburse")
    _input(at, "申請人＊").input("小華")
    _input(at, "項目＊").input("成果展海報")
    next(n for n in at.number_input if n.label == "金額（元）＊").set_value(1500)
    _input(at, "發票號碼").input("AB12345678")
    _button(at, "送出申請").click().run()
    assert not at.exception
    message = next(s.value for s in at.success if "報帳編號" in s.value)
    code = message.split("**")[1]

    _switch(at, "finance")
    assert [t.label for t in at.tabs] == ["部門顧問"]  # 解鎖前看不到財務分頁
    assert any("請先設定**財務密碼**" in i.value for i in at.info)
    _unlock_finance(at)
    assert [t.label for t in at.tabs][:5] == ["報帳審核（1）", "收支帳簿", "預算", "財務報表", "規範與設定"]
    assert any(code in m.value and "1,500 元" in m.value for m in at.markdown)
    at.button(key=f"rv_ok_{code}").click().run()
    assert not at.exception
    _button(at, "標記為已撥款").click().run()
    assert any("已標記 1 筆為已撥款" in s.value for s in at.success)
    assert any(m.label == "本學期支出" and m.value == "1,500" for m in at.metric)

    _switch(at, "pr")  # 申請人用編號查詢進度
    _open(at, "reimburse")
    _input(at, "報帳編號").input(code.lower())
    _button(at, "查詢").click().run()
    assert any("狀態：**已撥款**" in m.value for m in at.markdown)


def test_finance_pin_required_and_big_amount_needs_president():
    at = _app()
    _signup(at)
    _switch(at, "finance")
    _unlock_finance(at)
    _button(at, "鎖定").click().run()
    _input(at, "財務密碼").input("0000")
    _button(at, "進入").click().run()
    assert any("財務密碼錯誤" in e.value for e in at.error)

    _input(at, "財務密碼").input("8888")
    _button(at, "進入").click().run()
    _open(at, "reimburse")
    _input(at, "申請人＊").input("小明")
    _input(at, "項目＊").input("音響租借")
    next(n for n in at.number_input if n.label == "金額（元）＊").set_value(5000)
    _button(at, "送出申請").click().run()
    code = next(s.value for s in at.success if "報帳編號" in s.value).split("**")[1]
    _button(at, "返回部門功能").click().run()
    at.button(key=f"rv_ok_{code}").click().run()
    assert any("需要社長同意" in e.value for e in at.error)
    at.checkbox(key=f"rv_pres_{code}").check()
    at.button(key=f"rv_ok_{code}").click().run()
    assert any("已核准、待撥款（1 筆，共 5,000 元）" in m.value for m in at.markdown)


def test_speakers_department_flow(monkeypatch):
    from club_agent.schemas import Letter

    original = GeminiLLM.structured
    monkeypatch.setattr(GeminiLLM, "structured", lambda self, system, user, output_type: (
        Letter(subject="講座邀請：手機街拍", body="王老師您好……", short_text="短版") if output_type is Letter
        else original(self, system, user, output_type)))
    at = _app()
    _signup(at)
    _open(at, "settings")
    at.checkbox(key="set_en_speakers").check()
    _button(at, "儲存部門設定").click().run()
    _switch(at, "speakers")
    assert [t.label for t in at.tabs] == ["講座總覽（0）", "新增講座", "信件與通知", "講座彙整", "部門顧問"]
    _input(at, "講者姓名＊").input("王小明")
    _input(at, "講座主題＊").input("手機街拍")
    _input(at, "聯絡方式").input("ming@example.com")
    _button(at, "新增講座").click().run()
    assert any("已新增「王小明｜手機街拍」" in s.value for s in at.success)

    _button(at, "產生").click().run()
    assert not at.exception
    assert any(t.value == "講座邀請：手機街拍" for t in at.text_input)
    _button(at, "存到往來紀錄").click().run()
    assert any("進度改為已邀請" in s.value for s in at.success)


def test_event_project_flow(monkeypatch):
    from club_agent.schemas import EventProposal, EventReport, FeedbackForm, FeedbackQuestion
    from test_projects import make_proposal

    fakes = {
        EventProposal: make_proposal(),
        FeedbackForm: FeedbackForm(title="成果展回饋", intro="謝謝", questions=[
            FeedbackQuestion(question="整體滿意度", type="線性刻度", options=["差", "好"], required=True)]),
        EventReport: EventReport(summary="成果展圓滿結束", results=["180 人"], highlights=["體驗"], budget_review="—",
                                 feedback_summary="好評", improvements=["提早宣傳"], handover=["提早借場地"]),
    }
    original = GeminiLLM.structured
    monkeypatch.setattr(GeminiLLM, "structured", lambda self, system, user, output_type: (
        fakes[output_type] if output_type in fakes else original(self, system, user, output_type)))
    at = _app()
    _signup(at)
    _switch(at, "events")
    assert [t.label for t in at.tabs] == ["部門顧問"]  # 還沒有活動
    _input(at, "活動名稱＊").input("期末成果展")
    _button(at, "建立活動").click().run()
    assert any("已建立「期末成果展」" in s.value for s in at.success)

    _button(at, "產生企劃書").click().run()
    assert not at.exception
    assert any("展示社員作品" in m.value for m in at.markdown)
    _button(at, "把企劃書的 3 項籌備工作加入待辦").click().run()
    assert any("已加入 3 項籌備工作" in s.value for s in at.success)

    _button(at, "產生回饋表單題目").click().run()
    assert any("整體滿意度［線性刻度，必填］" in c.value for c in at.code)
    _button(at, "產生成果報告").click().run()
    assert not at.exception
    assert any("成果展圓滿結束" in m.value for m in at.markdown)

    from club_agent.store import LocalClubStore
    from club_agent.tasks import list_tasks

    store = LocalClubStore(os.environ["CLUB_AGENT_DATA_DIR"])  # 籌備工作是全社團待辦，行銷部門看得到
    tasks = list_tasks(store, at.session_state.club_id, "marketing")
    assert [t.title for t in tasks] == ["IG 宣傳貼文"] and tasks[0].source == "活動「期末成果展」"


def test_pr_partners_ideas_and_letters(monkeypatch):
    from club_agent.schemas import Letter, SponsorIdea, SponsorIdeas

    fakes = {
        SponsorIdeas: SponsorIdeas(ideas=[SponsorIdea(target_type="學校周邊飲料店", why="受眾重疊", ask="50 杯飲料",
                                                      offer="IG 貼文 2 篇", search_keywords=["公館 飲料店"])], tips=["提早聯絡"]),
        Letter: Letter(subject="【攝影社成果展】贊助邀請", body="您好……", short_text="短版"),
    }
    original = GeminiLLM.structured
    monkeypatch.setattr(GeminiLLM, "structured", lambda self, system, user, output_type: (
        fakes[output_type] if output_type in fakes else original(self, system, user, output_type)))
    at = _app()
    _signup(at)
    _switch(at, "pr")
    assert [t.label for t in at.tabs][:4] == ["找贊助對象", "合作對象（0）", "合作信件", "贊助彙整"]
    _button(at, "建議贊助對象").click().run()
    assert any("學校周邊飲料店" in m.value for m in at.markdown)

    # 「找贊助對象」是第一個分頁：搜尋後直接把找到的店家加入名單
    _input(at, "單位／店家名稱＊").input("好喝飲料")
    _input(at, "聯絡方式").input("drink@example.com")
    _button(at, "加入").click().run()
    assert any("已把「好喝飲料」加入合作對象" in s.value for s in at.success)

    _button(at, "產生").click().run()
    assert any(t.value == "【攝影社成果展】贊助邀請" for t in at.text_input)
    _button(at, "存到往來紀錄").click().run()
    assert any("進度改為已聯絡" in s.value for s in at.success)


def test_ai_agent_page_answers_from_search_box():
    at = _app()
    _signup(at)
    _open(at, "feed")
    assert "AI Agent 問答" in _page_title(at)
    _button(at, "下次發文時間是什麼時候？").click().run()  # 點範例問題就直接查詢
    assert not at.exception
    assert any("**Q：下次發文時間是什麼時候？**" in m.value for m in at.markdown)
    _input(at, "想查什麼？").input("成果展在哪裡辦？")
    _button(at, "提問").click().run()
    assert any("**Q：成果展在哪裡辦？**" in m.value for m in at.markdown)
    assert any(h.value == "各部門分享的成果" for h in at.subheader)

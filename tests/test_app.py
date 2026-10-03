"""網頁版冒煙測試：以假的 LLM 取代 Gemini，確認登入與各頁面流程可以走完。"""

from pathlib import Path

import pytest

st_testing = pytest.importorskip("streamlit.testing.v1")

from club_agent.llm import GeminiLLM
from club_agent.schemas import Advice, CampaignPlan, Critique, DiagnosisReport

from conftest import make_critique, make_diagnosis, make_plan
from test_advisor import make_advice

APP = str(Path(__file__).parent.parent / "app.py")


@pytest.fixture(autouse=True)
def env(monkeypatch, tmp_path):
    outputs = {
        DiagnosisReport: make_diagnosis(),
        CampaignPlan: make_plan("網頁測試企劃"),
        Critique: make_critique([5, 5, 5, 5]),
        Advice: make_advice(),
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


def test_signup_then_department_advice_shows_in_feed():
    at = _app()
    assert not at.exception
    _signup(at)
    assert not at.exception
    assert "測試攝影社" in at.title[0].value

    at.selectbox(key="dept").select("finance").run()
    assert "財務部門" in at.title[0].value
    _button(at, "取得建議").click().run()
    assert any("請先輸入問題" in w.value for w in at.warning)
    _input(at, "你的問題").input("成果展預算怎麼分配？")
    _button(at, "取得建議").click().run()
    assert not at.exception
    assert any("先做預算表" in m.value for m in at.markdown)
    # 其他部門看得到財務部的紀錄
    at.selectbox(key="dept").select("pr").run()
    assert any("成果展預算怎麼分配？" in m.value for m in at.markdown)


def test_login_and_wrong_password():
    at = _app()
    _signup(at, "club-x")
    _button(at, "登出").click().run()
    assert len(at.tabs) == 2  # 回到登入畫面
    at.text_input[0].input("club-x")
    at.text_input[1].input("wrongpass")
    at.button[0].click().run()
    assert any("帳號或密碼錯誤" in e.value for e in at.error)
    at.text_input[1].input("secret123")
    at.button[0].click().run()
    assert "測試攝影社" in at.title[0].value


def test_marketing_tools_flow():
    at = _app()
    _signup(at)
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
    _signup(at)
    assert any("邀請碼錯誤" in e.value for e in at.error)

"""網頁版冒煙測試：以假的 LLM 取代 Gemini，確認頁面流程可以走完。"""

from pathlib import Path

import pytest

st_testing = pytest.importorskip("streamlit.testing.v1")

from club_agent.llm import GeminiLLM
from club_agent.schemas import CampaignPlan, Critique, DiagnosisReport

from conftest import make_critique, make_diagnosis, make_plan

APP = str(Path(__file__).parent.parent / "app.py")


@pytest.fixture
def fake_gemini(monkeypatch):
    outputs = {DiagnosisReport: make_diagnosis(), CampaignPlan: make_plan("網頁測試企劃"), Critique: make_critique([5, 5, 5, 5])}
    monkeypatch.setattr(GeminiLLM, "structured", lambda self, system, user, output_type: outputs[output_type])
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.delenv("APP_PASSWORD", raising=False)


def _button(at, label):
    return next(b for b in at.button if b.label == label)


def test_password_gate(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "secret")
    at = st_testing.AppTest.from_file(APP).run()
    assert not at.tabs  # 未輸入密碼前看不到主畫面
    at.text_input[0].input("wrong")
    _button(at, "進入").click().run()
    assert at.error[0].value == "密碼錯誤"
    at.text_input[0].input("secret")
    _button(at, "進入").click().run()
    assert len(at.tabs) == 3


def test_diagnosis_and_campaign_flow(fake_gemini):
    at = st_testing.AppTest.from_file(APP, default_timeout=30).run()
    assert not at.exception
    _button(at, "填入範例社團").click().run()
    _button(at, "開始診斷").click().run()
    assert not at.exception
    assert any("流量瓶頸" in m.value for m in at.markdown)

    event = next(t for t in at.text_input if t.label == "活動名稱＊")
    event.input("跨校社團聯展")
    at.run()
    _button(at, "產生宣傳企劃").click().run()
    assert not at.exception
    assert any("網頁測試企劃" in m.value for m in at.markdown)
    assert "2 / 20" in " ".join(c.value for c in at.caption)

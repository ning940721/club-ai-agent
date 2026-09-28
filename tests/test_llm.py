import json

import pytest
from google.genai import types

from club_agent import llm as llm_mod
from club_agent.llm import GeminiLLM, LLMError, create_llm, inline_json_schema
from club_agent.schemas import CampaignPlan, Critique

CRITIQUE = {"scores": [{"criterion": "a", "score": 4, "comment": "ok"}], "overall_score": 4, "approved": True, "strengths": [], "revision_requests": []}


class FakeModels:
    def __init__(self, text, finish="STOP"):
        self.text, self.finish, self.kwargs = text, finish, None

    def generate_content(self, **kwargs):
        self.kwargs = kwargs
        return types.GenerateContentResponse(
            candidates=[types.Candidate(content=types.Content(role="model", parts=[types.Part(text=self.text)]), finish_reason=self.finish)]
        )


class FakeClient:
    def __init__(self, models):
        self.models = models


def test_inline_schema_has_no_refs():
    dumped = json.dumps(inline_json_schema(CampaignPlan))
    assert "$ref" not in dumped and "$defs" not in dumped
    assert "suggested_publish_time" in dumped


def test_gemini_structured_parses_output():
    models = FakeModels(json.dumps(CRITIQUE))
    result = GeminiLLM(model="gemini-test", client=FakeClient(models)).structured("系統", "使用者", Critique)
    assert result.scores[0].score == 4
    cfg = models.kwargs["config"]
    assert models.kwargs["model"] == "gemini-test"
    assert cfg.system_instruction == "系統" and cfg.response_mime_type == "application/json"


def test_gemini_errors():
    with pytest.raises(LLMError, match="max_output_tokens"):
        GeminiLLM(client=FakeClient(FakeModels('{"scores":', finish="MAX_TOKENS"))).structured("s", "u", Critique)
    with pytest.raises(LLMError, match="格式"):
        GeminiLLM(client=FakeClient(FakeModels('{"foo": 1}'))).structured("s", "u", Critique)


def test_create_llm_selects_provider(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test")
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("CLUB_AGENT_PROVIDER", raising=False)
    monkeypatch.delenv("CLUB_AGENT_MODEL", raising=False)
    llm = create_llm()
    assert isinstance(llm, GeminiLLM) and llm.model == llm_mod.DEFAULT_MODELS["gemini"]
    monkeypatch.setenv("CLUB_AGENT_MODEL", "gemini-pro-latest")
    assert create_llm("gemini").model == "gemini-pro-latest"
    with pytest.raises(ValueError):
        create_llm("unknown")

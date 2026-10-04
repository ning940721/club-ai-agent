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
    with pytest.raises(LLMError, match="截斷"):
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


class FlakyModels:
    """前 n 次呼叫丟出指定錯誤，之後回傳正常結果；記錄每次使用的模型。"""

    def __init__(self, failures: int, code: int = 503, quota_id: str = ""):
        from google.genai import errors

        self.failures, self.code, self.errors, self.models = failures, code, errors, []
        self.quota_id = quota_id

    def generate_content(self, **kwargs):
        self.models.append(kwargs["model"])
        if len(self.models) <= self.failures:
            cls = self.errors.ServerError if self.code >= 500 else self.errors.ClientError
            details = [{"violations": [{"quotaId": self.quota_id}]}, {"retryDelay": "7s"}] if self.quota_id else []
            raise cls(self.code, {"error": {"code": self.code, "message": "busy", "status": "UNAVAILABLE", "details": details}})
        return FakeModels(json.dumps(CRITIQUE)).generate_content(**kwargs)


def _flaky_llm(models, **kw):
    return GeminiLLM(
        model="main",
        client=FakeClient(models),
        fallback_models=["backup"],
        retries_per_model=2,
        notify=lambda _m: None,
        sleep=lambda _s: None,
        **kw,
    )


def test_gemini_retries_then_succeeds():
    models = FlakyModels(failures=2)
    assert _flaky_llm(models).structured("s", "u", Critique).scores[0].score == 4
    assert models.models == ["main", "main", "main"]


def test_gemini_falls_back_to_backup_model():
    models = FlakyModels(failures=3)
    _flaky_llm(models).structured("s", "u", Critique)
    assert models.models == ["main"] * 3 + ["backup"]


def test_gemini_gives_up_with_friendly_error():
    with pytest.raises(LLMError, match="忙碌"):
        _flaky_llm(FlakyModels(failures=99)).structured("s", "u", Critique)


def test_gemini_non_retryable_error_raises_immediately():
    models = FlakyModels(failures=99, code=400)
    with pytest.raises(LLMError, match="400"):
        _flaky_llm(models).structured("s", "u", Critique)
    assert models.models == ["main"]


def test_daily_quota_skips_retries_and_explains():
    models = FlakyModels(failures=99, code=429, quota_id="GenerateRequestsPerDayPerProjectPerModel-FreeTier")
    with pytest.raises(LLMError, match="今天的免費額度"):
        _flaky_llm(models).structured("s", "u", Critique)
    assert models.models == ["main", "backup"]  # 每個模型只試一次


def test_daily_quota_on_main_model_uses_backup():
    models = FlakyModels(failures=1, code=429, quota_id="GenerateRequestsPerDayPerProjectPerModel-FreeTier")
    assert _flaky_llm(models).structured("s", "u", Critique).scores[0].score == 4
    assert models.models == ["main", "backup"]


def test_minute_quota_waits_suggested_delay():
    waits = []
    models = FlakyModels(failures=99, code=429, quota_id="GenerateRequestsPerMinutePerProjectPerModel-FreeTier")
    llm = GeminiLLM(model="main", client=FakeClient(models), fallback_models=[], retries_per_model=1, notify=lambda _m: None, sleep=waits.append)
    with pytest.raises(LLMError, match="每分鐘"):
        llm.structured("s", "u", Critique)
    assert waits == [7.0]


class ModelSpecificErrors:
    """依模型名稱回傳指定錯誤碼，未指定的模型正常回應。"""

    def __init__(self, codes: dict[str, int]):
        from google.genai import errors

        self.codes, self.errors, self.models = codes, errors, []

    def generate_content(self, **kwargs):
        model = kwargs["model"]
        self.models.append(model)
        if model in self.codes:
            code = self.codes[model]
            cls = self.errors.ServerError if code >= 500 else self.errors.ClientError
            raise cls(code, {"error": {"code": code, "message": "x", "status": "X"}})
        return FakeModels(json.dumps(CRITIQUE)).generate_content(**kwargs)


def test_unavailable_fallback_model_is_skipped():
    models = ModelSpecificErrors({"main": 503, "retired": 404})
    llm = GeminiLLM(model="main", client=FakeClient(models), fallback_models=["retired", "good"], retries_per_model=1, notify=lambda _m: None, sleep=lambda _s: None)
    assert llm.structured("s", "u", Critique).scores[0].score == 4
    assert models.models == ["main", "main", "retired", "good"]


def test_all_models_unavailable_explains_setting():
    models = ModelSpecificErrors({"a": 404, "b": 404})
    llm = GeminiLLM(model="a", client=FakeClient(models), fallback_models=["b"], notify=lambda _m: None, sleep=lambda _s: None)
    with pytest.raises(LLMError, match="GEMINI_MODEL"):
        llm.structured("s", "u", Critique)


def test_thinking_level_is_sent_and_configurable(monkeypatch):
    monkeypatch.delenv("CLUB_AGENT_THINKING", raising=False)
    models = FakeModels(json.dumps(CRITIQUE))
    GeminiLLM(client=FakeClient(models)).structured("s", "u", Critique)
    assert models.kwargs["config"].thinking_config.thinking_level == "LOW"  # 預設低思考程度，回應較快

    GeminiLLM(client=FakeClient(models), thinking="minimal").structured("s", "u", Critique)
    assert models.kwargs["config"].thinking_config.thinking_level == "MINIMAL"

    GeminiLLM(client=FakeClient(models), thinking="default").structured("s", "u", Critique)
    assert models.kwargs["config"].thinking_config is None


def test_model_without_thinking_level_support_retries_without_it():
    from google.genai import errors

    class RejectThinking(FakeModels):
        def generate_content(self, **kwargs):
            if kwargs["config"].thinking_config is not None:
                raise errors.ClientError(400, {"error": {"code": 400, "message": "Thinking level is not supported", "status": "INVALID_ARGUMENT"}})
            return super().generate_content(**kwargs)

    models = RejectThinking(json.dumps(CRITIQUE))
    llm = GeminiLLM(model="old-model", client=FakeClient(models), fallback_models=[], notify=lambda _m: None)
    assert llm.structured("s", "u", Critique).scores[0].score == 4
    assert llm.structured("s", "u", Critique).scores[0].score == 4  # 記住這個模型不支援，之後直接不送

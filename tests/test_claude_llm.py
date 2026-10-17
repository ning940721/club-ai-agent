"""Claude 版本的 LLM：用假的用戶端檢查送出的參數與錯誤處理，不會真的呼叫 API。"""

from types import SimpleNamespace

import pytest

from club_agent.llm import ClaudeLLM, LLMError
from club_agent.schemas import MeetingAnswer

ANSWER = MeetingAnswer(found=True, answer="週日 21:00", sources=[])


class FakeMessages:
    def __init__(self, response=None, error=None):
        self.response, self.error, self.calls = response, error, []

    def parse(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return self.response


def fake_client(response=None, error=None):
    messages = FakeMessages(response, error)
    return SimpleNamespace(beta=SimpleNamespace(messages=messages)), messages


def ok(parsed=ANSWER, stop_reason="end_turn"):
    return SimpleNamespace(stop_reason=stop_reason, parsed_output=parsed, stop_details=None)


def test_request_parameters(monkeypatch):
    monkeypatch.delenv("CLUB_AGENT_MODEL", raising=False)
    monkeypatch.delenv("CLUB_AGENT_EFFORT", raising=False)
    client, messages = fake_client(ok())
    llm = ClaudeLLM(client=client)
    assert llm.structured("系統", "問題", MeetingAnswer) == ANSWER
    call = messages.calls[0]
    assert call["model"] == "claude-opus-5-5" and call["output_format"] is MeetingAnswer
    assert call["output_config"] == {"effort": "medium"} and call["fallbacks"] == "default"
    assert call["betas"] == ["server-side-fallback-2026-07-01"] and "thinking" not in call
    assert call["system"] == "系統" and call["messages"] == [{"role": "user", "content": "問題"}]

    ClaudeLLM(model="claude-sonnet-5-5", effort="low", client=client).structured("s", "u", MeetingAnswer)
    assert messages.calls[1]["model"] == "claude-sonnet-5-5" and messages.calls[1]["output_config"] == {"effort": "low"}


@pytest.mark.parametrize("stop_reason, text", [("refusal", "不適合回答"), ("max_tokens", "太長被截斷")])
def test_stop_reasons(stop_reason, text):
    client, _ = fake_client(ok(stop_reason=stop_reason))
    with pytest.raises(LLMError, match=text):
        ClaudeLLM(client=client).structured("s", "u", MeetingAnswer)


def _api_error(cls, status, message):
    import anthropic  # noqa: F401
    import httpx2

    request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    return cls(message, response=httpx2.Response(status, request=request), body=None)


def test_error_messages_in_chinese():
    import anthropic

    cases = [
        (_api_error(anthropic.AuthenticationError, 401, "invalid x-api-key"), "金鑰無效"),
        (_api_error(anthropic.RateLimitError, 429, "rate limited"), "速率上限"),
        (_api_error(anthropic.BadRequestError, 400, "Your credit balance is too low"), "餘額不足"),
        (_api_error(anthropic.InternalServerError, 500, "boom"), "忙碌"),
    ]
    for error, text in cases:
        client, _ = fake_client(error=error)
        with pytest.raises(LLMError, match=text):
            ClaudeLLM(client=client).structured("s", "u", MeetingAnswer)

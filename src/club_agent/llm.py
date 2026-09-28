"""LLM 呼叫層。

`LLM` 是 Agent 依賴的最小介面：給定 system prompt、使用者訊息與輸出格式，
回傳驗證過的 Pydantic 物件。`ClaudeLLM` 以 Anthropic Claude API 實作；
測試時可替換為假物件，無需 API 金鑰。
"""

from __future__ import annotations

import os
from typing import Protocol, TypeVar

import anthropic
from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)

DEFAULT_MODEL = "claude-opus-5"


class LLMError(RuntimeError):
    pass


class LLM(Protocol):
    def structured(self, system: str, user: str, output_type: type[T]) -> T: ...


class ClaudeLLM:
    """以 Claude 結構化輸出（Structured Outputs）產生符合 schema 的結果。

    - 使用 adaptive thinking，讓模型自行決定推理深度。
    - 啟用伺服器端 refusal fallback：若請求被安全分類器拒絕，
      API 會自動改由備援模型重跑，避免流程中斷。
    """

    def __init__(
        self,
        model: str | None = None,
        max_tokens: int = 16000,
        effort: str = "high",
        client: anthropic.Anthropic | None = None,
    ):
        self.model = model or os.environ.get("CLUB_AGENT_MODEL", DEFAULT_MODEL)
        self.max_tokens = max_tokens
        self.effort = effort
        self.client = client or anthropic.Anthropic()

    def structured(self, system: str, user: str, output_type: type[T]) -> T:
        response = self.client.beta.messages.parse(
            model=self.model,
            max_tokens=self.max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
            thinking={"type": "adaptive"},
            output_config={"effort": self.effort},
            output_format=output_type,
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        )
        if response.stop_reason == "refusal":
            raise LLMError(f"模型拒絕回應：{response.stop_details}")
        if response.stop_reason == "max_tokens":
            raise LLMError("輸出超過 max_tokens 上限，請調高 max_tokens 或縮小需求範圍")
        if response.parsed_output is None:
            raise LLMError(f"無法解析模型輸出（stop_reason={response.stop_reason}）")
        return response.parsed_output

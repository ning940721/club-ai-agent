"""LLM 呼叫層。

`LLM` 是 Agent 依賴的最小介面：給定 system prompt、使用者訊息與輸出格式，
回傳驗證過的 Pydantic 物件。目前支援兩個模型供應商，以 `create_llm()` 切換：

- `gemini`（預設）：Google Gemini API，金鑰放在 GEMINI_API_KEY 或 GOOGLE_API_KEY
- `claude`：Anthropic Claude API，金鑰放在 ANTHROPIC_API_KEY

也可用環境變數 CLUB_AGENT_PROVIDER 指定供應商、CLUB_AGENT_MODEL 指定模型。
測試時可替換為假物件，無需 API 金鑰。
"""

from __future__ import annotations

import os
from typing import Protocol, TypeVar

from pydantic import BaseModel, ValidationError

T = TypeVar("T", bound=BaseModel)

DEFAULT_PROVIDER = "gemini"
DEFAULT_MODELS = {
    "gemini": "gemini-flash-latest",
    "claude": "claude-opus-5",
}


class LLMError(RuntimeError):
    pass


class LLM(Protocol):
    def structured(self, system: str, user: str, output_type: type[T]) -> T: ...


def inline_json_schema(model: type[BaseModel]) -> dict:
    """展開 Pydantic 產生的 $ref／$defs，產生不含參照的獨立 JSON Schema。"""
    schema = model.model_json_schema()
    defs = schema.pop("$defs", {})

    def resolve(node):
        if isinstance(node, dict):
            if "$ref" in node:
                return resolve(defs[node["$ref"].split("/")[-1]])
            return {k: resolve(v) for k, v in node.items()}
        if isinstance(node, list):
            return [resolve(v) for v in node]
        return node

    return resolve(schema)


def _model_from_env(provider: str, model: str | None) -> str:
    return model or os.environ.get("CLUB_AGENT_MODEL") or DEFAULT_MODELS[provider]


class GeminiLLM:
    """以 Gemini 的 JSON Schema 結構化輸出產生符合 schema 的結果。"""

    def __init__(self, model: str | None = None, max_output_tokens: int = 16000, client=None):
        from google import genai

        self.model = _model_from_env("gemini", model)
        self.max_output_tokens = max_output_tokens
        self.client = client or genai.Client()

    def structured(self, system: str, user: str, output_type: type[T]) -> T:
        from google.genai import types

        response = self.client.models.generate_content(
            model=self.model,
            contents=user,
            config=types.GenerateContentConfig(
                system_instruction=system,
                max_output_tokens=self.max_output_tokens,
                response_mime_type="application/json",
                response_json_schema=inline_json_schema(output_type),
                automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
            ),
        )
        candidate = response.candidates[0] if response.candidates else None
        finish = candidate.finish_reason if candidate else None
        if finish == types.FinishReason.MAX_TOKENS:
            raise LLMError("輸出超過 max_output_tokens 上限，請調高上限或縮小需求範圍")
        if not response.text:
            feedback = response.prompt_feedback.block_reason if response.prompt_feedback else None
            raise LLMError(f"模型沒有回傳內容（finish_reason={finish}, block_reason={feedback}）")
        try:
            return output_type.model_validate_json(response.text)
        except ValidationError as e:
            raise LLMError(f"模型輸出不符合格式：{e}") from e


class ClaudeLLM:
    """以 Claude 結構化輸出（Structured Outputs）產生符合 schema 的結果。

    - 使用 adaptive thinking，讓模型自行決定推理深度。
    - 啟用伺服器端 refusal fallback：若請求被安全分類器拒絕，
      API 會自動改由備援模型重跑，避免流程中斷。
    """

    def __init__(self, model: str | None = None, max_tokens: int = 16000, effort: str = "high", client=None):
        import anthropic

        self.model = _model_from_env("claude", model)
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


PROVIDERS = {"gemini": GeminiLLM, "claude": ClaudeLLM}


def create_llm(provider: str | None = None, model: str | None = None) -> LLM:
    name = (provider or os.environ.get("CLUB_AGENT_PROVIDER") or DEFAULT_PROVIDER).lower()
    try:
        cls = PROVIDERS[name]
    except KeyError:
        raise ValueError(f"未知的模型供應商：{name}（可用：{', '.join(PROVIDERS)}）") from None
    try:
        return cls(model=model)
    except ImportError as e:
        raise LLMError(f"尚未安裝 {name} 所需套件，請執行：pip install -e \".[{name}]\"") from e

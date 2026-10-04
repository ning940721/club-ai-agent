"""各頁面共用的狀態與工具：目前登入的社團、部門設定、AI 呼叫與紀錄儲存。"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Any, Callable

import streamlit as st

from ..departments import ClubSettings, Department, get_department
from ..llm import GeminiLLM, LLMError
from ..schemas import ClubProfile
from ..store import ClubStore, Record


def demote_headings(markdown: str, levels: int = 2) -> str:
    """把標題降級，放在可展開區塊裡時不會比頁面標題還大。"""
    return re.sub(r"^(#{1,6}) ", lambda m: "#" * min(6, len(m.group(1)) + levels) + " ", markdown, flags=re.MULTILINE)


@dataclass
class AppContext:
    store: ClubStore
    club_id: str
    club: ClubProfile
    settings: ClubSettings
    dept_key: str
    api_key: str | None
    model: str | None
    max_runs: int
    thinking: str | None = None

    @property
    def dept(self) -> Department:
        return get_department(self.dept_key)

    @property
    def dept_name(self) -> str:
        return self.settings.name(self.dept_key)

    def make_llm(self, status) -> GeminiLLM:
        from google import genai

        return GeminiLLM(model=self.model, client=genai.Client(api_key=self.api_key), notify=status.write, thinking=self.thinking)

    def check_quota(self) -> bool:
        used = st.session_state.get("runs", 0)
        if used >= self.max_runs:
            st.warning(f"本次使用已達 {self.max_runs} 次上限，請重新整理頁面或稍後再試。")
            return False
        st.session_state.runs = used + 1
        return True

    def run_ai(self, label: str, fn: Callable[[GeminiLLM, Any], Any], done_label: str = "完成") -> Any | None:
        """呼叫 AI 並顯示進度；失敗時顯示錯誤並回傳 None。fn 會收到 (llm, status)。"""
        if not self.api_key:
            st.error("尚未設定 GEMINI_API_KEY，請管理者到 Secrets 設定。")
            return None
        if not self.check_quota():
            return None
        started = time.monotonic()
        with st.status(label, expanded=True) as status:
            try:
                result = fn(self.make_llm(status), status)
                elapsed = time.monotonic() - started
                status.update(label=f"{done_label}（花了 {elapsed:.0f} 秒）", state="complete", expanded=False)
                return result
            except LLMError as e:
                status.update(label=f"失敗（花了 {time.monotonic() - started:.0f} 秒）", state="error")
                st.error(str(e))
                return None

    def save_record(self, kind: str, title: str, summary: str, markdown: str, department: str | None = None) -> None:
        self.store.add_record(
            self.club_id,
            Record(department=department or self.dept_key, kind=kind, title=title, summary=summary, markdown=markdown),
        )

    def show_record(self, r: Record, where: str) -> None:
        label = self.settings.label(r.department)
        when = r.created_at[:16].replace("T", " ")
        title = f"查看完整內容（{label}｜{when}）" if where == "feed" else f"{label}｜{when}｜{r.title}"
        with st.expander(title):
            st.markdown(demote_headings(r.markdown))
            st.download_button("下載（.md）", r.markdown, file_name=f"{r.title[:20]}.md", key=f"dl_{where}_{r.id}")

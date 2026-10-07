"""各頁面共用的狀態與工具：目前登入的社團、部門設定、AI 呼叫與紀錄儲存。"""

from __future__ import annotations

import re
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable

import streamlit as st
from streamlit.runtime.scriptrunner import add_script_run_ctx, get_script_run_ctx

from ..departments import ClubSettings, Department, get_department
from ..export import pdf_available, to_docx, to_pdf
from ..llm import GeminiLLM, LLMError
from ..schemas import ClubProfile
from ..store import ClubStore, Record


DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def safe_filename(name: str) -> str:
    return re.sub(r'[\\/:*?"<>|\s]+', "_", name).strip("_")[:40] or "報告"


def download_buttons(markdown: str, name: str, key: str) -> None:
    """下載 Word／PDF。檔案在按下按鈕時才產生，不拖慢頁面。"""
    filename = safe_filename(name)
    c1, c2, _ = st.columns([1, 1, 3])
    c1.download_button(
        "下載 Word", lambda: to_docx(markdown), file_name=f"{filename}.docx", mime=DOCX_MIME,
        key=f"docx_{key}", icon=":material/description:", on_click="ignore", width="stretch",
    )
    has_font = pdf_available()
    c2.download_button(
        "下載 PDF", (lambda: to_pdf(markdown)) if has_font else b"", file_name=f"{filename}.pdf", mime="application/pdf",
        key=f"pdf_{key}", icon=":material/picture_as_pdf:", on_click="ignore", width="stretch", disabled=not has_font,
        help=None if has_font else "這台主機沒有中文字型，暫時無法產生 PDF，請下載 Word 檔",
    )


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

    def make_llm(self, status, thinking: str | None = None) -> GeminiLLM:
        from google import genai

        script_ctx = get_script_run_ctx()

        def notify(message: str) -> None:
            # 分段摘要會在背景執行緒呼叫 AI，需要綁定頁面才能顯示進度訊息
            add_script_run_ctx(threading.current_thread(), script_ctx)
            status.write(message)

        return GeminiLLM(
            model=self.model, client=genai.Client(api_key=self.api_key), notify=notify, thinking=thinking or self.thinking
        )

    def check_quota(self) -> bool:
        used = st.session_state.get("runs", 0)
        if used >= self.max_runs:
            st.warning(f"本次使用已達 {self.max_runs} 次上限，請重新整理頁面或稍後再試。")
            return False
        st.session_state.runs = used + 1
        return True

    def run_ai(
        self, label: str, fn: Callable[[GeminiLLM, Any], Any], done_label: str = "完成", thinking: str | None = None
    ) -> Any | None:
        """呼叫 AI 並顯示進度；失敗時顯示錯誤並回傳 None。fn 會收到 (llm, status)。

        thinking：這項工作的思考程度（minimal 最快）；不指定時用網站設定（預設 low）。
        """
        if not self.api_key:
            st.error("尚未設定 GEMINI_API_KEY，請管理者到 Secrets 設定。")
            return None
        if not self.check_quota():
            return None
        started = time.monotonic()
        with st.status(label, expanded=True) as status:
            try:
                result = fn(self.make_llm(status, thinking), status)
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

    # 分享給其他部門：幹部可以決定這次的結果要不要讓其他部門看到

    def share_toggle(self, key: str) -> bool:
        return st.toggle("完成後分享給其他部門", value=True, key=f"share_{key}", help="分享的內容會出現在「AI Agent 問答」，其他部門看得到，AI 也能用來回答問題；關閉後只有你看得到，之後仍可按「分享給其他部門」")

    def keep_result(
        self, key: str, kind: str, title: str, summary: str, markdown: str, share: bool, department: str | None = None
    ) -> None:
        """記住這次的結果；share 為 True 時直接分享，否則在結果下方顯示分享按鈕（見 share_controls）。"""
        item = {"kind": kind, "title": title, "summary": summary, "markdown": markdown, "department": department, "shared": False}
        st.session_state[f"result_{key}"] = item
        if share:
            self._share(item)

    def _share(self, item: dict) -> None:
        self.save_record(item["kind"], item["title"], item["summary"], item["markdown"], item["department"])
        item["shared"] = True

    def share_controls(self, key: str) -> None:
        item = st.session_state.get(f"result_{key}")
        if not item:
            return
        if item["shared"]:
            st.caption("已分享，其他部門可以在「AI Agent 問答」查看。")
        elif st.button("分享給其他部門", key=f"share_btn_{key}", icon=":material/share:"):
            self._share(item)
            st.rerun()

    def show_record(self, r: Record, where: str) -> None:
        label = self.settings.label(r.department)
        when = r.created_at[:16].replace("T", " ")
        title = f"查看完整內容（{label}｜{when}）" if where == "feed" else f"{label}｜{when}｜{r.title}"
        with st.expander(title):
            st.markdown(demote_headings(r.markdown))
            download_buttons(r.markdown, r.title[:20], f"{where}_{r.id}")

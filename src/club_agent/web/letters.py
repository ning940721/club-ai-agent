"""信件工作台（講者、公關共用）：選擇信件類型 → AI 撰寫 → 修改 → 存紀錄／用郵件程式開啟／下載。"""

from __future__ import annotations

from typing import Callable
from urllib.parse import quote

import streamlit as st

from ..agents import LetterWriter
from ..speakers import SavedMessage
from .context import AppContext, download_buttons


def letter_workbench(
    ctx: AppContext,
    key: str,
    kinds: dict[str, str],
    facts: str,
    contact: str,
    sender: str,
    on_save: Callable[[str, SavedMessage], None],
    notice_kinds: tuple[str, ...] = (),
    download_name: str = "",
    department: str | None = None,
) -> None:
    """kinds：信件類型 → 寫作指引。notice_kinds 是給社員的通知（不寄信，可分享給其他部門）。
    on_save(kind, message) 負責存檔並重新整理頁面。"""
    c1, c2 = st.columns([2, 3])
    kind = c1.selectbox("要寫什麼", list(kinds), key=f"{key}_kind")
    c2.caption(kinds[kind])
    extra = st.text_input("補充要求（選填）", placeholder="例：對方是學長，語氣可以輕鬆一點；報名連結是 forms.gle/xxxx", key=f"{key}_extra")
    if st.button("產生", type="primary", key=f"{key}_go"):
        letter = ctx.run_ai(f"撰寫{kind}中…", lambda llm, _s: LetterWriter(llm).run(ctx.club, sender, kind, kinds[kind], facts, extra))
        if letter:
            st.session_state[f"{key}_draft"] = (kind, letter)
            st.session_state[f"{key}_version"] = st.session_state.get(f"{key}_version", 0) + 1

    draft = st.session_state.get(f"{key}_draft")
    if not draft or draft[0] != kind:
        return
    _, letter = draft
    v = st.session_state.get(f"{key}_version", 0)
    st.divider()
    subject = st.text_input("主旨", value=letter.subject, key=f"{key}_subject_{v}")
    body = st.text_area("內文（可以直接修改）", value=letter.body, height=320, key=f"{key}_body_{v}")
    short = st.text_area("LINE／簡訊短版", value=letter.short_text, height=100, key=f"{key}_short_{v}")
    c1, c2 = st.columns(2)
    if c1.button("存到往來紀錄", key=f"{key}_save_{v}"):
        on_save(kind, SavedMessage(kind=kind, subject=subject, body=body, short_text=short))
    is_notice = kind in notice_kinds
    if not is_notice:
        if "@" in contact:
            email = contact.split()[0] if " " in contact else contact
            c2.link_button("用郵件程式開啟", f"mailto:{email}?subject={quote(subject)}&body={quote(body[:1500])}", icon=":material/mail:")
        else:
            c2.caption("填寫對方的 Email 後，可以直接用郵件程式開啟。")
    download_buttons(f"# {subject}\n\n{body}\n\n---\n\n**短版**\n\n{short}\n", f"{kind}_{download_name}", f"{key}_dl_{v}")
    if is_notice:
        # 分享的是修改後的最新內容；重新產生時重新開始
        result_key = f"{key}_notice"
        item = st.session_state.get(f"result_{result_key}")
        if item is None or item.get("version") != v:
            ctx.keep_result(result_key, "notice", subject, short[:150], "", share=False, department=department)
            item = st.session_state[f"result_{result_key}"]
            item["version"] = v
        if not item["shared"]:
            item.update(title=subject, markdown=f"# {subject}\n\n{body}\n", summary=short[:150])
        ctx.share_controls(result_key)

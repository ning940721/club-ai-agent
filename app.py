"""校園社團 AI 營運顧問｜網頁版（Streamlit）

本機執行：streamlit run app.py（Windows 可雙擊「啟動網頁.bat」）
部署方式請見 docs/deploy.md。API 金鑰等設定放在 Streamlit 的 Secrets，不寫進程式。

這個檔案只負責登入、建立帳號與頁面切換；各頁面內容在 src/club_agent/web/。
"""

from __future__ import annotations

import os
import sys
from typing import Callable
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT / "src"))

import streamlit as st  # noqa: E402

from club_agent.departments import (  # noqa: E402
    FEATURE_EVENTS,
    FEATURE_FINANCE,
    FEATURE_MARKETING,
    FEATURE_MEETINGS,
    FEATURE_PR,
    FEATURE_PRESIDENT,
    FEATURE_SPEAKERS,
    ClubSettings,
)
from club_agent.store import LocalClubStore, StoreError  # noqa: E402
from club_agent.web.calendar_pages import calendar_page  # noqa: E402
from club_agent.web.event_pages import event_tabs  # noqa: E402
from club_agent.web.finance_pages import finance_page, finance_tabs, reimburse_page  # noqa: E402
from club_agent.web.common_pages import (  # noqa: E402
    advisor_page,
    department_settings_form,
    feed_page,
    help_page,
    profile_form,
    settings_page,
    tasks_page,
)
from club_agent.web.context import AppContext  # noqa: E402
from club_agent.web.style import inject_css, page_header, sidebar_brand  # noqa: E402
from club_agent.web.marketing_pages import diagnosis_page, monthly_page  # noqa: E402
from club_agent.web.meeting_pages import meeting_tabs  # noqa: E402
from club_agent.web.pr_pages import pr_tabs  # noqa: E402
from club_agent.web.president_pages import president_page  # noqa: E402
from club_agent.web.speaker_pages import speaker_tabs  # noqa: E402


st.set_page_config(page_title="社團營運平台", page_icon=":material/groups:", layout="wide")
inject_css()


def secret(name: str, default: str | None = None) -> str | None:
    try:
        value = st.secrets.get(name)
    except Exception:  # 本機沒有 secrets.toml 時
        value = None
    return value or os.environ.get(name, default)


API_KEY = secret("GEMINI_API_KEY") or secret("GOOGLE_API_KEY")
SIGNUP_CODE = secret("SIGNUP_CODE")  # 設定後，建立新社團帳號需要輸入這組邀請碼
store = LocalClubStore(secret("CLUB_AGENT_DATA_DIR", str(ROOT / "data")))


# ---------------------------------------------------------------------------
# 登入／建立社團帳號
# ---------------------------------------------------------------------------

if "club_id" not in st.session_state:
    _, center, _ = st.columns([1, 2, 1])
    with center:
        page_header("社團營運平台", "AI 營運顧問")
        st.caption("每個社團一組帳號，登入後選擇你的部門，就能使用該部門的顧問與工具。")
        tab_login, tab_signup = st.tabs(["登入", "建立社團帳號"])

        with tab_login:
            with st.form("login"):
                account = st.text_input("社團帳號")
                password = st.text_input("密碼", type="password")
                if st.form_submit_button("登入", type="primary"):
                    club_id = store.authenticate(account, password)
                    if club_id:
                        st.session_state.club_id = club_id
                        st.rerun()
                    st.error("帳號或密碼錯誤")

        with tab_signup:
            st.caption("第一次使用請由社長或負責人建立帳號，之後把帳號密碼分享給各部門幹部。")
            code = st.text_input("邀請碼", type="password", help="請向系統管理者索取") if SIGNUP_CODE else None
            new_account = st.text_input("設定社團帳號（英文或數字，例：ntu-photo）", key="su_account")
            new_pw = st.text_input("設定密碼（至少 6 個字元）", type="password", key="su_pw")
            new_pw2 = st.text_input("再輸入一次密碼", type="password", key="su_pw2")
            st.markdown("**社團有哪些部門、各自負責什麼？**（之後可在「社團設定」修改）")
            club_settings = department_settings_form(ClubSettings.default(), prefix="su")
            st.markdown("**社團資料**（AI 會依這些資料給出貼合社團的建議）")
            profile = profile_form("su")
            if st.button("建立帳號並登入", type="primary"):
                if SIGNUP_CODE and code != SIGNUP_CODE:
                    st.error("邀請碼錯誤")
                elif new_pw != new_pw2:
                    st.error("兩次輸入的密碼不一樣")
                elif not club_settings.enabled_keys():
                    st.error("請至少選擇一個部門")
                elif profile is None:
                    st.error("請填寫社團名稱、定位與目標受眾")
                else:
                    try:
                        st.session_state.club_id = store.create_club(new_account, new_pw, profile, club_settings)
                        st.rerun()
                    except StoreError as e:
                        st.error(str(e))
    st.stop()


# ---------------------------------------------------------------------------
# 登入後
# ---------------------------------------------------------------------------

club_id: str = st.session_state.club_id
club = store.get_profile(club_id)
settings = store.get_settings(club_id)
enabled = settings.enabled_keys()
if st.session_state.get("dept") not in enabled:
    st.session_state.dept = enabled[0]

# 側邊欄的頁面：幹部共用的功能，以及不常用的社團設定、使用說明。點選後主畫面改顯示該頁，選部門或按「返回」回到部門功能
SHARED_PAGES = {
    "tasks": ("待辦與進度", ":material/checklist:", tasks_page),
    "feed": ("AI Agent 問答", ":material/smart_toy:", feed_page),
    "calendar": ("行事曆", ":material/calendar_month:", calendar_page),
    "reimburse": ("報帳申請", ":material/receipt_long:", reimburse_page),
}
OTHER_PAGES = {
    "settings": ("社團設定", ":material/settings:", settings_page),
    "help": ("使用說明", ":material/help:", lambda _ctx: help_page()),
}
SIDE_PAGES = {**SHARED_PAGES, **OTHER_PAGES}


def open_side_page(name: str | None) -> None:
    st.session_state.side_page = name


def side_buttons(group: dict) -> None:
    current = st.session_state.get("side_page")
    for name, (label, icon, _) in group.items():
        st.button(label, icon=icon, type="secondary" if name == current else "tertiary", key=f"side_{name}",
                  on_click=open_side_page, args=(name,), width="stretch")


with st.sidebar:
    sidebar_brand(club.name)
    dept_key = st.selectbox("我的部門", enabled, format_func=settings.label, key="dept", on_change=open_side_page, args=(None,))
    usage_slot = st.empty()  # 在頁面最後更新，才會算到這次按下的按鈕
    st.divider()
    st.caption("幹部共用")
    side_buttons(SHARED_PAGES)
    st.divider()
    side_buttons(OTHER_PAGES)
    if st.button("登出", icon=":material/logout:", type="tertiary", width="stretch"):
        st.session_state.clear()
        st.rerun()

ctx = AppContext(
    store=store,
    club_id=club_id,
    club=club,
    settings=settings,
    dept_key=dept_key,
    api_key=API_KEY,
    model=secret("GEMINI_MODEL"),
    max_runs=int(secret("MAX_RUNS_PER_SESSION", "20")),
    thinking=secret("GEMINI_THINKING"),
)
features = settings.features(dept_key)  # 社團自訂的分工

if (side_page := st.session_state.get("side_page")) in SIDE_PAGES:
    label, _, render = SIDE_PAGES[side_page]
    page_header(label, club.name)
    st.button("返回部門功能", icon=":material/arrow_back:", on_click=open_side_page, args=(None,))
    render(ctx)
    usage_slot.caption(f"本次已使用 {st.session_state.get('runs', 0)} / {ctx.max_runs} 次")
    st.stop()

page_header(ctx.dept_name, club.name, beta=ctx.dept.beta)
if not API_KEY:
    st.error("網站尚未設定 GEMINI_API_KEY，請管理者到 Secrets 設定（見 docs/deploy.md）。")

# 各部門的功能直接列在上方分頁；部門顧問放最後。待辦、AI Agent 問答、行事曆、報帳在側邊欄「幹部共用」。
# 有些部門的功能需要先在分頁上方選擇對象（例如活動），所以先取得分頁清單（會先畫出上方的選單），再建立分頁。
# 每個功能模組對應的分頁；部門負責哪些模組由社團設定決定（社團可以自訂分工）
MODULE_TABS: dict[str, Callable[[], list[tuple[str, Callable[[], None]]]]] = {
    FEATURE_PRESIDENT: lambda: [("社團總覽", lambda: president_page(ctx))],
    FEATURE_MEETINGS: lambda: meeting_tabs(ctx),
    FEATURE_MARKETING: lambda: [("社群數據診斷", lambda: diagnosis_page(ctx)), ("月報與趨勢", lambda: monthly_page(ctx))],
    FEATURE_EVENTS: lambda: event_tabs(ctx),
    FEATURE_PR: lambda: pr_tabs(ctx),
    FEATURE_SPEAKERS: lambda: speaker_tabs(ctx),
    # 財務是部門唯一的功能時展開成多個分頁；部門還有其他功能（例如社長）時收在一個「財務管理」分頁
    FEATURE_FINANCE: lambda: finance_tabs(ctx) if len(features) == 1 else [("財務管理", lambda: finance_page(ctx))],
}
pages: list[tuple[str, Callable[[], None]]] = []
for feature in features:
    if feature in MODULE_TABS:
        pages += MODULE_TABS[feature]()
pages.append(("部門顧問", lambda: advisor_page(ctx)))

for tab, (_, render) in zip(st.tabs([name for name, _ in pages]), pages):
    with tab:
        render()

usage_slot.caption(f"本次已使用 {st.session_state.get('runs', 0)} / {ctx.max_runs} 次")

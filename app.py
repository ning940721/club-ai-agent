"""校園社團 AI 營運顧問｜網頁版（Streamlit）

本機執行：streamlit run app.py（Windows 可雙擊「啟動網頁.bat」）
部署方式請見 docs/deploy.md。API 金鑰等設定放在 Streamlit 的 Secrets，不寫進程式。

這個檔案只負責登入、建立帳號與頁面切換；各頁面內容在 src/club_agent/web/。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT / "src"))

import streamlit as st  # noqa: E402

from club_agent.departments import (  # noqa: E402
    DEFAULT_ENABLED,
    DEPARTMENTS,
    FEATURE_MARKETING,
    FEATURE_MEETINGS,
    FEATURE_PRESIDENT,
    ClubSettings,
)
from club_agent.store import LocalClubStore, StoreError  # noqa: E402
from club_agent.web.common_pages import advisor_page, feed_page, help_page, profile_form, settings_page, tasks_page  # noqa: E402
from club_agent.web.context import AppContext  # noqa: E402
from club_agent.web.style import inject_css, page_header, sidebar_brand  # noqa: E402
from club_agent.web.marketing_pages import campaign_page, diagnosis_page  # noqa: E402
from club_agent.web.meeting_pages import meetings_page  # noqa: E402
from club_agent.web.president_pages import president_page  # noqa: E402

CSV_COLUMNS = ["date", "time", "platform", "post_type", "topic", "reach", "likes", "comments", "shares", "saves", "followers", "caption"]

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
            st.markdown("**社團有哪些部門？**（之後可在「社團設定」修改、改名、填寫部門細節）")
            chosen_depts = st.multiselect(
                "部門",
                list(DEPARTMENTS),
                default=list(DEFAULT_ENABLED),
                format_func=lambda k: DEPARTMENTS[k].label,
                key="su_depts",
            )
            st.markdown("**社團資料**（AI 會依這些資料給出貼合社團的建議）")
            profile = profile_form("su")
            if st.button("建立帳號並登入", type="primary"):
                if SIGNUP_CODE and code != SIGNUP_CODE:
                    st.error("邀請碼錯誤")
                elif new_pw != new_pw2:
                    st.error("兩次輸入的密碼不一樣")
                elif not chosen_depts:
                    st.error("請至少選擇一個部門")
                elif profile is None:
                    st.error("請填寫社團名稱、定位與目標受眾")
                else:
                    try:
                        st.session_state.club_id = store.create_club(new_account, new_pw, profile, ClubSettings.default(chosen_depts))
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

# 社團設定與使用說明不常用，放在側邊欄下方；點選後主畫面改顯示該頁，選部門或按「返回」回到部門功能
SIDE_PAGES = {"settings": ("社團設定", ":material/settings:"), "help": ("使用說明", ":material/help:")}


def open_side_page(name: str | None) -> None:
    st.session_state.side_page = name


with st.sidebar:
    sidebar_brand(club.name)
    dept_key = st.selectbox("我的部門", enabled, format_func=settings.label, key="dept", on_change=open_side_page, args=(None,))
    usage_slot = st.empty()  # 在頁面最後更新，才會算到這次按下的按鈕
    st.divider()
    for name, (label, icon) in SIDE_PAGES.items():
        st.button(label, icon=icon, type="tertiary", key=f"side_{name}", on_click=open_side_page, args=(name,))
    if st.button("登出", icon=":material/logout:", type="tertiary"):
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
features = DEPARTMENTS[dept_key].features

if side_page := st.session_state.get("side_page"):
    page_header(SIDE_PAGES[side_page][0], club.name)
    st.button("返回部門功能", icon=":material/arrow_back:", on_click=open_side_page, args=(None,))
    if side_page == "settings":
        settings_page(ctx)
    else:
        help_page(CSV_COLUMNS)
    usage_slot.caption(f"本次已使用 {st.session_state.get('runs', 0)} / {ctx.max_runs} 次")
    st.stop()

page_header(ctx.dept_name, club.name, beta=DEPARTMENTS[dept_key].beta)
if not API_KEY:
    st.error("網站尚未設定 GEMINI_API_KEY，請管理者到 Secrets 設定（見 docs/deploy.md）。")

pages: list[tuple[str, callable]] = []
if FEATURE_PRESIDENT in features:
    pages.append(("社團總覽", president_page))
if FEATURE_MEETINGS in features:
    pages.append(("會議記錄", meetings_page))
if FEATURE_MARKETING in features:
    pages += [("社群數據診斷", diagnosis_page), ("活動宣傳企劃", campaign_page)]
if FEATURE_PRESIDENT not in features:
    pages.append(("待辦與進度", tasks_page))
pages += [("部門顧問", advisor_page), ("社團動態", feed_page)]

for tab, (_, render) in zip(st.tabs([name for name, _ in pages]), pages):
    with tab:
        render(ctx)

usage_slot.caption(f"本次已使用 {st.session_state.get('runs', 0)} / {ctx.max_runs} 次")

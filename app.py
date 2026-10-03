"""校園社團 AI 營運顧問｜網頁版（Streamlit）

本機執行：streamlit run app.py
部署方式請見 docs/deploy.md。API 金鑰等設定放在 Streamlit 的 Secrets，不寫進程式。

使用流程：社團帳號登入（第一次先建立帳號並填社團資料）→ 選擇自己的部門 →
向部門顧問提問、取得建議；所有部門的紀錄都會出現在「社團動態」，彼此看得到。
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT / "src"))

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

from club_agent.agents import DepartmentAdvisor  # noqa: E402
from club_agent.departments import DEPARTMENTS, department_retriever  # noqa: E402
from club_agent.llm import GeminiLLM, LLMError  # noqa: E402
from club_agent.metrics import decode_csv_bytes, engagement_rate, parse_posts_csv, summarize  # noqa: E402
from club_agent.report import advice_markdown, campaign_markdown, diagnosis_markdown  # noqa: E402
from club_agent.retriever import BM25Retriever  # noqa: E402
from club_agent.schemas import ClubProfile  # noqa: E402
from club_agent.store import LocalClubStore, Record, StoreError, activity_digest  # noqa: E402
from club_agent.workflow import MarketingWorkflow  # noqa: E402

EXAMPLES = ROOT / "examples"
CSV_COLUMNS = ["date", "time", "platform", "post_type", "topic", "reach", "likes", "comments", "shares", "saves", "followers", "caption"]
PLATFORMS = ["Instagram", "Facebook", "Dcard", "Threads"]

st.set_page_config(page_title="社團 AI 營運顧問", page_icon="📣", layout="wide")


def secret(name: str, default: str | None = None) -> str | None:
    try:
        value = st.secrets.get(name)
    except Exception:  # 本機沒有 secrets.toml 時
        value = None
    return value or os.environ.get(name, default)


API_KEY = secret("GEMINI_API_KEY") or secret("GOOGLE_API_KEY")
MODEL = secret("GEMINI_MODEL")
MAX_RUNS = int(secret("MAX_RUNS_PER_SESSION", "20"))
SIGNUP_CODE = secret("SIGNUP_CODE")  # 設定後，建立新社團帳號需要輸入這組邀請碼
store = LocalClubStore(secret("CLUB_AGENT_DATA_DIR", str(ROOT / "data")))


@st.cache_resource
def get_marketing_retriever() -> BM25Retriever:
    return BM25Retriever.from_directory()


@st.cache_resource
def get_department_retriever(key: str) -> BM25Retriever:
    return department_retriever(key)


def make_llm(status) -> GeminiLLM:
    from google import genai

    return GeminiLLM(model=MODEL, client=genai.Client(api_key=API_KEY), notify=status.write)


def make_workflow(status, rounds: int = 3) -> MarketingWorkflow:
    return MarketingWorkflow(llm=make_llm(status), retriever=get_marketing_retriever(), max_rounds=rounds, on_progress=status.write)


def check_quota() -> bool:
    used = st.session_state.get("runs", 0)
    if used >= MAX_RUNS:
        st.warning(f"本次使用已達 {MAX_RUNS} 次上限，請重新整理頁面或稍後再試。")
        return False
    st.session_state.runs = used + 1
    return True


def profile_form(prefix: str, profile: ClubProfile | None = None) -> ClubProfile | None:
    """社團資料欄位（建立帳號與社團設定共用），必填欄位不完整時回傳 None。"""
    p = profile
    name = st.text_input("社團名稱＊", value=p.name if p else "", key=f"{prefix}_name")
    category = st.text_input("社團類型", value=p.category if p else "", placeholder="例：學藝性、康樂性、服務性、系學會", key=f"{prefix}_category")
    positioning = st.text_area("社團定位與特色＊", value=p.positioning if p else "", placeholder="例：以街頭攝影與底片攝影為特色，每週社課＋每月外拍", key=f"{prefix}_positioning")
    audience = st.text_area("主要目標受眾＊", value=p.target_audience if p else "", placeholder="例：對攝影有興趣的大一至大三學生，多為初學者", key=f"{prefix}_audience")
    voice = st.text_input("品牌語氣", value=p.brand_voice if p else "", placeholder="例：文青、溫暖、帶點幽默", key=f"{prefix}_voice")
    platforms = st.multiselect("經營平台", PLATFORMS, default=[x for x in (p.platforms if p else ["Instagram", "Facebook"]) if x in PLATFORMS], key=f"{prefix}_platforms")
    budget = st.number_input("每月行銷預算（新台幣）", min_value=0, step=500, value=p.monthly_budget_ntd if p else 0, key=f"{prefix}_budget")
    if not (name.strip() and positioning.strip() and audience.strip()):
        return None
    return ClubProfile(
        name=name.strip(),
        category=category.strip() or "未填寫",
        positioning=positioning.strip(),
        target_audience=audience.strip(),
        brand_voice=voice.strip() or "親切、有活力",
        platforms=platforms or ["Instagram"],
        monthly_budget_ntd=int(budget),
    )


# ---------------------------------------------------------------------------
# 登入／建立社團帳號
# ---------------------------------------------------------------------------

if "club_id" not in st.session_state:
    st.title("📣 社團 AI 營運顧問")
    st.caption("每個社團一組帳號，登入後選擇你的部門，就能向該部門的 AI 顧問提問。")
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
        st.markdown("**社團資料**（AI 會依這些資料給出貼合社團的建議，之後可在「社團設定」修改）")
        profile = profile_form("su")
        if st.button("建立帳號並登入", type="primary"):
            if SIGNUP_CODE and code != SIGNUP_CODE:
                st.error("邀請碼錯誤")
            elif new_pw != new_pw2:
                st.error("兩次輸入的密碼不一樣")
            elif profile is None:
                st.error("請填寫社團名稱、定位與目標受眾")
            else:
                try:
                    st.session_state.club_id = store.create_club(new_account, new_pw, profile)
                    st.rerun()
                except StoreError as e:
                    st.error(str(e))
    st.stop()


# ---------------------------------------------------------------------------
# 登入後
# ---------------------------------------------------------------------------

club_id: str = st.session_state.club_id
club = store.get_profile(club_id)

with st.sidebar:
    st.header(f"🏫 {club.name}")
    dept_key = st.selectbox(
        "我的部門",
        list(DEPARTMENTS),
        format_func=lambda k: DEPARTMENTS[k].label,
        key="dept",
    )
    if st.button("登出", width="stretch"):
        st.session_state.clear()
        st.rerun()
    usage_slot = st.empty()  # 在頁面最後更新，才會算到這次按下的按鈕

dept = DEPARTMENTS[dept_key]

st.title(f"{dept.icon} {dept.name}部門｜{club.name}")
if not API_KEY:
    st.error("網站尚未設定 GEMINI_API_KEY，請管理者到 Secrets 設定（見 docs/deploy.md）。")

tab_names = ["💬 部門顧問"]
if dept_key == "marketing":
    tab_names += ["📊 社群數據診斷", "📝 活動宣傳企劃"]
tab_names += ["🗂️ 社團動態", "⚙️ 社團設定", "📖 使用說明"]
tabs = dict(zip(tab_names, st.tabs(tab_names)))


def save_record(kind: str, title: str, summary: str, markdown: str) -> None:
    store.add_record(club_id, Record(department=dept_key, kind=kind, title=title, summary=summary, markdown=markdown))


def show_record(r: Record, where: str) -> None:
    d = DEPARTMENTS.get(r.department)
    label = f"{d.icon} {d.name}" if d else r.department
    when = r.created_at[:16].replace("T", " ")
    title = f"查看完整內容（{label}｜{when}）" if where == "feed" else f"{label}｜{when}｜{r.title}"
    with st.expander(title):
        st.markdown(r.markdown)
        st.download_button("下載（.md）", r.markdown, file_name=f"{r.title[:20]}.md", key=f"dl_{where}_{r.id}")


# --- 部門顧問 ---------------------------------------------------------------

with tabs["💬 部門顧問"]:
    if dept.beta:
        st.info(f"「{dept.name}」顧問目前為測試版，知識庫仍在擴充中，建議請再自行確認。")
    st.caption("專長：" + "、".join(dept.focus))

    q_key = f"question_{dept_key}"
    st.markdown("**範例問題（點一下帶入）**")
    for i, example in enumerate(dept.example_questions):
        if st.button(example, key=f"ex_{dept_key}_{i}"):
            st.session_state[q_key] = example
    question = st.text_area("你的問題", key=q_key, height=120, placeholder="描述你遇到的狀況，越具體建議越準確")

    ask = st.button("取得建議", type="primary", disabled=not API_KEY)
    if ask and not question.strip():
        st.warning("請先輸入問題")
    elif ask and check_quota():
        with st.status(f"{dept.name}顧問思考中…", expanded=True) as status:
            try:
                activity = activity_digest(store.list_records(club_id, limit=30), exclude_department=dept_key)
                advisor = DepartmentAdvisor(make_llm(status), get_department_retriever(dept_key))
                advice = advisor.run(club, dept, question.strip(), activity)
                md = advice_markdown(dept.name, question.strip(), advice)
                save_record("advice", question.strip()[:60], advice.summary[:150], md)
                st.session_state[f"advice_md_{dept_key}"] = md
                status.update(label="完成，已存入社團動態", state="complete", expanded=False)
            except LLMError as e:
                status.update(label="產生失敗", state="error")
                st.error(str(e))

    if md := st.session_state.get(f"advice_md_{dept_key}"):
        st.divider()
        st.markdown(md)
        st.download_button("下載建議（.md）", md, file_name=f"{dept.name}顧問建議.md")

    recent = store.list_records(club_id, department=dept_key, limit=5)
    if recent:
        st.divider()
        st.markdown(f"**{dept.name}部門最近紀錄**")
        for r in recent:
            show_record(r, "dept")

# --- 行銷專屬工具 -------------------------------------------------------------

if "📊 社群數據診斷" in tabs:
    with tabs["📊 社群數據診斷"]:
        st.subheader("上傳社群數據，找出流量瓶頸")
        col1, col2 = st.columns([3, 1])
        uploaded = col1.file_uploader("貼文數據 CSV（格式見「使用說明」）", type="csv")
        use_example = col2.checkbox("使用範例數據", value=uploaded is None)

        posts = None
        try:
            if uploaded is not None and not use_example:
                posts = parse_posts_csv(decode_csv_bytes(uploaded.getvalue()))
            elif use_example:
                posts = parse_posts_csv((EXAMPLES / "sample_posts.csv").read_text(encoding="utf-8"))
        except Exception as e:  # 欄位或數字格式錯誤
            st.error(f"CSV 讀取失敗，請確認欄位名稱與格式：{e}")

        if posts:
            metrics = summarize(posts)
            df = pd.DataFrame([p.model_dump() for p in posts])
            df["互動率"] = [f"{engagement_rate(p):.2%}" for p in posts]
            st.success(f"已讀取 {len(posts)} 篇貼文（{metrics.date_range[0]} ~ {metrics.date_range[1]}）")
            with st.expander("查看數據與統計摘要"):
                st.dataframe(df, width="stretch", hide_index=True)
                st.text(metrics.to_prompt_text())

            concern = st.text_area("目前的宣傳困擾（選填）", placeholder="例：最近三個月觸及一直掉，不知道該發什麼")
            if st.button("開始診斷", type="primary", disabled=not API_KEY) and check_quota():
                with st.status("AI 顧問分析中…", expanded=True) as status:
                    try:
                        report = make_workflow(status).diagnose(club, metrics, concern)
                        md = diagnosis_markdown(club.name, report)
                        st.session_state.diagnosis = report
                        st.session_state.diagnosis_md = md
                        save_record("diagnosis", "社群數據診斷", report.summary[:150], md)
                        status.update(label="診斷完成，已存入社團動態", state="complete", expanded=False)
                    except LLMError as e:
                        status.update(label="診斷失敗", state="error")
                        st.error(str(e))

        if st.session_state.get("diagnosis_md"):
            st.divider()
            st.markdown(st.session_state.diagnosis_md)
            st.download_button("下載診斷報告（.md）", st.session_state.diagnosis_md, file_name="診斷報告.md")

    with tabs["📝 活動宣傳企劃"]:
        st.subheader("輸入活動資訊，產出多平台宣傳企劃")
        st.caption("不知道的欄位可以留空，AI 會標示【待補】，不會自己編造。")
        c1, c2 = st.columns(2)
        event_name = c1.text_input("活動名稱＊", placeholder="例：跨校社團聯展")
        event_date = c2.text_input("活動日期與時間", placeholder="例：12/20（六）13:00-18:00")
        location = c1.text_input("地點", placeholder="例：學生活動中心 2 樓")
        fee = c2.text_input("費用", placeholder="例：免費入場")
        goal = c1.text_input("宣傳目標", placeholder="例：吸引 300 人參觀、IG 新增 100 位追蹤")
        signup = c2.text_input("報名方式", placeholder="例：IG 主頁連結的 Google 表單")
        extra = st.text_area("其他說明", placeholder="例：有 5 個攝影社團共同參展、現場有底片體驗攤位")

        has_diag = st.session_state.get("diagnosis") is not None
        use_diag = st.checkbox("參考「社群數據診斷」的結果", value=has_diag, disabled=not has_diag)
        rounds = st.slider("最多審查修訂輪數", 1, 3, 2, help="輪數越多品質可能越好，但等待時間與 API 用量也越多")

        make_plan = st.button("產生宣傳企劃", type="primary", disabled=not API_KEY)
        if make_plan and not event_name.strip():
            st.warning("請先填寫活動名稱")
        elif make_plan and check_quota():
            fields = [
                ("活動名稱", event_name),
                ("日期時間", event_date),
                ("地點", location),
                ("費用", fee),
                ("報名方式", signup),
                ("宣傳目標", goal),
                ("其他說明", extra),
            ]
            brief = "\n".join(f"{k}：{v.strip() or '【未提供】'}" for k, v in fields)
            with st.status("AI 顧問撰寫中（約需 1–3 分鐘）…", expanded=True) as status:
                try:
                    result = make_workflow(status, rounds).campaign(club, brief, st.session_state.diagnosis if use_diag else None)
                    md = campaign_markdown(result)
                    st.session_state.campaign_md = md
                    save_record("campaign", event_name.strip(), result.plan.key_message[:150], md)
                    status.update(label="企劃完成，已存入社團動態", state="complete", expanded=False)
                except LLMError as e:
                    status.update(label="產生失敗", state="error")
                    st.error(str(e))

        if st.session_state.get("campaign_md"):
            st.divider()
            st.markdown(st.session_state.campaign_md)
            st.download_button("下載宣傳企劃（.md）", st.session_state.campaign_md, file_name="宣傳企劃.md")

# --- 社團動態 ---------------------------------------------------------------

with tabs["🗂️ 社團動態"]:
    st.subheader("全社團各部門的提問與成果")
    st.caption("各部門向 AI 顧問提問、診斷與企劃的結果都會出現在這裡，方便掌握彼此進度。")
    options = ["all", *DEPARTMENTS]
    chosen = st.selectbox("篩選部門", options, format_func=lambda k: "全部部門" if k == "all" else DEPARTMENTS[k].label)
    records = store.list_records(club_id, department=None if chosen == "all" else chosen, limit=50)
    if not records:
        st.info("還沒有任何紀錄，先到「部門顧問」問第一個問題吧！")
    counts = pd.Series([r.department for r in store.list_records(club_id)]).value_counts() if records else None
    if counts is not None and chosen == "all":
        st.caption("｜".join(f"{DEPARTMENTS[k].icon} {DEPARTMENTS[k].name} {n} 筆" for k, n in counts.items() if k in DEPARTMENTS))
    for r in records:
        st.markdown(f"**{DEPARTMENTS[r.department].icon if r.department in DEPARTMENTS else ''} {r.title}**　{r.summary}")
        show_record(r, "feed")

# --- 社團設定 ---------------------------------------------------------------

with tabs["⚙️ 社團設定"]:
    st.subheader("社團資料")
    st.caption("所有部門的顧問都會參考這些資料。")
    updated = profile_form("settings", club)
    if st.button("儲存社團資料", type="primary"):
        if updated is None:
            st.error("請填寫社團名稱、定位與目標受眾")
        else:
            store.update_profile(club_id, updated.model_copy(update={"notes": club.notes}))
            st.success("已儲存")
            st.rerun()

# --- 使用說明 ---------------------------------------------------------------

with tabs["📖 使用說明"]:
    st.markdown(
        """
### 怎麼使用
1. 在左側選擇**我的部門**。
2. 到 **💬 部門顧問** 輸入問題（或點範例問題），按「取得建議」。
3. 建議會自動存到 **🗂️ 社團動態**，其他部門也看得到，顧問回答時也會參考其他部門的近況。
4. 行銷部門另有 **📊 社群數據診斷** 與 **📝 活動宣傳企劃** 兩個專屬工具。

### 怎麼準備貼文數據 CSV（行銷部門）
1. 下載下方的 **CSV 範本**，用 Excel 或 Google 試算表打開。
2. 從 IG／FB 的「洞察報告」把每篇貼文的數據填進去，一列一篇，建議至少近三個月。
3. 存成 CSV 後，到「社群數據診斷」上傳。

| 欄位 | 填什麼 |
|---|---|
| date | 發文日期，格式 2026-09-28 |
| time | 發文時間，格式 21:30 |
| platform | Instagram、Facebook、Dcard… |
| post_type | 圖文、輪播、Reels、公告、限動… |
| topic | 你們自己的分類，例如：活動宣傳、社課花絮、作品分享 |
| reach | 觸及人數 |
| likes / comments / shares / saves | 按讚、留言、分享、收藏數 |
| followers | 發文當下的粉絲數（選填） |
| caption | 貼文內文（選填） |

互動率 =（按讚＋留言＋分享＋收藏）÷ 觸及人數。
"""
    )
    template = ",".join(CSV_COLUMNS) + "\n2026-09-01,21:00,Instagram,輪播,活動宣傳,850,60,5,4,12,1200,範例貼文\n"
    st.download_button("下載 CSV 範本", template.encode("utf-8-sig"), file_name="貼文數據範本.csv", mime="text/csv")
    st.markdown(
        """
**小提醒**
- AI 的建議僅供參考，執行前請再確認資訊正確，涉及學校規定時請向校內單位確認。
- 請不要輸入或上傳個資（例如報名者姓名、學號）。
"""
    )

usage_slot.caption(f"本次已使用 {st.session_state.get('runs', 0)} / {MAX_RUNS} 次")

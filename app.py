"""校園社團 AI 營運顧問｜網頁版（Streamlit）

本機執行：streamlit run app.py
部署方式請見 docs/deploy.md。API 金鑰與使用密碼放在 Streamlit 的 Secrets，不寫進程式。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT / "src"))

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

from club_agent.llm import GeminiLLM, LLMError  # noqa: E402
from club_agent.metrics import decode_csv_bytes, engagement_rate, parse_posts_csv, summarize  # noqa: E402
from club_agent.report import campaign_markdown, diagnosis_markdown  # noqa: E402
from club_agent.retriever import BM25Retriever  # noqa: E402
from club_agent.schemas import ClubProfile  # noqa: E402
from club_agent.workflow import MarketingWorkflow  # noqa: E402

EXAMPLES = ROOT / "examples"
CSV_COLUMNS = ["date", "time", "platform", "post_type", "topic", "reach", "likes", "comments", "shares", "saves", "followers", "caption"]

st.set_page_config(page_title="社團 AI 營運顧問", page_icon="📣", layout="wide")


def secret(name: str, default: str | None = None) -> str | None:
    try:
        value = st.secrets.get(name)
    except Exception:  # 本機沒有 secrets.toml 時
        value = None
    return value or os.environ.get(name, default)


# ---------------------------------------------------------------------------
# 使用密碼
# ---------------------------------------------------------------------------

APP_PASSWORD = secret("APP_PASSWORD")
if APP_PASSWORD and not st.session_state.get("authed"):
    st.title("📣 社團 AI 營運顧問")
    pw = st.text_input("請輸入使用密碼", type="password")
    if st.button("進入"):
        if pw == APP_PASSWORD:
            st.session_state.authed = True
            st.rerun()
        else:
            st.error("密碼錯誤")
    st.stop()

API_KEY = secret("GEMINI_API_KEY") or secret("GOOGLE_API_KEY")
MODEL = secret("GEMINI_MODEL")
MAX_RUNS = int(secret("MAX_RUNS_PER_SESSION", "20"))


@st.cache_resource
def get_retriever() -> BM25Retriever:
    return BM25Retriever.from_directory()


def make_workflow(status, rounds: int = 3) -> MarketingWorkflow:
    from google import genai

    llm = GeminiLLM(model=MODEL, client=genai.Client(api_key=API_KEY), notify=status.write)
    return MarketingWorkflow(llm=llm, retriever=get_retriever(), max_rounds=rounds, on_progress=status.write)


def check_quota() -> bool:
    used = st.session_state.get("runs", 0)
    if used >= MAX_RUNS:
        st.warning(f"本次使用已達 {MAX_RUNS} 次上限，請重新整理頁面或稍後再試。")
        return False
    st.session_state.runs = used + 1
    return True


# ---------------------------------------------------------------------------
# 側邊欄：社團資料
# ---------------------------------------------------------------------------

CLUB_FIELDS = {
    "name": ("社團名稱", ""),
    "category": ("社團類型", "例：學藝性、康樂性、服務性、系學會"),
    "positioning": ("社團定位與特色", "例：以街頭攝影與底片攝影為特色，每週社課＋每月外拍"),
    "target_audience": ("主要目標受眾", "例：對攝影有興趣的大一至大三學生，多為初學者"),
    "brand_voice": ("品牌語氣", "例：文青、溫暖、帶點幽默"),
}

st.session_state.setdefault("club_platforms", ["Instagram", "Facebook"])
st.session_state.setdefault("club_budget", 0)

with st.sidebar:
    st.header("🏫 社團資料")
    if st.button("填入範例社團", width="stretch"):
        import json

        example = json.loads((EXAMPLES / "club_profile.json").read_text(encoding="utf-8"))
        for key in CLUB_FIELDS:
            st.session_state[f"club_{key}"] = example[key]
        st.session_state.club_platforms = example["platforms"]
        st.session_state.club_budget = example["monthly_budget_ntd"]
    for key, (label, placeholder) in CLUB_FIELDS.items():
        widget = st.text_area if key in ("positioning", "target_audience") else st.text_input
        widget(label, key=f"club_{key}", placeholder=placeholder)
    st.multiselect("經營平台", ["Instagram", "Facebook", "Dcard", "Threads"], key="club_platforms")
    st.number_input("每月行銷預算（新台幣）", min_value=0, step=500, key="club_budget")
    usage_slot = st.empty()  # 在頁面最後更新，才會算到這次按下的按鈕


def current_club() -> ClubProfile | None:
    values = {k: st.session_state.get(f"club_{k}", "").strip() for k in CLUB_FIELDS}
    if not values["name"] or not values["positioning"] or not values["target_audience"]:
        return None
    return ClubProfile(
        **{k: v for k, v in values.items() if v},
        platforms=st.session_state.get("club_platforms") or ["Instagram"],
        monthly_budget_ntd=int(st.session_state.get("club_budget", 0)),
    )


# ---------------------------------------------------------------------------
# 主畫面
# ---------------------------------------------------------------------------

st.title("📣 社團 AI 營運顧問")
st.caption("行銷宣傳與數據診斷模組｜數據診斷 Agent → 文案與策略 Agent → 經營審查 Agent")

if not API_KEY:
    st.error("網站尚未設定 GEMINI_API_KEY，請管理者到 Secrets 設定（見 docs/deploy.md）。")

tab_diag, tab_campaign, tab_help = st.tabs(["📊 社群數據診斷", "📝 活動宣傳企劃", "📖 使用說明"])

with tab_diag:
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
        club = current_club()
        if club is None:
            st.info("請先在左側「社團資料」填寫社團名稱、定位與目標受眾（手機請點左上角 » 打開），或按「填入範例社團」。")
        if st.button("開始診斷", type="primary", disabled=club is None or not API_KEY) and check_quota():
            with st.status("AI 顧問分析中…", expanded=True) as status:
                try:
                    report = make_workflow(status).diagnose(club, metrics, concern)
                    st.session_state.diagnosis = report
                    st.session_state.diagnosis_md = diagnosis_markdown(club.name, report)
                    status.update(label="診斷完成", state="complete", expanded=False)
                except LLMError as e:
                    status.update(label="診斷失敗", state="error")
                    st.error(str(e))

    if st.session_state.get("diagnosis_md"):
        st.divider()
        st.markdown(st.session_state.diagnosis_md)
        st.download_button("下載診斷報告（.md）", st.session_state.diagnosis_md, file_name="診斷報告.md")

with tab_campaign:
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

    club = current_club()
    if club is None:
        st.info("請先在左側「社團資料」填寫社團資料（手機請點左上角 » 打開）。")
    ready = club is not None and bool(event_name.strip()) and bool(API_KEY)
    if st.button("產生宣傳企劃", type="primary", disabled=not ready) and check_quota():
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
                result = make_workflow(status, rounds).campaign(
                    club, brief, st.session_state.diagnosis if use_diag else None
                )
                st.session_state.campaign_md = campaign_markdown(result)
                status.update(label="企劃完成", state="complete", expanded=False)
            except LLMError as e:
                status.update(label="產生失敗", state="error")
                st.error(str(e))

    if st.session_state.get("campaign_md"):
        st.divider()
        st.markdown(st.session_state.campaign_md)
        st.download_button("下載宣傳企劃（.md）", st.session_state.campaign_md, file_name="宣傳企劃.md")

with tab_help:
    st.subheader("怎麼準備貼文數據 CSV？")
    st.markdown(
        """
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
- AI 的建議僅供參考，發布前請再確認活動資訊正確。
- 請不要上傳個資（例如報名者姓名、學號）。
"""
    )

usage_slot.caption(f"本次已使用 {st.session_state.get('runs', 0)} / {MAX_RUNS} 次")

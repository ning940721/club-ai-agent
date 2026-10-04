"""行銷部門專屬功能：社群數據診斷、活動宣傳企劃。"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st

from ..metrics import decode_csv_bytes, engagement_rate, parse_posts_csv, summarize
from ..report import campaign_markdown, diagnosis_markdown
from ..retriever import BM25Retriever
from ..workflow import MarketingWorkflow
from .context import AppContext

EXAMPLES = Path(__file__).resolve().parents[3] / "examples"


@st.cache_resource
def get_marketing_retriever() -> BM25Retriever:
    return BM25Retriever.from_directory()


def _workflow(llm, status, rounds: int = 3) -> MarketingWorkflow:
    return MarketingWorkflow(llm=llm, retriever=get_marketing_retriever(), max_rounds=rounds, on_progress=status.write)


def diagnosis_page(ctx: AppContext) -> None:
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
        if st.button("開始診斷", type="primary"):
            report = ctx.run_ai(
                "AI 顧問分析中…",
                lambda llm, status: _workflow(llm, status).diagnose(ctx.club, metrics, concern),
                "診斷完成，已存入社團動態",
            )
            if report:
                md = diagnosis_markdown(ctx.club.name, report)
                st.session_state.diagnosis = report
                st.session_state.diagnosis_md = md
                ctx.save_record("diagnosis", "社群數據診斷", report.summary[:150], md)

    if st.session_state.get("diagnosis_md"):
        st.divider()
        st.markdown(st.session_state.diagnosis_md)
        st.download_button("下載診斷報告（.md）", st.session_state.diagnosis_md, file_name="診斷報告.md")


def campaign_page(ctx: AppContext) -> None:
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

    if st.button("產生宣傳企劃", type="primary"):
        if not event_name.strip():
            st.warning("請先填寫活動名稱")
        else:
            fields = [("活動名稱", event_name), ("日期時間", event_date), ("地點", location), ("費用", fee),
                      ("報名方式", signup), ("宣傳目標", goal), ("其他說明", extra)]
            brief = "\n".join(f"{k}：{v.strip() or '【未提供】'}" for k, v in fields)
            diagnosis = st.session_state.diagnosis if use_diag else None
            result = ctx.run_ai(
                "AI 顧問撰寫中（約需 1–3 分鐘）…",
                lambda llm, status: _workflow(llm, status, rounds).campaign(ctx.club, brief, diagnosis),
                "企劃完成，已存入社團動態",
            )
            if result:
                md = campaign_markdown(result)
                st.session_state.campaign_md = md
                ctx.save_record("campaign", event_name.strip(), result.plan.key_message[:150], md)

    if st.session_state.get("campaign_md"):
        st.divider()
        st.markdown(st.session_state.campaign_md)
        st.download_button("下載宣傳企劃（.md）", st.session_state.campaign_md, file_name="宣傳企劃.md")

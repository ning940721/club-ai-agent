"""行銷部門專屬功能：社群數據診斷、活動宣傳企劃。"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd
import streamlit as st

from ..metrics import (
    FIELD_LABELS,
    PLATFORMS,
    coverage,
    decode_csv_bytes,
    engagement_rate,
    guess_mapping,
    read_table,
    rows_to_posts,
    summarize,
)
from ..agents import MonthlyReviewer
from ..events import club_events, events_digest
from ..post_history import clear_history, compare_month, list_history, months, save_posts
from ..report import campaign_markdown, diagnosis_markdown, monthly_report_markdown
from ..retriever import BM25Retriever
from ..workflow import MarketingWorkflow
from .context import AppContext, download_buttons

EXAMPLES = Path(__file__).resolve().parents[3] / "examples"


@st.cache_resource
def get_marketing_retriever() -> BM25Retriever:
    return BM25Retriever.from_directory()


def _workflow(llm, status, rounds: int = 3) -> MarketingWorkflow:
    return MarketingWorkflow(llm=llm, retriever=get_marketing_retriever(), max_rounds=rounds, on_progress=status.write)


def load_posts(ctx: AppContext) -> list | None:
    """上傳 CSV → 確認欄位對應 → 轉成貼文；顯示資料完整度。只有日期是必填。"""
    col1, col2 = st.columns([3, 1])
    uploaded = col1.file_uploader("貼文數據 CSV（IG／FB 匯出的檔案或自己整理的表格都可以，格式見「使用說明」）", type="csv")
    use_example = col2.checkbox("使用範例數據", value=uploaded is None)
    if uploaded is None and not use_example:
        return None
    try:
        text = (EXAMPLES / "sample_posts.csv").read_text(encoding="utf-8") if use_example else decode_csv_bytes(uploaded.getvalue())
        columns, rows = read_table(text)
    except Exception as e:  # 檔案不是 CSV 或編碼錯誤
        st.error(f"CSV 讀取失敗：{e}")
        return None
    if not rows:
        st.warning("檔案裡沒有資料")
        return None

    guessed = guess_mapping(columns)
    file_key = abs(hash(tuple(columns))) % 10**8  # 換檔案時重新對應
    with st.expander("欄位對應（系統已自動判斷，對錯了可以修改；沒有的欄位選「沒有這一欄」）", expanded="date" not in guessed):
        mapping = {}
        cols = st.columns(4)
        for i, (f, label) in enumerate(FIELD_LABELS.items()):
            options = ["", *columns]
            mapping[f] = cols[i % 4].selectbox(
                f"{label}{'＊' if f == 'date' else ''}", options, index=options.index(guessed[f]) if f in guessed else 0,
                format_func=lambda c: c or "沒有這一欄", key=f"mk_map_{file_key}_{f}",
            )
    mapping = {f: c for f, c in mapping.items() if c}
    if "date" not in mapping:
        st.error("請在「欄位對應」選擇哪一欄是發文日期（唯一必填的欄位）")
        return None
    default_platform = ""
    if "platform" not in mapping:
        default_platform = st.selectbox("檔案裡沒有平台欄位，這份資料是哪個平台的？", PLATFORMS, key=f"mk_platform_{file_key}")

    posts, skipped = rows_to_posts(rows, mapping, default_platform)
    if skipped:
        with st.expander(f"有 {len(skipped)} 列略過（日期空白或看不懂）"):
            st.markdown("\n".join(f"- {x}" for x in skipped[:50]))
    if not posts:
        st.error("沒有可以分析的貼文，請確認日期欄位")
        return None
    gaps = [c for c in coverage(posts) if c.missing]
    if gaps:
        st.info("有些資料沒有填，沒關係：空白會當成「不知道」，不會當成 0；AI 也會知道少了哪些資料，不會亂下結論。")
        st.dataframe(
            pd.DataFrame({"欄位": [c.label for c in gaps], "有資料": [f"{c.filled}/{c.total} 篇" for c in gaps],
                          "影響": [c.impact for c in gaps]}),
            hide_index=True, width="stretch",
        )
    return posts


def diagnosis_page(ctx: AppContext) -> None:
    st.subheader("上傳社群數據，找出流量瓶頸")
    posts = load_posts(ctx)
    if posts:
        metrics = summarize(posts)
        df = pd.DataFrame([p.model_dump() for p in posts])
        df["互動率"] = [("—" if (r := engagement_rate(p)) is None else f"{r:.2%}") for p in posts]
        df = df.rename(columns=FIELD_LABELS)
        st.success(f"已讀取 {len(posts)} 篇貼文（{metrics.date_range[0]} ~ {metrics.date_range[1]}）")
        with st.expander("查看數據與統計摘要"):
            st.dataframe(df, width="stretch", hide_index=True)
            st.text(metrics.to_prompt_text())
        if st.button("存到歷史資料（月報與趨勢會用到）", icon=":material/history:", key="save_history"):
            added, updated = save_posts(ctx.store, ctx.club_id, posts)
            st.success(f"已存入：新增 {added} 篇、更新 {updated} 篇。到「月報與趨勢」查看各月比較。")

        concern = st.text_area("目前的宣傳困擾（選填）", placeholder="例：最近三個月觸及一直掉，不知道該發什麼")
        col_btn, col_share = st.columns([1, 3], vertical_alignment="center")
        clicked = col_btn.button("開始診斷", type="primary")
        with col_share:
            share = ctx.share_toggle("diagnosis")
        if clicked:
            report = ctx.run_ai(
                "AI 顧問分析中…",
                lambda llm, status: _workflow(llm, status).diagnose(ctx.club, metrics, concern),
                "診斷完成",
            )
            if report:
                md = diagnosis_markdown(ctx.club.name, report)
                st.session_state.diagnosis = report
                st.session_state.diagnosis_md = md
                ctx.keep_result("diagnosis", "diagnosis", "社群數據診斷", report.summary[:150], md, share)

    if st.session_state.get("diagnosis_md"):
        st.divider()
        st.markdown(st.session_state.diagnosis_md)
        download_buttons(st.session_state.diagnosis_md, "社群數據診斷報告", "diagnosis")
        ctx.share_controls("diagnosis")


def monthly_page(ctx: AppContext) -> None:
    """月報與趨勢：歷史資料的各月比較、趨勢圖與 AI 月報。"""
    history = list_history(ctx.store, ctx.club_id)
    if not history:
        st.info("還沒有歷史資料。到「社群數據診斷」上傳貼文數據後，按「存到歷史資料」。之後每個月上傳一次最新的匯出檔，系統會自動合併。")
        return
    available = months(history)
    st.caption(f"歷史資料：{len(history)} 篇貼文（{available[-1]} ~ {available[0]}）。每個月上傳一次最新的匯出檔，重複的貼文會自動合併。")

    trend = summarize(history).by_month
    if len(trend) >= 2:
        st.markdown("**歷月趨勢**")
        chart = pd.DataFrame({
            "月份": [m.key for m in trend],
            "平均觸及": [m.avg_reach for m in trend],
            "平均互動率（%）": [None if m.avg_engagement_rate is None else round(m.avg_engagement_rate * 100, 2) for m in trend],
        }).set_index("月份")
        # 觸及與互動率單位不同，分成兩張圖，不用雙軸
        c1, c2 = st.columns(2)
        with c1:
            st.caption("平均觸及（人）")
            st.line_chart(chart["平均觸及"], color="#2D4A6B", height=220)
        with c2:
            st.caption("平均互動率（%）")
            st.line_chart(chart["平均互動率（%）"], color="#2D4A6B", height=220)
        with st.expander("查看各月數字"):
            st.dataframe(
                pd.DataFrame({
                    "月份": [m.key for m in trend], "貼文數": [m.posts for m in trend],
                    "平均觸及": ["—" if m.avg_reach is None else f"{m.avg_reach:,.0f}" for m in trend],
                    "平均互動率": ["—" if m.avg_engagement_rate is None else f"{m.avg_engagement_rate:.2%}" for m in trend],
                }),
                hide_index=True, width="stretch",
            )

    st.divider()
    month = st.selectbox("月報月份", available, key="monthly_month")
    comparison = compare_month(history, month)
    st.markdown(f"**{month} 和 {comparison.previous} 比較**")
    st.dataframe(pd.DataFrame(comparison.rows(), columns=["指標", "本月", "上月", "變化"]), hide_index=True, width="stretch")
    if comparison.current.top_posts:
        st.markdown("**本月互動率最高的貼文**\n" + "\n".join(f"- {t}" for t in comparison.current.top_posts))
    gaps = [c for c in comparison.current.coverage if c.missing]
    if gaps:
        st.caption("本月資料完整度：" + "；".join(f"{c.label} {c.filled}/{c.total}" for c in gaps))

    concern = st.text_input("這個月想特別了解什麼（選填）", placeholder="例：Reels 是不是比輪播好？", key="monthly_concern")
    col_btn, col_share = st.columns([1, 3], vertical_alignment="center")
    clicked = col_btn.button("產生 AI 月報", type="primary", key="monthly_go")
    with col_share:
        share = ctx.share_toggle("monthly")
    if clicked:
        trend_text = "\n".join(f"- {m.line()}" for m in trend)
        today = date.today()
        upcoming = events_digest(club_events(ctx.store, ctx.club_id, ctx.settings), today, past_days=0, future_days=45,
                                 settings=ctx.settings)
        review = ctx.run_ai(
            "撰寫社群月報中…",
            lambda llm, _s: MonthlyReviewer(llm).run(ctx.club, comparison.to_prompt_text(), trend_text, upcoming, concern),
        )
        if review:
            md = monthly_report_markdown(ctx.club.name, month, comparison.rows(), review)
            st.session_state.monthly_md = (month, md)
            ctx.keep_result("monthly", "monthly", f"社群月報（{month}）", review.summary[:150], md, share, "marketing")
    if (saved := st.session_state.get("monthly_md")) and saved[0] == month:
        st.divider()
        st.markdown(saved[1])
        download_buttons(saved[1], f"社群月報_{month}", f"monthly_{month}")
        ctx.share_controls("monthly")

    with st.expander("清除歷史資料"):
        st.caption("會刪除所有存過的貼文數據（不影響已產生的報告）。")
        if st.button("確定清除", key="clear_history"):
            clear_history(ctx.store, ctx.club_id)
            st.session_state.pop("monthly_md", None)
            st.rerun()


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
    rounds = st.slider("最多審查修訂輪數", 1, 3, 1, help="每多一輪就多呼叫 AI 兩次。輪數越多品質可能越好，但等待時間與用量也會增加")

    col_btn, col_share = st.columns([1, 3], vertical_alignment="center")
    clicked = col_btn.button("產生宣傳企劃", type="primary")
    with col_share:
        share = ctx.share_toggle("campaign")
    if clicked:
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
                "企劃完成",
            )
            if result:
                md = campaign_markdown(result)
                st.session_state.campaign_md = md
                ctx.keep_result("campaign", "campaign", event_name.strip(), result.plan.key_message[:150], md, share)

    if st.session_state.get("campaign_md"):
        st.divider()
        st.markdown(st.session_state.campaign_md)
        download_buttons(st.session_state.campaign_md, "活動宣傳企劃", "campaign")
        ctx.share_controls("campaign")

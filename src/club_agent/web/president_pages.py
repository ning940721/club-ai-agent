"""社長專屬：各部門進度總覽，自動產出進度彙整與下次會議議程。"""

from __future__ import annotations

from datetime import date

import pandas as pd
import streamlit as st

from ..agents import ProgressReporter
from ..meetings import list_meetings, recent_summaries_digest
from ..report import progress_brief_markdown
from ..store import activity_digest
from ..tasks import department_progress, list_tasks, tasks_digest
from .common_pages import add_task_form, tasks_table
from .context import AppContext


def upcoming_dates(ctx: AppContext, today: date) -> list[str]:
    rows = []
    for doc in list_meetings(ctx.store, ctx.club_id):
        if doc.summary:
            for k in doc.summary.key_dates:
                if k.date >= today.isoformat():
                    extra = " ".join(x for x in (k.time, k.location) if x)
                    rows.append((k.date, f"**{k.date}** {extra}｜{k.event}"))
    return [line for _, line in sorted(set(rows))]


def president_page(ctx: AppContext) -> None:
    today = date.today()
    tasks = list_tasks(ctx.store, ctx.club_id)
    records = ctx.store.list_records(ctx.club_id)
    stats = department_progress(tasks, today)
    last_activity = {}
    for r in records:
        last_activity.setdefault(r.department, r.created_at[:10])

    st.subheader("各部門進度")
    rows = []
    for key in ctx.settings.enabled_keys():
        s = stats.get(key, {})
        rows.append(
            {
                "部門": ctx.settings.label(key),
                "未完成": s.get("待辦", 0) + s.get("進行中", 0),
                "進行中": s.get("進行中", 0),
                "逾期": s.get("逾期", 0),
                "已完成": s.get("完成", 0),
                "最近一次使用": last_activity.get(key, "—"),
            }
        )
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")

    overdue = [t for t in tasks if t.is_overdue(today)]
    upcoming = upcoming_dates(ctx, today)
    c1, c2 = st.columns(2)
    with c1:
        st.markdown(f"**逾期任務（{len(overdue)}）**")
        for t in overdue[:10]:
            st.markdown(f"- {ctx.settings.name(t.department)}｜{t.title}（{t.owner or '未指定'}，期限 {t.due}）")
        if not overdue:
            st.caption("目前沒有逾期任務。")
    with c2:
        st.markdown("**近期重要日期**（來自會議記錄）")
        for line in upcoming[:10]:
            st.markdown(f"- {line}")
        if not upcoming:
            st.caption("尚無日期。上傳會議記錄並整理重點後會自動出現。")

    st.divider()
    st.subheader("進度彙整與會議議程")
    st.caption("AI 會根據各部門的待辦、社團動態與最近的會議記錄，整理每個部門在做什麼、哪裡卡關，並規劃下次會議要討論的內容。")
    if st.button("產生進度彙整與議程", type="primary"):
        meetings = list_meetings(ctx.store, ctx.club_id)

        def build(llm, _status):
            return ProgressReporter(llm).run(
                ctx.club,
                ctx.settings,
                tasks_digest(tasks, ctx.settings, today),
                activity_digest(records[:40], limit=20, settings=ctx.settings),
                recent_summaries_digest(meetings),
                today,
            )

        brief = ctx.run_ai("彙整各部門進度中…", build, "完成，已存入社團動態")
        if brief:
            md = progress_brief_markdown(ctx.club.name, today.isoformat(), brief)
            st.session_state.progress_md = md
            ctx.save_record("brief", f"進度彙整與議程（{today.isoformat()}）", brief.overview[:150], md, department="president")
    if md := st.session_state.get("progress_md"):
        st.markdown(md)
        st.download_button("下載（.md）", md, file_name="進度彙整與議程.md")

    st.divider()
    st.subheader("全社團待辦")
    add_task_form(ctx, "all", department=None)
    show_done = st.toggle("顯示已完成", key="show_done_all")
    tasks_table(ctx, [t for t in list_tasks(ctx.store, ctx.club_id) if show_done or t.status != "完成"], "all", show_department=True)

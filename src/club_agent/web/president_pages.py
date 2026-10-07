"""社長專屬：各部門進度總覽，自動產出進度彙整與下次會議議程。"""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import streamlit as st

from ..agenda import (
    KINDS,
    AgendaRow,
    MeetingPlan,
    delete_plan,
    get_plan,
    list_plans,
    meeting_description,
    parse_time,
    rows_from_items,
    save_plan,
    schedule,
    schedule_markdown,
    template_rows,
    total_minutes,
)
from ..agents import ProgressReporter
from ..departments import MeetingDefaults
from ..events import club_events
from ..events import upcoming as upcoming_events
from ..meetings import list_meetings, recent_summaries_digest
from ..report import progress_brief_markdown
from ..store import activity_digest
from ..tasks import department_progress, list_tasks, tasks_digest
from .common_pages import add_task_form, tasks_table
from .context import AppContext, demote_headings, download_buttons


def upcoming_dates(ctx: AppContext, today: date) -> list[str]:
    """接下來的行程（來自行事曆：會議、會議記錄中的日期、自行新增的行程；待辦期限另外列在逾期／任務表）。"""
    lines = []
    for e in upcoming_events(club_events(ctx.store, ctx.club_id, ctx.settings), today):
        if e.kind == "截止":
            continue
        extra = " ".join(x for x in (e.time, e.location) if x)
        dept = f"［{ctx.settings.name(e.department)}］" if e.department else ""
        lines.append(f"**{e.date}** {extra}｜{dept}{e.title}")
    return lines


def meeting_inputs(ctx: AppContext, today: date, default_date: date) -> tuple[date, object, int, str]:
    """會議日期、開始時間、時長與地點；時間、時長、地點會存成社團預設值，下次自動帶入。"""
    saved = ctx.settings.meeting
    c1, c2, c3, c4 = st.columns([2, 2, 2, 3])
    meeting_date = c1.date_input("會議日期", value=default_date, key="mt_date")
    start = c2.time_input("開始時間", value=parse_time(saved.start), step=300, key="mt_start")
    minutes = c3.number_input("會議時長（分鐘）", min_value=10, max_value=480, value=saved.minutes, step=10, key="mt_minutes")
    location = c4.text_input("地點（選填）", value=saved.location, placeholder="例：社辦、線上 Google Meet", key="mt_location")
    current = MeetingDefaults(start=f"{start:%H:%M}", minutes=int(minutes), location=location.strip())
    if current != saved:
        ctx.settings = ctx.settings.model_copy(update={"meeting": current})
        ctx.store.update_settings(ctx.club_id, ctx.settings)
    return meeting_date, start, int(minutes), location.strip()


def set_agenda(rows: list[AgendaRow]) -> None:
    st.session_state.agenda_rows = rows
    st.session_state.agenda_current = rows
    st.session_state.agenda_version = st.session_state.get("agenda_version", 0) + 1  # 讓編輯表格重新載入


def _text(value) -> str:
    """表格新增的空白列會是 None／NaN。"""
    return "" if value is None or pd.isna(value) else str(value).strip()


def agenda_editor(rows: list[AgendaRow]) -> list[AgendaRow]:
    """可新增、刪除、修改議題與分鐘數的表格；回傳修改後的議程。"""
    df = pd.DataFrame(
        {
            "議題": [r.topic for r in rows],
            "類型": [r.kind if r.kind in KINDS else "討論" for r in rows],
            "負責": [r.department for r in rows],
            "分鐘": [r.minutes for r in rows],
            "目標": [r.goal for r in rows],
        }
    )
    edited = st.data_editor(
        df,
        key=f"agenda_editor_{st.session_state.get('agenda_version', 0)}",
        num_rows="dynamic",
        hide_index=True,
        width="stretch",
        column_config={
            "類型": st.column_config.SelectboxColumn(options=list(KINDS), required=True),
            "分鐘": st.column_config.NumberColumn(min_value=0, max_value=480, step=5, required=True),
        },
    )
    out = []
    for row in edited.to_dict("records"):
        if topic := _text(row["議題"]):
            minutes = 0 if pd.isna(row["分鐘"]) else int(row["分鐘"])
            out.append(AgendaRow(topic, minutes, _text(row["類型"]) or "討論", _text(row["負責"]), _text(row["目標"])))
    return out


def remember_plan(ctx: AppContext, plan: MeetingPlan) -> None:
    """自動儲存議程；這次操作中改了會議日期時，移除舊日期的那份，避免留下重複的議程。"""
    previous = st.session_state.get("plan_saved_date")
    if previous and previous != plan.date:
        delete_plan(ctx.store, ctx.club_id, previous)
    if get_plan(ctx.store, ctx.club_id, plan.id) != plan:
        save_plan(ctx.store, ctx.club_id, plan)
    st.session_state.plan_saved_date = plan.date


def unresolved_section(ctx: AppContext) -> None:
    """上次會議中還沒有決議的議題（來自會議記錄的議程對照），可以一鍵加入這次議程。"""
    last = next((d for d in list_meetings(ctx.store, ctx.club_id) if d.summary and d.summary.agenda_review), None)
    if last is None:
        return
    pending = last.summary.unresolved_agenda()
    st.markdown(f"**上次會議議程追蹤**（{last.date}｜{last.title}）")
    if not pending:
        st.caption("上次議程的所有議題都已經有決議。")
        return
    for c in pending:
        st.markdown(f"- {c.topic}：{c.result}" + (f"（{c.note}）" if c.note else ""))
    rows = st.session_state.get("agenda_current") or st.session_state.get("agenda_rows") or []  # 含表格中的修改
    existing = {r.topic for r in rows}
    new = [AgendaRow(c.topic, 10, "討論", "", f"延續上次：{c.note}" if c.note else "延續上次會議") for c in pending if c.topic not in existing]
    if new and st.button("把這些議題加入下次議程", key="carry_over"):
        set_agenda([*rows, *new])
        st.rerun()


def meeting_section(ctx: AppContext, tasks, records, today: date) -> None:
    st.subheader("下次幹部會議")
    st.caption("設定會議時間與時長，AI 會依各部門的待辦、分享的成果與最近的會議記錄規劃議程，並排出每個議題的時段。")
    upcoming = [p for p in list_plans(ctx.store, ctx.club_id) if p.date >= today.isoformat()]
    default_date = date.fromisoformat(upcoming[-1].date) if upcoming else today + timedelta(days=7)
    meeting_date, start, minutes, location = meeting_inputs(ctx, today, default_date)
    if st.session_state.get("agenda_rows") is None and (saved := get_plan(ctx.store, ctx.club_id, meeting_date.isoformat())):
        set_agenda(saved.agenda)  # 之前排好的議程

    col_ai, col_template, col_share = st.columns([2, 2, 3], vertical_alignment="center")
    clicked = col_ai.button("產生進度彙整與議程", type="primary", width="stretch")
    with col_share:
        share = ctx.share_toggle("brief")
    if clicked:
        meetings = list_meetings(ctx.store, ctx.club_id)
        meeting_text = meeting_description(meeting_date, start, minutes, location)

        def build(llm, _status):
            return ProgressReporter(llm).run(
                ctx.club,
                ctx.settings,
                tasks_digest(tasks, ctx.settings, today),
                activity_digest(records[:40], limit=20, settings=ctx.settings),
                recent_summaries_digest(meetings),
                today,
                meeting_text,
            )

        brief = ctx.run_ai("彙整各部門進度中…", build)
        if brief:
            rows = rows_from_items(brief.agenda)
            set_agenda(rows)
            st.session_state.progress_brief = brief
            md = progress_brief_markdown(
                ctx.club.name, today.isoformat(), brief, schedule_markdown(meeting_date, start, minutes, rows, location)
            )
            ctx.keep_result("brief", "brief", f"進度彙整與議程（{today.isoformat()}）", brief.overview[:150], md, share, "president")
    if col_template.button("使用基本議程（不使用 AI）", width="stretch"):
        names = [ctx.settings.name(k) for k in ctx.settings.enabled_keys() if k != "president"]
        set_agenda(template_rows(minutes, names))
        st.session_state.pop("progress_brief", None)
        st.session_state.pop("result_brief", None)

    unresolved_section(ctx)
    rows = st.session_state.get("agenda_rows")
    if rows is None:
        return

    st.markdown("**會議時間表**")
    with st.expander("調整議程（修改議題、分鐘數，或在表格最下方新增一列；勾選列後可刪除）"):
        rows = agenda_editor(rows)
    st.session_state.agenda_current = rows
    used = total_minutes(rows)
    table = pd.DataFrame(
        {
            "時間": [s.span for s in schedule(rows, start)],
            "議題": [r.topic for r in rows],
            "類型": [r.kind for r in rows],
            "負責": [r.department for r in rows],
            "分鐘": [r.minutes for r in rows],
            "目標": [r.goal for r in rows],
        }
    )
    st.dataframe(table, hide_index=True, width="stretch")
    if used == minutes:
        st.caption(f"共 {used} 分鐘，剛好符合預定時長。")
    elif used < minutes:
        st.caption(f"共 {used} 分鐘，比預定時長少 {minutes - used} 分鐘。")
    else:
        st.warning(f"議程共 {used} 分鐘，超過預定時長 {used - minutes} 分鐘，建議縮短部分議題。")

    remember_plan(ctx, MeetingPlan(date=meeting_date.isoformat(), start=f"{start:%H:%M}", minutes=minutes, location=location, agenda=rows))
    st.caption("議程會自動儲存；會議記錄部門整理這場會議的記錄時，會逐一對照每個議題是否已有決議。")

    agenda_md = schedule_markdown(meeting_date, start, minutes, rows, location)
    if brief := st.session_state.get("progress_brief"):
        md = progress_brief_markdown(ctx.club.name, today.isoformat(), brief, agenda_md)
        without_agenda = progress_brief_markdown(ctx.club.name, today.isoformat(), brief.model_copy(update={"agenda": []}))
        with st.expander("進度彙整（各部門進度、需要決定的事、近期提醒）", expanded=True):
            st.markdown(demote_headings(without_agenda, 1))
        download_buttons(md, f"幹部會議議程_{meeting_date.isoformat()}", "meeting_brief")
    else:
        md = f"# {ctx.club.name} 幹部會議議程\n\n{agenda_md}"
        download_buttons(md, f"幹部會議議程_{meeting_date.isoformat()}", "meeting_agenda")

    # 還沒分享時，按「分享給其他部門」要分享修改後的最新議程，而不是 AI 剛產生的版本
    item = st.session_state.get("result_brief")
    if item is None:
        title = f"幹部會議議程（{meeting_date.isoformat()}）"
        summary = meeting_description(meeting_date, start, minutes, location)
        ctx.keep_result("brief", "brief", title, summary, md, share=False, department="president")
    elif not item["shared"]:
        item["markdown"] = md
    ctx.share_controls("brief")


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
        st.markdown("**近期行程**（完整內容見「行事曆」）")
        for line in upcoming[:10]:
            st.markdown(f"- {line}")
        if not upcoming:
            st.caption("目前沒有之後的行程。排好的幹部會議、會議記錄中的日期與自行新增的行程都會出現在這裡。")

    st.divider()
    meeting_section(ctx, tasks, records, today)

    st.divider()
    st.subheader("全社團待辦")
    add_task_form(ctx, "all", department=None)
    show_done = st.toggle("顯示已完成", key="show_done_all")
    tasks_table(ctx, [t for t in list_tasks(ctx.store, ctx.club_id) if show_done or t.status != "完成"], "all", show_department=True)

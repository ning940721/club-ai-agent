"""課程部門：學期課表（AI 規劃、可編輯、下載）、出席與回饋（出席率與趨勢）。"""

from __future__ import annotations

import io
from datetime import date, datetime, time, timedelta
from typing import Callable

import pandas as pd
import streamlit as st

from ..agents import CoursePlanner
from ..courses import (
    STATUSES,
    CourseSession,
    CourseSettings,
    attendance_stats,
    delete_session,
    get_course_settings,
    list_sessions,
    plan_to_sessions,
    save_course_settings,
    save_session,
    schedule_markdown,
)
from ..departments import department_retriever
from .context import AppContext, download_buttons

XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
WEEKDAY_NAMES = ["週一", "週二", "週三", "週四", "週五", "週六", "週日"]


@st.cache_resource
def _courses_retriever():
    return department_retriever("courses")


def _flash(message: str) -> None:
    st.session_state.course_flash = message
    st.rerun()


def _text(value) -> str:
    return "" if value is None or (not isinstance(value, str) and pd.isna(value)) else str(value).strip()


def _time(text: str, default: time) -> time:
    try:
        return datetime.strptime(text, "%H:%M").time()
    except (TypeError, ValueError):
        return default


def course_tabs(ctx: AppContext) -> list[tuple[str, Callable[[], None]]]:
    if message := st.session_state.pop("course_flash", None):
        st.success(message)
    sessions = list_sessions(ctx.store, ctx.club_id)
    return [(f"學期課表（{sum(s.status != '取消' for s in sessions)}）", lambda: schedule_tab(ctx, sessions)),
            ("出席與回饋", lambda: attendance_tab(ctx, sessions))]


# ---------------------------------------------------------------------------
# 學期課表
# ---------------------------------------------------------------------------


def planner(ctx: AppContext) -> None:
    with st.expander("請 AI 規劃學期課表", expanded=not list_sessions(ctx.store, ctx.club_id)):
        c1, c2 = st.columns(2)
        goal = c1.text_input("學期目標", placeholder="例：讓零基礎的社員學期末能獨立拍出一組作品", key="cp_goal")
        level = c2.text_input("學員程度", placeholder="例：多為大一新生、零基礎", key="cp_level")
        c3, c4, c5, c6 = st.columns(4)
        count = c3.number_input("堂數", min_value=1, max_value=30, value=12, key="cp_count")
        weekday = c4.selectbox("上課星期", range(7), index=3, format_func=lambda i: WEEKDAY_NAMES[i], key="cp_weekday")
        start = c5.time_input("開始時間", value=time(19, 0), step=900, key="cp_start")
        end = c6.time_input("結束時間", value=time(21, 0), step=900, key="cp_end")
        today = date.today()
        c7, c8 = st.columns(2)
        first = c7.date_input("第一堂課的日期", value=today + timedelta(days=(weekday - today.weekday()) % 7 or 7), key="cp_first")
        location = c8.text_input("地點", placeholder="例：社辦", key="cp_location")
        skip_text = st.text_input("要跳過的日期（用逗號分開，例如期中考週、連假）", placeholder="例：2026-11-05, 2026-11-12", key="cp_skip")
        extra = st.text_input("其他要求（選填）", placeholder="例：第 6 堂想邀請外部講者；期末要辦小型成果展", key="cp_extra")
        if first.weekday() != weekday:
            st.caption(f"提醒：第一堂課的日期是{WEEKDAY_NAMES[first.weekday()]}，之後每週同一天上課。")
        if st.button("產生課表", type="primary", key="cp_go"):
            minutes = (datetime.combine(today, end) - datetime.combine(today, start)).seconds // 60
            plan = ctx.run_ai(
                "規劃社課中…",
                lambda llm, _s: CoursePlanner(llm, _courses_retriever()).plan(
                    ctx.club, goal, level, int(count), minutes, ctx.settings.details("courses"), extra),
            )
            if plan:
                skip = {x.strip() for x in skip_text.replace("，", ",").split(",") if x.strip()}
                st.session_state.course_plan = (plan, plan_to_sessions(plan, first, f"{start:%H:%M}", f"{end:%H:%M}", location.strip(), skip))
        if saved := st.session_state.get("course_plan"):
            plan, drafts = saved
            st.markdown("**AI 規劃的課表**（套用後可以在下方修改）")
            st.dataframe(pd.DataFrame({
                "日期": [s.label() for s in drafts], "主題": [s.title for s in drafts],
                "學習目標": [s.objectives for s in drafts], "準備材料": [s.materials for s in drafts],
            }), hide_index=True, width="stretch")
            if plan.notes:
                st.markdown("\n".join(f"- {n}" for n in plan.notes))
            c1, c2 = st.columns(2)
            if c1.button(f"套用到課表（新增 {len(drafts)} 堂）", type="primary", key="cp_apply"):
                for s in drafts:
                    save_session(ctx.store, ctx.club_id, s)
                st.session_state.pop("course_plan", None)
                st.session_state.course_version = st.session_state.get("course_version", 0) + 1
                _flash(f"已新增 {len(drafts)} 堂社課，並加入行事曆")
            if c2.button("不要這份", key="cp_discard"):
                st.session_state.pop("course_plan", None)
                st.rerun()


def schedule_tab(ctx: AppContext, sessions: list[CourseSession]) -> None:
    planner(ctx)
    st.markdown("**課表**（可以直接修改；在最下方新增一列可以加課；勾選「刪除」後儲存）")
    df = pd.DataFrame({
        "id": pd.Series([s.id for s in sessions], dtype="object"),
        "日期": pd.Series([date.fromisoformat(s.date) for s in sessions], dtype="object"),
        "開始": pd.Series([_time(s.start, time(19)) for s in sessions], dtype="object"),
        "結束": pd.Series([_time(s.end, time(21)) for s in sessions], dtype="object"),
        "主題": pd.Series([s.title for s in sessions], dtype="object"),
        "講師": pd.Series([s.instructor for s in sessions], dtype="object"),
        "地點": pd.Series([s.location for s in sessions], dtype="object"),
        "狀態": pd.Series([s.status for s in sessions], dtype="object"),
        "學習目標": pd.Series([s.objectives for s in sessions], dtype="object"),
        "準備材料": pd.Series([s.materials for s in sessions], dtype="object"),
        "刪除": pd.Series([False for _ in sessions], dtype="bool"),
    })
    edited = st.data_editor(
        df, key=f"course_editor_{st.session_state.get('course_version', 0)}", num_rows="dynamic", hide_index=True, width="stretch",
        column_order=["日期", "開始", "結束", "主題", "講師", "地點", "狀態", "學習目標", "準備材料", "刪除"],
        column_config={
            "日期": st.column_config.DateColumn(format="YYYY-MM-DD", required=True),
            "開始": st.column_config.TimeColumn(format="HH:mm", step=900, default=time(19)),
            "結束": st.column_config.TimeColumn(format="HH:mm", step=900, default=time(21)),
            "狀態": st.column_config.SelectboxColumn(options=list(STATUSES), default="規劃中"),
        },
    )
    if st.button("儲存課表", type="primary", key="course_save"):
        by_id = {s.id: s for s in sessions}
        kept, removed = 0, 0
        for row in edited.to_dict("records"):
            sid = _text(row.get("id"))
            if row.get("刪除") and sid in by_id:
                delete_session(ctx.store, ctx.club_id, sid)
                removed += 1
                continue
            if row.get("日期") is None or pd.isna(row.get("日期")) or not _text(row.get("主題")):
                continue
            start = row["開始"] if isinstance(row.get("開始"), time) else time(19)
            end = row["結束"] if isinstance(row.get("結束"), time) else time(21)
            base = by_id.get(sid) or CourseSession(date="", title="")
            save_session(ctx.store, ctx.club_id, base.model_copy(update={
                "date": row["日期"].isoformat(), "start": f"{start:%H:%M}", "end": f"{end:%H:%M}", "title": _text(row["主題"]),
                "instructor": _text(row.get("講師")), "location": _text(row.get("地點")),
                "status": _text(row.get("狀態")) or "規劃中", "objectives": _text(row.get("學習目標")), "materials": _text(row.get("準備材料")),
            }))
            kept += 1
        st.session_state.course_version = st.session_state.get("course_version", 0) + 1
        _flash(f"已儲存 {kept} 堂" + (f"、刪除 {removed} 堂" if removed else ""))

    if sessions:
        settings = get_course_settings(ctx.store, ctx.club_id)
        md = schedule_markdown(ctx.club.name, sessions, settings.member_count)
        c1, c2 = st.columns([1, 4])

        def excel() -> bytes:
            buffer = io.BytesIO()
            with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
                df.drop(columns=["id", "刪除"]).to_excel(writer, sheet_name="課表", index=False)
            return buffer.getvalue()

        c1.download_button("下載 Excel", excel, file_name="社課課表.xlsx", mime=XLSX_MIME, icon=":material/table_view:",
                           on_click="ignore", width="stretch", key="course_xlsx")
        with c2:
            download_buttons(md, "社課課表", "course_schedule")


# ---------------------------------------------------------------------------
# 出席與回饋
# ---------------------------------------------------------------------------


def attendance_tab(ctx: AppContext, sessions: list[CourseSession]) -> None:
    active = [s for s in sessions if s.status != "取消"]
    if not active:
        st.info("先在「學期課表」建立社課，才能記錄出席。")
        return
    settings = get_course_settings(ctx.store, ctx.club_id)
    c1, c2 = st.columns([1, 3], vertical_alignment="bottom")
    members = c1.number_input("社員人數（算出席率用）", min_value=0, step=1, value=settings.member_count or 0, key="course_members")
    if int(members) != (settings.member_count or 0):
        save_course_settings(ctx.store, ctx.club_id, CourseSettings(member_count=int(members) or None))
    stats = attendance_stats(active, int(members) or None)
    if stats["recorded"]:
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("平均出席", f"{stats['avg_attendance']:.1f} 人")
        m2.metric("平均出席率", f"{stats['attendance_rate']:.0%}" if stats["attendance_rate"] is not None else "—")
        m3.metric("新面孔", f"{stats['newcomers']} 人")
        m4.metric("平均滿意度", f"{stats['avg_rating']:.1f}／5" if stats["avg_rating"] is not None else "—")
        if stats["first_half"] and stats["second_half"] and stats["second_half"] < stats["first_half"] * 0.8:
            st.warning(f"後半學期平均出席（{stats['second_half']:.1f} 人）比前半（{stats['first_half']:.1f} 人）少超過兩成，"
                       "可以到「部門顧問」問問怎麼提升出席率。")
        recorded = [s for s in active if s.attendance is not None]
        if len(recorded) >= 2:
            st.caption("每堂出席人數")
            chart = pd.DataFrame({"日期": [s.date for s in recorded], "出席人數": [s.attendance for s in recorded]}).set_index("日期")
            st.line_chart(chart["出席人數"], color="#2D4A6B", height=220)

    st.markdown("**記錄出席與回饋**（不知道的可以空著）")
    df = pd.DataFrame({
        "id": pd.Series([s.id for s in active], dtype="object"),
        "日期": pd.Series([s.date for s in active], dtype="object"),
        "主題": pd.Series([s.title for s in active], dtype="object"),
        "出席人數": pd.Series([s.attendance for s in active], dtype="Int64"),
        "新面孔": pd.Series([s.newcomers for s in active], dtype="Int64"),
        "滿意度": pd.Series([s.rating for s in active], dtype="float"),
        "回饋重點": pd.Series([s.feedback for s in active], dtype="object"),
    })
    edited = st.data_editor(
        df, key=f"attendance_editor_{st.session_state.get('course_version', 0)}", hide_index=True, width="stretch",
        column_order=["日期", "主題", "出席人數", "新面孔", "滿意度", "回饋重點"], disabled=["日期", "主題"],
        column_config={
            "出席人數": st.column_config.NumberColumn(min_value=0, step=1),
            "新面孔": st.column_config.NumberColumn(min_value=0, step=1),
            "滿意度": st.column_config.NumberColumn(min_value=1.0, max_value=5.0, step=0.1, format="%.1f", help="回饋表單的平均分數（1–5）"),
        },
    )
    if st.button("儲存出席與回饋", type="primary", key="attendance_save"):
        by_id = {s.id: s for s in active}

        def number(v, kind=int):
            return None if v is None or pd.isna(v) else kind(v)

        for row in edited.to_dict("records"):
            s = by_id[row["id"]]
            attendance = number(row["出席人數"])
            status = "已完成" if attendance is not None and s.status in ("規劃中", "已確認") else s.status
            save_session(ctx.store, ctx.club_id, s.model_copy(update={
                "attendance": attendance, "newcomers": number(row["新面孔"]), "rating": number(row["滿意度"], float),
                "feedback": _text(row["回饋重點"]), "status": status,
            }))
        st.session_state.course_version = st.session_state.get("course_version", 0) + 1
        _flash("已儲存出席與回饋；有出席人數的社課改為「已完成」")

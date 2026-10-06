"""全社團行事曆：月曆檢視、本月行程列表、新增行程、匯出到 Google 日曆。"""

from __future__ import annotations

import calendar
import html
from datetime import date

import streamlit as st

from ..events import KINDS, SOURCE_MANUAL, CalendarEvent, club_events, delete_event, save_event, to_ics
from .context import AppContext

WEEK_HEADER = "一二三四五六日"
KIND_CLASS = {"活動": "ev-event", "會議": "ev-meeting", "截止": "ev-due", "其他": "ev-other"}
MAX_CHIPS = 3


def _shift_month(first: date, months: int) -> date:
    index = first.year * 12 + first.month - 1 + months
    return date(index // 12, index % 12 + 1, 1)


def _set_month(value: date) -> None:
    st.session_state.cal_month = value


def month_grid_html(month: date, events: list[CalendarEvent], today: date, dept_name) -> str:
    by_day: dict[str, list[CalendarEvent]] = {}
    for e in events:
        by_day.setdefault(e.date, []).append(e)
    head = "".join(f"<th>{d}</th>" for d in WEEK_HEADER)
    rows = []
    for week in calendar.Calendar(firstweekday=0).monthdatescalendar(month.year, month.month):
        cells = []
        for day in week:
            classes = ["cal-day"]
            if day.month != month.month:
                classes.append("cal-out")
            if day == today:
                classes.append("cal-today")
            day_events = by_day.get(day.isoformat(), [])
            chips = []
            for e in day_events[:MAX_CHIPS]:
                prefix = f"{e.time} " if e.time else ""
                dept = f"［{dept_name(e.department)}］" if e.department else ""
                tip = html.escape(f"{e.when()}｜{dept}{e.title}" + (f"｜{e.location}" if e.location else ""))
                chips.append(
                    f'<div class="cal-chip {KIND_CLASS.get(e.kind, "ev-other")}" title="{tip}">{html.escape(prefix + e.title)}</div>'
                )
            if len(day_events) > MAX_CHIPS:
                chips.append(f'<div class="cal-more">還有 {len(day_events) - MAX_CHIPS} 項</div>')
            cells.append(f'<td class="{" ".join(classes)}"><div class="cal-num">{day.day}</div>{"".join(chips)}</td>')
        rows.append(f"<tr>{''.join(cells)}</tr>")
    legend = "".join(f'<span class="cal-chip {cls}">{kind}</span>' for kind, cls in KIND_CLASS.items())
    return f'<div class="cal-wrap"><table class="cal"><thead><tr>{head}</tr></thead><tbody>{"".join(rows)}</tbody></table><div class="cal-legend">{legend}</div></div>'


def add_event_form(ctx: AppContext) -> None:
    with st.expander("新增行程"):
        with st.form("add_event", clear_on_submit=True, border=False):
            c1, c2, c3 = st.columns([3, 2, 2])
            title = c1.text_input("行程名稱＊", placeholder="例：期初社員大會、成果展、社課")
            day = c2.date_input("日期", value=date.today())
            kind = c3.selectbox("類型", KINDS)
            c4, c5, c6 = st.columns([2, 2, 3])
            start = c4.time_input("開始時間（整天可不填）", value=None, step=900)
            end = c5.time_input("結束時間（可不填）", value=None, step=900)
            options = ["", *ctx.settings.enabled_keys()]
            department = c6.selectbox("部門", options, index=options.index(ctx.dept_key),
                                      format_func=lambda k: ctx.settings.name(k) if k else "全社團")
            location = st.text_input("地點（選填）")
            note = st.text_input("備註（選填）")
            if st.form_submit_button("加入行事曆", type="primary"):
                if not title.strip():
                    st.warning("請填寫行程名稱")
                elif start and end and end <= start:
                    st.warning("結束時間要晚於開始時間")
                else:
                    save_event(
                        ctx.store,
                        ctx.club_id,
                        CalendarEvent(
                            date=day.isoformat(), title=title.strip(), time=f"{start:%H:%M}" if start else "",
                            end=f"{end:%H:%M}" if start and end else "", kind=kind, department=department,
                            location=location.strip(), note=note.strip(),
                        ),
                    )
                    st.success(f"已新增「{title.strip()}」（{day.isoformat()}）")


def event_list(ctx: AppContext, events: list[CalendarEvent]) -> None:
    if not events:
        st.caption("這個月沒有行程。")
        return
    for e in events:
        day = date.fromisoformat(e.date)
        dept = ctx.settings.name(e.department) if e.department else "全社團"
        extra = "｜".join(x for x in (e.location, e.note) if x)
        c1, c2 = st.columns([6, 1], vertical_alignment="center")
        c1.markdown(
            f"**{day.month}/{day.day}（{WEEK_HEADER[day.weekday()]}）{e.when()}**　{e.title}　"
            f":gray[{e.kind}｜{dept}｜{e.source}{'｜' + extra if extra else ''}]"
        )
        if e.source == SOURCE_MANUAL and c2.button("刪除", key=f"del_event_{e.id}", type="tertiary"):
            delete_event(ctx.store, ctx.club_id, e.id)
            st.rerun()


def calendar_page(ctx: AppContext) -> None:
    today = date.today()
    st.caption("集中全社團的行程：社長排好的幹部會議、會議記錄中提到的日期、待辦的期限，以及各部門自行新增的行程。")
    add_event_form(ctx)

    all_events = club_events(ctx.store, ctx.club_id, ctx.settings)
    month = st.session_state.get("cal_month") or today.replace(day=1)

    c_prev, c_title, c_next, c_today, c_filter = st.columns([1, 2, 1, 1, 4], vertical_alignment="center")
    c_prev.button("上個月", on_click=_set_month, args=(_shift_month(month, -1),), width="stretch")
    c_title.markdown(f"<div style='text-align:center;font-weight:600'>{month.year} 年 {month.month} 月</div>", unsafe_allow_html=True)
    c_next.button("下個月", on_click=_set_month, args=(_shift_month(month, 1),), width="stretch")
    c_today.button("本月", on_click=_set_month, args=(today.replace(day=1),), width="stretch")
    departments = c_filter.multiselect(
        "只看這些部門", ctx.settings.enabled_keys(), format_func=ctx.settings.name, key="cal_depts",
        placeholder="全部部門", label_visibility="collapsed",
    )
    show_tasks = st.toggle("顯示待辦期限", value=True, key="cal_tasks")

    events = [
        e for e in all_events
        if (not departments or not e.department or e.department in departments) and (show_tasks or e.kind != "截止")
    ]
    month_prefix = f"{month:%Y-%m}"
    month_events = [e for e in events if e.date.startswith(month_prefix)]
    st.markdown(month_grid_html(month, month_events, today, ctx.settings.name), unsafe_allow_html=True)

    st.markdown(f"**{month.month} 月行程（{len(month_events)}）**")
    event_list(ctx, month_events)

    future = [e for e in events if e.date >= today.isoformat()]
    st.download_button(
        f"匯出之後的行程到 Google 日曆（.ics，共 {len(future)} 項）",
        lambda: to_ics(future, f"{ctx.club.name} 行事曆", ctx.settings).encode("utf-8"),
        file_name="社團行事曆.ics",
        mime="text/calendar",
        icon=":material/calendar_month:",
        on_click="ignore",
        disabled=not future,
        help="Google 日曆：設定 → 匯入與匯出 → 選擇這個檔案。手機可直接開啟檔案加入行事曆。",
    )

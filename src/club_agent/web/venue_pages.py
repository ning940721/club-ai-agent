"""總務：場地申請（時程提醒、從活動建立）、器材借還、器材清單。"""

from __future__ import annotations

import io
from datetime import date, datetime, time, timedelta
from typing import Callable

import pandas as pd
import streamlit as st

from ..projects import list_projects
from ..venue import (
    BOOKING_STATUSES,
    CONDITIONS,
    Booking,
    Equipment,
    Loan,
    VenueSettings,
    apply_deadline,
    available,
    bookings_markdown,
    delete_booking,
    delete_equipment,
    get_venue_settings,
    list_bookings,
    list_equipment,
    list_loans,
    on_loan,
    save_booking,
    save_equipment,
    save_loan,
    save_venue_settings,
)
from .context import AppContext, download_buttons

XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _flash(message: str) -> None:
    st.session_state.venue_flash = message
    st.rerun()


def _text(value) -> str:
    return "" if value is None or (not isinstance(value, str) and pd.isna(value)) else str(value).strip()


def _time(text: str) -> time | None:
    try:
        return datetime.strptime(text, "%H:%M").time()
    except (TypeError, ValueError):
        return None


def venue_tabs(ctx: AppContext) -> list[tuple[str, Callable[[], None]]]:
    if message := st.session_state.pop("venue_flash", None):
        st.success(message)
    bookings = list_bookings(ctx.store, ctx.club_id)
    loans = list_loans(ctx.store, ctx.club_id)
    equipment = list_equipment(ctx.store, ctx.club_id)
    todo = sum(b.status == "待申請" for b in bookings)
    out = sum(x.outstanding for x in loans)
    return [
        (f"場地申請（{todo} 待申請）", lambda: bookings_tab(ctx, bookings)),
        (f"器材借還（{out} 借出中）", lambda: loans_tab(ctx, equipment, loans)),
        (f"器材清單（{len(equipment)}）", lambda: equipment_tab(ctx, equipment, loans)),
    ]


def venue_page(ctx: AppContext) -> None:
    """社長的「場地與器材」分頁：場地申請、器材借還、器材清單收在同一個分頁裡。"""
    tabs = venue_tabs(ctx)
    for tab, (_, render) in zip(st.tabs([name for name, _ in tabs]), tabs):
        with tab:
            render()


# ---------------------------------------------------------------------------
# 場地申請
# ---------------------------------------------------------------------------


def bookings_tab(ctx: AppContext, bookings: list[Booking]) -> None:
    today = date.today()
    settings = get_venue_settings(ctx.store, ctx.club_id)
    for b in bookings:
        if warning := b.apply_warning(today):
            st.warning(f"{warning}：{b.venue}（{b.date} 使用，{b.purpose or b.event or '未填用途'}），申請期限 {b.apply_by}")

    c1, c2 = st.columns([1, 3], vertical_alignment="bottom")
    lead = c1.number_input("場地要提前幾天申請", min_value=0, max_value=180, value=settings.lead_days, key="venue_lead")
    c2.caption("申請期限預設為使用日往前推這個天數，請依學校規定調整（例如課外組要求兩週前申請）。")
    if int(lead) != settings.lead_days:
        save_venue_settings(ctx.store, ctx.club_id, VenueSettings(lead_days=int(lead)))

    booked_events = {b.event for b in bookings if b.event}
    pending_projects = [p for p in list_projects(ctx.store, ctx.club_id)
                        if p.stage != "結案" and p.event_date() and p.event_date() >= today and p.name not in booked_events]
    if pending_projects:
        st.markdown("**還沒建立場地申請的活動**")
        for p in pending_projects:
            c1, c2 = st.columns([3, 1], vertical_alignment="center")
            c1.markdown(f"{p.name}｜{p.when()}｜{p.location or '地點未定'}")
            if c2.button("建立場地申請", key=f"venue_from_{p.id}"):
                use = p.event_date()
                save_booking(ctx.store, ctx.club_id, Booking(
                    venue=p.location or "【待補：場地】", purpose=p.name, event=p.name, date=use.isoformat(),
                    start=p.start_time, end=p.end_time, apply_by=max(apply_deadline(use, int(lead)), today).isoformat(), owner=p.owner,
                ))
                _flash(f"已為「{p.name}」建立場地申請，申請期限已加入行事曆")

    with st.expander("新增場地申請", expanded=not bookings):
        with st.form("booking_new", clear_on_submit=True, border=False):
            c1, c2 = st.columns(2)
            venue = c1.text_input("場地＊", placeholder="例：學生活動中心 B1 演藝廳")
            purpose = c2.text_input("用途", placeholder="例：期初社員大會")
            c3, c4, c5, c6 = st.columns(4)
            use = c3.date_input("使用日期", value=today + timedelta(days=int(lead) + 7))
            start = c4.time_input("開始", value=time(18, 0), step=900)
            end = c5.time_input("結束", value=time(21, 0), step=900)
            apply_by = c6.date_input("申請期限（空白則自動計算）", value=None)
            c7, c8 = st.columns(2)
            owner = c7.text_input("負責人")
            note = c8.text_input("備註", placeholder="例：需要投影機、借用 50 張椅子")
            if st.form_submit_button("新增", type="primary"):
                if not venue.strip():
                    st.warning("請填寫場地")
                else:
                    deadline = apply_by or max(apply_deadline(use, int(lead)), today)
                    save_booking(ctx.store, ctx.club_id, Booking(
                        venue=venue.strip(), purpose=purpose.strip(), date=use.isoformat(), start=f"{start:%H:%M}", end=f"{end:%H:%M}",
                        apply_by=deadline.isoformat(), owner=owner.strip(), note=note.strip(),
                    ))
                    _flash(f"已新增「{venue.strip()}」，申請期限 {deadline.isoformat()}")

    if not bookings:
        return
    show_closed = st.toggle("顯示未核准與取消的申請", key="venue_closed")
    for b in bookings:
        if b.status in ("未核准", "取消") and not show_closed:
            continue
        with st.expander(f"{b.status}｜{b.date} {b.start}｜{b.venue}｜{b.purpose or b.event or ''}"):
            with st.form(f"booking_edit_{b.id}", border=False):
                c1, c2, c3 = st.columns(3)
                status = c1.selectbox("狀態", BOOKING_STATUSES, index=BOOKING_STATUSES.index(b.status) if b.status in BOOKING_STATUSES else 0)
                venue = c2.text_input("場地", value=b.venue)
                owner = c3.text_input("負責人", value=b.owner)
                c4, c5, c6, c7 = st.columns(4)
                use = c4.date_input("使用日期", value=date.fromisoformat(b.date))
                start = c5.time_input("開始", value=_time(b.start), step=900)
                end = c6.time_input("結束", value=_time(b.end), step=900)
                apply_by = c7.date_input("申請期限", value=date.fromisoformat(b.apply_by) if b.apply_by else None)
                note = st.text_input("備註", value=b.note)
                if st.form_submit_button("儲存"):
                    save_booking(ctx.store, ctx.club_id, b.model_copy(update={
                        "status": status, "venue": venue.strip() or b.venue, "owner": owner.strip(), "date": use.isoformat(),
                        "start": f"{start:%H:%M}" if start else "", "end": f"{end:%H:%M}" if end else "",
                        "apply_by": apply_by.isoformat() if apply_by else "", "note": note.strip(),
                    }))
                    _flash("已儲存")
            if st.button("刪除", key=f"booking_del_{b.id}", type="tertiary"):
                delete_booking(ctx.store, ctx.club_id, b.id)
                _flash("已刪除")
    md = bookings_markdown(ctx.club.name, bookings)
    download_buttons(md, "場地申請一覽", "bookings")


# ---------------------------------------------------------------------------
# 器材借還
# ---------------------------------------------------------------------------


def loans_tab(ctx: AppContext, equipment: list[Equipment], loans: list[Loan]) -> None:
    today = date.today()
    for x in loans:
        if x.is_overdue(today):
            st.warning(f"逾期未還：{x.equipment_name} × {x.quantity}（{x.borrower}，應於 {x.due} 歸還）")
    if not equipment:
        st.info("先到「器材清單」建立社團的器材，才能登記借用。")
        return
    lendable = [e for e in equipment if available(e, loans) > 0]
    with st.expander("登記借用", expanded=True):
        if not lendable:
            st.caption("目前所有器材都已借出。")
        else:
            with st.form("loan_new", clear_on_submit=True, border=False):
                by_id = {e.id: e for e in lendable}
                c1, c2, c3 = st.columns([3, 2, 1])
                eid = c1.selectbox("器材", list(by_id), format_func=lambda i: f"{by_id[i].name}（可借 {available(by_id[i], loans)}）")
                borrower = c2.text_input("借用人＊")
                qty = c3.number_input("數量", min_value=1, value=1, step=1)
                c4, c5, c6 = st.columns(3)
                departments = ctx.settings.enabled_keys()
                dept = c4.selectbox("部門", departments, index=departments.index(ctx.dept_key), format_func=ctx.settings.name)
                due = c5.date_input("歸還期限", value=today + timedelta(days=7))
                note = c6.text_input("備註", placeholder="例：外拍活動用")
                if st.form_submit_button("借出", type="primary"):
                    e = by_id[eid]
                    if not borrower.strip():
                        st.warning("請填寫借用人")
                    elif int(qty) > available(e, loans):
                        st.error(f"{e.name} 只剩 {available(e, loans)} 個可借")
                    else:
                        save_loan(ctx.store, ctx.club_id, Loan(
                            equipment_id=e.id, equipment_name=e.name, borrower=borrower.strip(), department=dept,
                            quantity=int(qty), due=due.isoformat(), note=note.strip(),
                        ))
                        _flash(f"已登記：{borrower.strip()} 借用 {e.name} × {int(qty)}，{due.isoformat()} 前歸還")

    outstanding = [x for x in loans if x.outstanding]
    st.markdown(f"**借出中（{len(outstanding)}）**")
    if not outstanding:
        st.caption("目前沒有借出的器材。")
    for x in outstanding:
        c1, c2 = st.columns([4, 1], vertical_alignment="center")
        late = "　:red[逾期]" if x.is_overdue(today) else ""
        c1.markdown(f"{x.equipment_name} × {x.quantity}｜{x.borrower}（{ctx.settings.name(x.department)}）｜借出 {x.borrowed}，"
                    f"應還 {x.due or '未定'}{late}")
        if c2.button("已歸還", key=f"loan_return_{x.id}"):
            save_loan(ctx.store, ctx.club_id, x.model_copy(update={"returned": today.isoformat()}))
            _flash(f"已歸還：{x.equipment_name} × {x.quantity}")
    returned = [x for x in loans if not x.outstanding]
    if returned:
        with st.expander(f"借還紀錄（{len(returned)}）"):
            st.dataframe(pd.DataFrame({
                "器材": [x.equipment_name for x in returned], "數量": [x.quantity for x in returned],
                "借用人": [x.borrower for x in returned], "部門": [ctx.settings.name(x.department) for x in returned],
                "借出": [x.borrowed for x in returned], "應還": [x.due for x in returned], "歸還": [x.returned for x in returned],
            }), hide_index=True, width="stretch")


# ---------------------------------------------------------------------------
# 器材清單
# ---------------------------------------------------------------------------


def equipment_tab(ctx: AppContext, equipment: list[Equipment], loans: list[Loan]) -> None:
    st.caption("社團的器材與數量；「借出中」由借還紀錄自動計算。在表格最下方新增一列可以加器材，勾選「刪除」後儲存。")
    df = pd.DataFrame({
        "id": pd.Series([e.id for e in equipment], dtype="object"),
        "名稱": pd.Series([e.name for e in equipment], dtype="object"),
        "數量": pd.Series([e.quantity for e in equipment], dtype="int64"),
        "借出中": pd.Series([on_loan(e.id, loans) for e in equipment], dtype="int64"),
        "存放位置": pd.Series([e.location for e in equipment], dtype="object"),
        "狀況": pd.Series([e.condition for e in equipment], dtype="object"),
        "備註": pd.Series([e.note for e in equipment], dtype="object"),
        "刪除": pd.Series([False for _ in equipment], dtype="bool"),
    })
    edited = st.data_editor(
        df, key=f"equipment_editor_{st.session_state.get('equipment_version', 0)}", num_rows="dynamic", hide_index=True, width="stretch",
        column_order=["名稱", "數量", "借出中", "存放位置", "狀況", "備註", "刪除"], disabled=["借出中"],
        column_config={
            "數量": st.column_config.NumberColumn(min_value=0, step=1, default=1),
            "狀況": st.column_config.SelectboxColumn(options=list(CONDITIONS), default="良好"),
        },
    )
    if st.button("儲存器材清單", type="primary", key="equipment_save"):
        by_id = {e.id: e for e in equipment}
        saved, removed, blocked = 0, 0, []
        for row in edited.to_dict("records"):
            eid = _text(row.get("id"))
            if row.get("刪除") and eid in by_id:
                if on_loan(eid, loans):
                    blocked.append(by_id[eid].name)
                    continue
                delete_equipment(ctx.store, ctx.club_id, eid)
                removed += 1
                continue
            if not _text(row.get("名稱")):
                continue
            quantity = row.get("數量")
            base = by_id.get(eid) or Equipment(name="")
            save_equipment(ctx.store, ctx.club_id, base.model_copy(update={
                "name": _text(row["名稱"]), "quantity": 1 if quantity is None or pd.isna(quantity) else int(quantity),
                "location": _text(row.get("存放位置")), "condition": _text(row.get("狀況")) or "良好", "note": _text(row.get("備註")),
            }))
            saved += 1
        st.session_state.equipment_version = st.session_state.get("equipment_version", 0) + 1
        message = f"已儲存 {saved} 項器材" + (f"、刪除 {removed} 項" if removed else "")
        if blocked:
            message += f"；{'、'.join(blocked)} 還有借出未還，先登記歸還才能刪除"
        _flash(message)

    if equipment:
        def excel() -> bytes:
            buffer = io.BytesIO()
            with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
                df.drop(columns=["id", "刪除"]).assign(可借=[available(e, loans) for e in equipment]).to_excel(writer, sheet_name="器材清單", index=False)
            return buffer.getvalue()

        st.download_button("下載器材清單 Excel", excel, file_name="器材清單.xlsx", mime=XLSX_MIME, icon=":material/table_view:",
                           on_click="ignore", key="equipment_xlsx")

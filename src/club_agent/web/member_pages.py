"""人資／社員：社員名單、招生與面試（AI 面試題目）、幹部交接手冊（AI 整理部門紀錄）。"""

from __future__ import annotations

import io
from datetime import date, datetime, time
from typing import Callable

import pandas as pd
import streamlit as st

from ..agents import PeopleAdvisor
from ..events import club_events
from ..meetings import list_meetings
from ..members import (
    MEMBER_STATUSES,
    RESULTS,
    ROLES,
    Applicant,
    Member,
    admitted_to_members,
    by_source,
    current_term,
    delete_applicant,
    delete_member,
    funnel,
    list_applicants,
    list_members,
    member_stats,
    parse_members_csv,
    save_applicant,
    save_member,
)
from ..metrics import decode_csv_bytes
from ..report import handover_markdown, interview_kit_markdown
from ..tasks import list_tasks
from .context import AppContext, download_buttons

XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _flash(message: str) -> None:
    st.session_state.member_flash = message
    st.rerun()


def _text(value) -> str:
    return "" if value is None or (not isinstance(value, str) and pd.isna(value)) else str(value).strip()


def member_tabs(ctx: AppContext) -> list[tuple[str, Callable[[], None]]]:
    if message := st.session_state.pop("member_flash", None):
        st.success(message)
    members = list_members(ctx.store, ctx.club_id)
    applicants = list_applicants(ctx.store, ctx.club_id)
    return [
        (f"社員名單（{sum(m.status == '在籍' for m in members)}）", lambda: roster_tab(ctx, members)),
        (f"招生與面試（{len(applicants)}）", lambda: recruiting_tab(ctx, applicants, members)),
        ("交接手冊", lambda: handover_tab(ctx)),
    ]


# ---------------------------------------------------------------------------
# 社員名單
# ---------------------------------------------------------------------------


def roster_tab(ctx: AppContext, members: list[Member]) -> None:
    term = current_term()
    st.caption("只記錄社團經營需要的資料；請不要記錄學號、身分證字號等敏感個資，聯絡方式也可以不填。")
    stats = member_stats(members, term)
    cols = st.columns(4)
    for col, (label, value) in zip(cols, stats.items()):
        col.metric(label, value)

    with st.expander("從 CSV 匯入名單（例如社博報名表、Google 表單回覆）"):
        uploaded = st.file_uploader("上傳 CSV（只有姓名必填，其他欄位會自動對應）", type="csv", key="member_import")
        if uploaded is not None:
            try:
                new, mapping = parse_members_csv(decode_csv_bytes(uploaded.getvalue()), term)
            except ValueError as e:
                st.error(str(e))
                new, mapping = [], []
            if new:
                existing = {m.name for m in members}
                fresh = [m for m in new if m.name not in existing]
                st.caption(f"讀到 {len(new)} 人，其中 {len(new) - len(fresh)} 人已在名單中會略過。欄位對應：{'、'.join(mapping)}")
                if fresh and st.button(f"匯入 {len(fresh)} 人", type="primary", key="member_import_go"):
                    for m in fresh:
                        save_member(ctx.store, ctx.club_id, m)
                    st.session_state.member_version = st.session_state.get("member_version", 0) + 1
                    _flash(f"已匯入 {len(fresh)} 位社員")

    departments = ["", *ctx.settings.enabled_keys()]
    df = pd.DataFrame({
        "id": pd.Series([m.id for m in members], dtype="object"),
        "姓名": pd.Series([m.name for m in members], dtype="object"),
        "系級": pd.Series([m.major for m in members], dtype="object"),
        "入社學期": pd.Series([m.joined for m in members], dtype="object"),
        "身分": pd.Series([m.role for m in members], dtype="object"),
        "部門": pd.Series([ctx.settings.name(m.department) if m.department else "" for m in members], dtype="object"),
        "聯絡方式": pd.Series([m.contact for m in members], dtype="object"),
        "狀態": pd.Series([m.status for m in members], dtype="object"),
        "備註": pd.Series([m.note for m in members], dtype="object"),
        "刪除": pd.Series([False for _ in members], dtype="bool"),
    })
    dept_names = {ctx.settings.name(k): k for k in departments if k}
    st.markdown("**名單**（可以直接修改；在最下方新增一列可以加人；勾選「刪除」後儲存）")
    edited = st.data_editor(
        df, key=f"member_editor_{st.session_state.get('member_version', 0)}", num_rows="dynamic", hide_index=True, width="stretch",
        column_order=["姓名", "系級", "入社學期", "身分", "部門", "聯絡方式", "狀態", "備註", "刪除"],
        column_config={
            "入社學期": st.column_config.TextColumn(default=term, help="例如 2026 上、2026 下"),
            "身分": st.column_config.SelectboxColumn(options=list(ROLES), default="社員"),
            "部門": st.column_config.SelectboxColumn(options=["", *dept_names], help="幹部所屬的部門"),
            "狀態": st.column_config.SelectboxColumn(options=list(MEMBER_STATUSES), default="在籍"),
        },
    )
    if st.button("儲存名單", type="primary", key="member_save"):
        by_id = {m.id: m for m in members}
        saved = removed = 0
        for row in edited.to_dict("records"):
            mid = _text(row.get("id"))
            if row.get("刪除") and mid in by_id:
                delete_member(ctx.store, ctx.club_id, mid)
                removed += 1
                continue
            if not _text(row.get("姓名")):
                continue
            base = by_id.get(mid) or Member(name="")
            save_member(ctx.store, ctx.club_id, base.model_copy(update={
                "name": _text(row["姓名"]), "major": _text(row.get("系級")), "joined": _text(row.get("入社學期")) or term,
                "role": _text(row.get("身分")) or "社員", "department": dept_names.get(_text(row.get("部門")), ""),
                "contact": _text(row.get("聯絡方式")), "status": _text(row.get("狀態")) or "在籍", "note": _text(row.get("備註")),
            }))
            saved += 1
        st.session_state.member_version = st.session_state.get("member_version", 0) + 1
        _flash(f"已儲存 {saved} 人" + (f"、刪除 {removed} 人" if removed else ""))

    if members:
        def excel() -> bytes:
            buffer = io.BytesIO()
            with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
                df.drop(columns=["id", "刪除"]).to_excel(writer, sheet_name="社員名單", index=False)
            return buffer.getvalue()

        st.download_button("下載名單 Excel", excel, file_name="社員名單.xlsx", mime=XLSX_MIME, icon=":material/table_view:",
                           on_click="ignore", key="member_xlsx")


# ---------------------------------------------------------------------------
# 招生與面試
# ---------------------------------------------------------------------------


def recruiting_tab(ctx: AppContext, applicants: list[Applicant], members: list[Member]) -> None:
    if applicants:
        stats = funnel(applicants)
        cols = st.columns(3)
        for col, (label, value) in zip(cols, stats.items()):
            col.metric(label, value)
        sources = by_source(applicants)
        if len(sources) > 1:
            st.caption("招生管道：" + "｜".join(f"{s} 報名 {n}、錄取 {ok}" for s, n, ok in sources))

    with st.expander("新增報名者", expanded=not applicants):
        with st.form("applicant_new", clear_on_submit=True, border=False):
            c1, c2, c3 = st.columns(3)
            name = c1.text_input("姓名＊")
            major = c2.text_input("系級")
            source = c3.text_input("從哪裡知道社團", placeholder="例：社博、IG、朋友介紹")
            c4, c5, c6, c7 = st.columns(4)
            role = c4.text_input("應徵", value="社員", help="社員，或某個幹部職位，例如：行銷部員")
            day = c5.date_input("面試日期（選填）", value=None)
            at = c6.time_input("面試時間", value=None, step=900)
            interviewer = c7.text_input("面試官")
            if st.form_submit_button("新增", type="primary"):
                if not name.strip():
                    st.warning("請填寫姓名")
                else:
                    save_applicant(ctx.store, ctx.club_id, Applicant(
                        name=name.strip(), major=major.strip(), source=source.strip(), role=role.strip() or "社員",
                        interview_date=day.isoformat() if day else "", interview_time=f"{at:%H:%M}" if at else "",
                        interviewer=interviewer.strip(),
                    ))
                    st.session_state.applicant_version = st.session_state.get("applicant_version", 0) + 1
                    _flash(f"已新增報名者「{name.strip()}」" + ("，面試時間已加入行事曆" if day else ""))

    if applicants:
        df = pd.DataFrame({
            "id": pd.Series([a.id for a in applicants], dtype="object"),
            "姓名": pd.Series([a.name for a in applicants], dtype="object"),
            "應徵": pd.Series([a.role for a in applicants], dtype="object"),
            "管道": pd.Series([a.source for a in applicants], dtype="object"),
            "面試日期": pd.Series([date.fromisoformat(a.interview_date) if a.interview_date else None for a in applicants], dtype="object"),
            "面試時間": pd.Series([datetime.strptime(a.interview_time, "%H:%M").time() if a.interview_time else None for a in applicants], dtype="object"),
            "面試官": pd.Series([a.interviewer for a in applicants], dtype="object"),
            "結果": pd.Series([a.result for a in applicants], dtype="object"),
            "備註": pd.Series([a.note for a in applicants], dtype="object"),
            "刪除": pd.Series([False for _ in applicants], dtype="bool"),
        })
        edited = st.data_editor(
            df, key=f"applicant_editor_{st.session_state.get('applicant_version', 0)}", hide_index=True, width="stretch",
            column_order=["姓名", "應徵", "管道", "面試日期", "面試時間", "面試官", "結果", "備註", "刪除"],
            column_config={
                "面試日期": st.column_config.DateColumn(format="YYYY-MM-DD"),
                "面試時間": st.column_config.TimeColumn(format="HH:mm", step=900),
                "結果": st.column_config.SelectboxColumn(options=list(RESULTS), required=True),
            },
        )
        c1, c2 = st.columns(2)
        if c1.button("儲存", type="primary", key="applicant_save"):
            by_id = {a.id: a for a in applicants}
            for row in edited.to_dict("records"):
                a = by_id[row["id"]]
                if row.get("刪除"):
                    delete_applicant(ctx.store, ctx.club_id, a.id)
                    continue
                d, t = row.get("面試日期"), row.get("面試時間")
                save_applicant(ctx.store, ctx.club_id, a.model_copy(update={
                    "name": _text(row["姓名"]) or a.name, "role": _text(row.get("應徵")) or a.role, "source": _text(row.get("管道")),
                    "interview_date": d.isoformat() if isinstance(d, date) else "",
                    "interview_time": f"{t:%H:%M}" if isinstance(t, time) else "",
                    "interviewer": _text(row.get("面試官")), "result": _text(row.get("結果")) or a.result, "note": _text(row.get("備註")),
                }))
            st.session_state.applicant_version = st.session_state.get("applicant_version", 0) + 1
            _flash("已儲存報名者資料")
        new_members = admitted_to_members(applicants, members, current_term())
        if new_members and c2.button(f"把 {len(new_members)} 位錄取者加入社員名單", key="admit"):
            for m in new_members:
                save_member(ctx.store, ctx.club_id, m)
            st.session_state.member_version = st.session_state.get("member_version", 0) + 1
            _flash(f"已加入 {len(new_members)} 位社員：{'、'.join(m.name for m in new_members)}")

    st.divider()
    st.markdown("**AI 面試題目與評分標準**")
    c1, c2 = st.columns([1, 2])
    role = c1.text_input("職位", value="社員", key="kit_role", placeholder="例：社員、行銷部員、副社長")
    extra = c2.text_input("補充（選填）", key="kit_extra", placeholder="例：面試時間 10 分鐘；想找能長期投入的人")
    if st.button("產生面試題目", key="kit_go"):
        dept_key = next((k for k in ctx.settings.enabled_keys() if ctx.settings.name(k) in role), "")
        kit = ctx.run_ai("設計面試題目中…", lambda llm, _s: PeopleAdvisor(llm).interview_kit(
            ctx.club, role.strip() or "社員", ctx.settings.details(dept_key) if dept_key else "", extra), thinking="minimal")
        if kit:
            st.session_state.interview_kit = (role.strip() or "社員", kit)
    if saved := st.session_state.get("interview_kit"):
        md = interview_kit_markdown(ctx.club.name, saved[0], saved[1])
        st.markdown(md)
        download_buttons(md, f"面試題目_{saved[0]}", "interview_kit")


# ---------------------------------------------------------------------------
# 交接手冊
# ---------------------------------------------------------------------------


def handover_digest(ctx: AppContext, dept_key: str) -> str:
    """把一個部門的紀錄整理給 AI：部門細節、待辦、分享的成果、會議決議與待辦、行事曆。"""
    name = ctx.settings.name(dept_key)
    lines = [f"[部門細節]\n{ctx.settings.details(dept_key) or '（未填寫）'}"]
    tasks = list_tasks(ctx.store, ctx.club_id, dept_key)
    if tasks:
        lines.append("\n[待辦與進度]")
        lines += [f"- {t.status}｜{t.title}（{t.owner or '未指定'}，期限 {t.due or '無'}{'，逾期' if t.is_overdue() else ''}）" for t in tasks[:60]]
    records = ctx.store.list_records(ctx.club_id, department=dept_key, limit=30)
    if records:
        lines.append("\n[這個部門分享過的成果]")
        lines += [f"- {r.created_at[:10]}｜{r.title}：{r.summary}" for r in records]
    meeting_lines = []
    for doc in list_meetings(ctx.store, ctx.club_id)[:20]:
        if doc.summary:
            items = [a for a in doc.summary.action_items if a.department == dept_key]
            meeting_lines += [f"- {doc.date}｜決議：{d}" for d in doc.summary.decisions if name in d]
            meeting_lines += [f"- {doc.date}｜交辦：{a.task}（{a.owner or '未指定'}）" for a in items]
    if meeting_lines:
        lines.append("\n[會議中和這個部門有關的決議與交辦]")
        lines += meeting_lines[:40]
    events = [e for e in club_events(ctx.store, ctx.club_id, ctx.settings) if e.department == dept_key]
    if events:
        lines.append("\n[行事曆]")
        lines += [f"- {e.date}｜{e.kind}｜{e.title}" for e in events[-60:]]
    return "\n".join(lines)


def handover_tab(ctx: AppContext) -> None:
    st.caption("選擇部門，AI 會從這個部門的待辦、分享的成果、會議決議與行事曆整理交接手冊，讓下一屆快速上手。"
               "紀錄越完整，手冊越具體；帳號密碼不會寫進手冊。")
    keys = ctx.settings.enabled_keys()
    c1, c2 = st.columns([1, 2])
    dept_key = c1.selectbox("部門", keys, format_func=ctx.settings.name, key="handover_dept")
    extra = c2.text_input("想補充的經驗（選填）", key="handover_extra", placeholder="例：成果展場地要在兩個月前借；廠商 A 很好合作")
    col_btn, col_share = st.columns([1, 3], vertical_alignment="center")
    clicked = col_btn.button("產生交接手冊", type="primary", key="handover_go")
    with col_share:
        share = ctx.share_toggle("handover")
    if clicked:
        name = ctx.settings.name(dept_key)
        digest = handover_digest(ctx, dept_key)
        manual = ctx.run_ai("整理交接手冊中…", lambda llm, _s: PeopleAdvisor(llm).handover(ctx.club, name, digest, extra))
        if manual:
            md = handover_markdown(ctx.club.name, name, manual)
            st.session_state.handover_md = (dept_key, md)
            ctx.keep_result("handover", "handover", f"{name}交接手冊", manual.overview[:150], md, share, dept_key)
    if (saved := st.session_state.get("handover_md")) and saved[0] == dept_key:
        st.divider()
        st.markdown(saved[1])
        download_buttons(saved[1], f"{ctx.settings.name(dept_key)}交接手冊", f"handover_{dept_key}")
        ctx.share_controls("handover")


# ---------------------------------------------------------------------------
# 交接資料包（社長）
# ---------------------------------------------------------------------------


def handover_pack_page(ctx: AppContext) -> None:
    """整理全社團各部門的資料成一個 ZIP（Word／Excel／行事曆），可選擇同時用 AI 產生各部門交接手冊。"""
    from ..handover_export import build_handover_zip

    st.caption("把全社團的資料整理成一個 ZIP：待辦、行事曆、會議記錄、各部門分享的成果、活動企劃與成果報告、講座、合作對象、"
               "行銷數據與設計、社課、器材、社員名單等，依部門分資料夾，用 Word／Excel 就能打開。適合學期末交接或備份。")
    finance_open = st.session_state.get("finance_unlocked") == ctx.club_id
    c1, c2 = st.columns(2)
    include_finance = c1.checkbox("包含財務資料（學期報表、報帳規範）", value=False, disabled=not finance_open, key="pack_finance",
                                  help=None if finance_open else "請先到「財務管理」輸入財務密碼")
    include_contacts = c2.checkbox("包含社員聯絡方式（個資，請小心保管）", value=False, key="pack_contacts")
    if not finance_open:
        st.caption("財務資料需要先在「財務管理」輸入財務密碼才能包含。")
    with_manuals = st.checkbox("同時用 AI 產生各部門的交接手冊", value=False, key="pack_manuals",
                               help="每個部門呼叫一次 AI，部門多時需要幾分鐘")
    chosen: list[str] = []
    if with_manuals:
        keys = ctx.settings.enabled_keys()
        chosen = st.multiselect("要產生交接手冊的部門", keys, default=keys, format_func=ctx.settings.name, key="pack_depts")
        remaining = ctx.max_runs - st.session_state.get("runs", 0)
        if len(chosen) > remaining:
            st.warning(f"這次登入只剩 {remaining} 次 AI 使用額度，請減少部門數量，或重新整理頁面後再試。")
    if st.button("整理交接資料包", type="primary", key="pack_go"):
        manuals = {}
        for key in chosen:
            name = ctx.settings.name(key)
            digest = handover_digest(ctx, key)
            manual = ctx.run_ai(f"整理{name}交接手冊中…", lambda llm, _s, n=name, d=digest: PeopleAdvisor(llm).handover(ctx.club, n, d))
            if manual:
                manuals[key] = handover_markdown(ctx.club.name, name, manual)
        with st.spinner("整理檔案中…"):
            data, files = build_handover_zip(ctx.store, ctx.club_id, ctx.club, ctx.settings, include_finance=include_finance,
                                             include_contacts=include_contacts, manuals=manuals)
        st.session_state.handover_zip = (data, files, f"{ctx.club.name}_交接資料_{date.today():%Y%m%d}.zip")
    if saved := st.session_state.get("handover_zip"):
        data, files, filename = saved
        st.success(f"已整理 {len(files)} 個檔案（{len(data) / 1024:,.0f} KB）")
        st.download_button("下載交接資料包（ZIP）", data, file_name=filename, mime="application/zip", type="primary",
                           icon=":material/folder_zip:", on_click="ignore", key="pack_download")
        with st.expander("資料包裡有哪些檔案"):
            root = files[0].split("/")[0] if files else ""
            st.text("\n".join(f.removeprefix(root + "/") for f in files))

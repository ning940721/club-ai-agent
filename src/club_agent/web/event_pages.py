"""活動部門：活動專案（總覽、企劃書、籌備清單、細流與工作人員、回饋表單、成果報告）。"""

from __future__ import annotations

import io
from datetime import date, datetime, time
from typing import Callable

import pandas as pd
import streamlit as st

from ..agents import EventPlanner
from ..departments import department_retriever
from ..export import ExportError, pdf_available
from ..finance import get_settings as finance_settings
from ..finance import list_requests
from ..projects import (
    STAGES,
    EventProject,
    StaffMember,
    actual_spending,
    badges_pdf,
    delete_project,
    feedback_markdown,
    google_form_text,
    list_projects,
    prep_tasks_to_tasks,
    proposal_markdown,
    report_markdown,
    rundown_markdown,
    save_project,
)
from ..schemas import BudgetLine, RundownItem
from ..tasks import list_tasks, save_task
from .common_pages import add_task_form, tasks_table
from .context import AppContext, download_buttons

XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@st.cache_resource
def _events_retriever():
    return department_retriever("events")


def _flash(message: str) -> None:
    st.session_state.event_flash = message
    st.rerun()


def _text(value) -> str:
    return "" if value is None or (not isinstance(value, str) and pd.isna(value)) else str(value).strip()


def _time(text: str) -> time | None:
    try:
        return datetime.strptime(text, "%H:%M").time()
    except (TypeError, ValueError):
        return None


def event_tabs(ctx: AppContext) -> list[tuple[str, Callable[[], None]]]:
    """活動部門的分頁。活動選單與「新增活動」放在分頁上方，所有分頁都針對目前選擇的活動。"""
    if message := st.session_state.pop("event_flash", None):
        st.success(message)
    projects = list_projects(ctx.store, ctx.club_id)
    c1, c2 = st.columns([3, 1], vertical_alignment="bottom")
    with c2.popover("新增活動", icon=":material/add:", width="stretch"):
        new_project_form(ctx)
    if not projects:
        c1.info("還沒有活動，按右邊「新增活動」建立第一個活動專案。")
        return []
    ids = [p.id for p in projects]
    by_id = {p.id: p for p in projects}
    if st.session_state.get("event_project") not in ids:
        st.session_state.event_project = ids[0]
    pid = c1.selectbox("活動", ids, format_func=lambda i: f"{by_id[i].stage}｜{by_id[i].name}｜{by_id[i].when()}", key="event_project")
    p = by_id[pid]
    return [
        ("活動總覽", lambda: overview_tab(ctx, p)),
        ("企劃書", lambda: proposal_tab(ctx, p)),
        ("籌備清單", lambda: prep_tab(ctx, p)),
        ("細流與工作人員", lambda: rundown_tab(ctx, p)),
        ("回饋表單", lambda: feedback_tab(ctx, p)),
        ("成果報告", lambda: report_tab(ctx, p)),
    ]


# ---------------------------------------------------------------------------
# 基本資料
# ---------------------------------------------------------------------------


def project_fields(prefix: str, p: EventProject | None) -> dict:
    p = p or EventProject(name="")
    name = st.text_input("活動名稱＊", value=p.name, placeholder="例：期末成果展", key=f"{prefix}_name",
                         help="報帳時「所屬活動」填這個名稱，成果報告才能帶入實際支出")
    c1, c2, c3, c4 = st.columns(4)
    day = c1.date_input("日期", value=p.event_date(), key=f"{prefix}_date")
    start = c2.time_input("開始時間", value=_time(p.start_time), step=900, key=f"{prefix}_start")
    end = c3.time_input("結束時間", value=_time(p.end_time), step=900, key=f"{prefix}_end")
    stage = c4.selectbox("階段", STAGES, index=STAGES.index(p.stage) if p.stage in STAGES else 0, key=f"{prefix}_stage")
    c5, c6, c7, c8 = st.columns(4)
    location = c5.text_input("地點", value=p.location, key=f"{prefix}_loc")
    people = c6.number_input("預計人數", min_value=0, step=10, value=p.expected_people, key=f"{prefix}_people")
    budget = c7.number_input("總預算（元）", min_value=0, step=500, value=p.budget, key=f"{prefix}_budget")
    owner = c8.text_input("總召／負責人", value=p.owner, key=f"{prefix}_owner")
    goal = st.text_input("活動目的", value=p.goal, placeholder="例：展示社員作品、吸引 100 位非社員參觀", key=f"{prefix}_goal")
    description = st.text_area("活動構想", value=p.description, height=90,
                               placeholder="例：在學活中心展出 30 件作品，搭配底片體驗攤位與講者分享", key=f"{prefix}_desc")
    return {
        "name": name.strip(), "date": day.isoformat() if day else "", "start_time": f"{start:%H:%M}" if start else "",
        "end_time": f"{end:%H:%M}" if end else "", "stage": stage, "location": location.strip(), "expected_people": int(people),
        "budget": int(budget), "owner": owner.strip(), "goal": goal.strip(), "description": description.strip(),
    }


def new_project_form(ctx: AppContext) -> None:
    with st.form("event_new", clear_on_submit=True, border=False):
        data = project_fields("en", None)
        if st.form_submit_button("建立活動", type="primary"):
            if not data["name"]:
                st.warning("請填寫活動名稱")
            else:
                p = EventProject(**data)
                save_project(ctx.store, ctx.club_id, p)
                st.session_state.event_project = p.id
                _flash(f"已建立「{p.name}」，下一步可以到「企劃書」產生企劃")


def overview_tab(ctx: AppContext, p: EventProject) -> None:
    tasks = [t for t in list_tasks(ctx.store, ctx.club_id) if t.project == p.id]
    done = sum(t.status == "完成" for t in tasks)
    overdue = sum(t.is_overdue() for t in tasks)
    planned = sum(b.amount for b in p.budget_lines) or p.budget
    m1, m2, m3, m4 = st.columns(4)
    days = (p.event_date() - date.today()).days if p.event_date() else None
    m1.metric("距離活動", f"{days} 天" if days is not None and days >= 0 else ("已結束" if days is not None else "未定"))
    m2.metric("籌備進度", f"{done}/{len(tasks)}" if tasks else "—")
    m3.metric("逾期工作", overdue)
    m4.metric("預算", f"{planned:,}" if planned else "—")
    with st.form(f"event_edit_{p.id}", border=False):
        data = project_fields(f"ee_{p.id}", p)
        if st.form_submit_button("儲存變更", type="primary"):
            if not data["name"]:
                st.warning("活動名稱不能空白")
            else:
                save_project(ctx.store, ctx.club_id, p.model_copy(update=data))
                _flash("已儲存")
    with st.popover("刪除這個活動"):
        st.caption("刪除後企劃書、細流、報告都會消失；籌備清單的待辦會保留。")
        if st.button("確定刪除", key=f"event_del_{p.id}", type="primary"):
            delete_project(ctx.store, ctx.club_id, p.id)
            st.session_state.pop("event_project", None)
            _flash(f"已刪除「{p.name}」")


# ---------------------------------------------------------------------------
# 企劃書
# ---------------------------------------------------------------------------


def proposal_tab(ctx: AppContext, p: EventProject) -> None:
    st.caption("AI 依總覽的活動資訊撰寫企劃書，包含流程、預算、人力、宣傳、籌備時程與風險應變。資訊越完整越準確，未知的部分會標示【待補】。")
    extra = st.text_input("補充要求（選填）", placeholder="例：要申請學校補助，預算請分成自籌與補助；當天下雨要有備案", key=f"prop_extra_{p.id}")
    c1, c2 = st.columns([1, 3], vertical_alignment="center")
    clicked = c1.button("重新產生企劃書" if p.proposal else "產生企劃書", type="primary", key=f"prop_go_{p.id}")
    with c2:
        share = ctx.share_toggle(f"proposal_{p.id}")
    if clicked:
        proposal = ctx.run_ai(
            "撰寫企劃書中（約 1 分鐘）…",
            lambda llm, _s: EventPlanner(llm, _events_retriever()).propose(
                ctx.club, ctx.settings, p.facts(), extra, finance_settings(ctx.store, ctx.club_id).categories
            ),
        )
        if proposal:
            updated = p.model_copy(update={
                "proposal": proposal, "rundown": proposal.rundown, "budget_lines": proposal.budget,
                "stage": "企劃" if p.stage == "構思" else p.stage,
            })
            save_project(ctx.store, ctx.club_id, updated)
            md = proposal_markdown(ctx.club.name, updated, ctx.settings.name)
            ctx.keep_result(f"proposal_{p.id}", "proposal", f"{p.name} 企劃書", proposal.purpose[:150], md, share, "events")
            _flash("企劃書完成；流程與預算已帶入，可以在下方與「細流與工作人員」修改")
    if not p.proposal:
        return
    md = proposal_markdown(ctx.club.name, p, ctx.settings.name)
    st.divider()
    st.markdown(md)
    download_buttons(md, f"{p.name}企劃書", f"proposal_{p.id}")
    ctx.share_controls(f"proposal_{p.id}")

    st.divider()
    st.markdown("**調整預算**（會更新企劃書與成果報告的預算）")
    df = pd.DataFrame({
        "項目": pd.Series([b.item for b in p.budget_lines], dtype="object"),
        "類別": pd.Series([b.category for b in p.budget_lines], dtype="object"),
        "金額": pd.Series([b.amount for b in p.budget_lines], dtype="int64"),
        "說明": pd.Series([b.note for b in p.budget_lines], dtype="object"),
    })
    # 類別沿用財務設定的預算類別（只是類別名稱，不含任何金額）；保留企劃書裡已經用到的類別
    categories = list(dict.fromkeys([*finance_settings(ctx.store, ctx.club_id).categories, *[b.category for b in p.budget_lines]]))
    edited = st.data_editor(
        df, key=f"budget_lines_{p.id}", num_rows="dynamic", hide_index=True, width="stretch",
        column_config={
            "類別": st.column_config.SelectboxColumn(options=categories),
            "金額": st.column_config.NumberColumn(min_value=0, step=100, format="%,d"),
        },
    )
    lines = [
        BudgetLine(item=_text(r["項目"]), category=_text(r["類別"]) or "雜支", amount=int(r["金額"] or 0) if not pd.isna(r["金額"]) else 0,
                   note=_text(r["說明"]))
        for r in edited.to_dict("records") if _text(r["項目"])
    ]
    total = sum(b.amount for b in lines)
    st.caption(f"合計 {total:,} 元" + (f"（總預算 {p.budget:,} 元，{'超出' if total > p.budget else '剩餘'} {abs(p.budget - total):,} 元）" if p.budget else ""))
    if st.button("儲存預算", key=f"budget_save_{p.id}"):
        save_project(ctx.store, ctx.club_id, p.model_copy(update={"budget_lines": lines}))
        _flash("已儲存預算")


# ---------------------------------------------------------------------------
# 籌備清單（全社團待辦）
# ---------------------------------------------------------------------------


def prep_tab(ctx: AppContext, p: EventProject) -> None:
    st.caption("籌備工作就是全社團的待辦：各部門會在自己的「待辦與進度」看到，社長總覽與行事曆也會顯示期限。")
    tasks = [t for t in list_tasks(ctx.store, ctx.club_id) if t.project == p.id]
    if p.proposal:
        existing = {t.title for t in tasks}
        new = [t for t in prep_tasks_to_tasks(p, ctx.settings.enabled_keys()) if t.title not in existing]
        if new and st.button(f"把企劃書的 {len(new)} 項籌備工作加入待辦", type="primary", key=f"prep_import_{p.id}"):
            for t in new:
                save_task(ctx.store, ctx.club_id, t)
            _flash(f"已加入 {len(new)} 項籌備工作，期限依活動日期往前推算")
    elif not tasks:
        st.info("先到「企劃書」產生企劃，就能一鍵把籌備工作加入待辦；也可以直接在下方手動新增。")
    if tasks:
        done = sum(t.status == "完成" for t in tasks)
        st.progress(done / len(tasks), text=f"完成 {done}／{len(tasks)} 項")
    add_task_form(ctx, f"prep_{p.id}", department=None, project=p.id, source=f"活動「{p.name}」")
    show_done = st.toggle("顯示已完成", key=f"prep_done_{p.id}")
    tasks_table(ctx, [t for t in tasks if show_done or t.status != "完成"], f"prep_{p.id}", show_department=True)


# ---------------------------------------------------------------------------
# 細流與工作人員
# ---------------------------------------------------------------------------


def rundown_tab(ctx: AppContext, p: EventProject) -> None:
    st.markdown("**活動細流**（時間請用 HH:MM，例如 13:30）")
    rundown_df = pd.DataFrame({
        "開始": pd.Series([r.start for r in p.rundown], dtype="object"),
        "結束": pd.Series([r.end for r in p.rundown], dtype="object"),
        "流程": pd.Series([r.item for r in p.rundown], dtype="object"),
        "負責": pd.Series([r.owner for r in p.rundown], dtype="object"),
        "注意事項": pd.Series([r.note for r in p.rundown], dtype="object"),
    })
    rundown_edit = st.data_editor(rundown_df, key=f"rundown_{p.id}", num_rows="dynamic", hide_index=True, width="stretch")
    st.markdown("**工作人員**")
    staff_df = pd.DataFrame({
        "姓名": pd.Series([s.name for s in p.staff], dtype="object"),
        "組別／職務": pd.Series([s.role for s in p.staff], dtype="object"),
        "值班時段": pd.Series([s.shift for s in p.staff], dtype="object"),
        "備註": pd.Series([s.note for s in p.staff], dtype="object"),
    })
    staff_edit = st.data_editor(staff_df, key=f"staff_{p.id}", num_rows="dynamic", hide_index=True, width="stretch")
    rundown = [
        RundownItem(start=_text(r["開始"]), end=_text(r["結束"]), item=_text(r["流程"]), owner=_text(r["負責"]), note=_text(r["注意事項"]))
        for r in rundown_edit.to_dict("records") if _text(r["流程"])
    ]
    staff = [
        StaffMember(name=_text(r["姓名"]), role=_text(r["組別／職務"]), shift=_text(r["值班時段"]), note=_text(r["備註"]))
        for r in staff_edit.to_dict("records") if _text(r["姓名"])
    ]
    if st.button("儲存細流與工作人員", type="primary", key=f"rundown_save_{p.id}"):
        save_project(ctx.store, ctx.club_id, p.model_copy(update={"rundown": rundown, "staff": staff}))
        _flash("已儲存細流與工作人員")

    current = p.model_copy(update={"rundown": rundown, "staff": staff})
    md = rundown_markdown(ctx.club.name, current)
    c1, c2 = st.columns([1, 4])

    def excel() -> bytes:
        buffer = io.BytesIO()
        with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
            rundown_edit.to_excel(writer, sheet_name="細流", index=False)
            staff_edit.to_excel(writer, sheet_name="工作人員", index=False)
        return buffer.getvalue()

    c1.download_button("下載 Excel", excel, file_name=f"{p.name}細流與工作人員.xlsx", mime=XLSX_MIME,
                       icon=":material/table_view:", on_click="ignore", width="stretch", key=f"rundown_xlsx_{p.id}")
    with c2:
        download_buttons(md, f"{p.name}細流", f"rundown_{p.id}")

    st.divider()
    st.markdown("**名牌**（A4 每頁 8 張，印出後裁切）")
    default = "\n".join(f"{s.name}, {s.role}" if s.role else s.name for s in staff)
    names = st.text_area("名單：一行一位，可以用逗號加上職稱或組別", value=default, height=140, key=f"badges_{p.id}",
                         placeholder="王小明, 場控組\n陳小華, 攝影組")
    entries = []
    for line in names.splitlines():
        if line.strip():
            name, _, role = line.replace("，", ",").partition(",")
            entries.append((name.strip(), role.strip()))
    if not pdf_available():
        st.caption("這台主機沒有中文字型，暫時無法產生名牌。")
    elif entries:
        def badges() -> bytes:
            try:
                return badges_pdf(entries, ctx.club.name, p.name)
            except ExportError:
                return b""

        st.download_button(f"下載名牌 PDF（{len(entries)} 張）", badges, file_name=f"{p.name}名牌.pdf", mime="application/pdf",
                           icon=":material/badge:", on_click="ignore", key=f"badges_dl_{p.id}")


# ---------------------------------------------------------------------------
# 回饋表單
# ---------------------------------------------------------------------------


def feedback_tab(ctx: AppContext, p: EventProject) -> None:
    st.caption("AI 依活動內容設計 8–12 題回饋表單，可以直接照著建立 Google 表單。")
    extra = st.text_input("補充要求（選填）", placeholder="例：想知道參加者從哪裡得知活動；加一題抽獎用 Email（選填）", key=f"fb_extra_{p.id}")
    if st.button("重新產生題目" if p.feedback else "產生回饋表單題目", type="primary", key=f"fb_go_{p.id}"):
        content = "\n".join(p.proposal.content) if p.proposal else ""
        form = ctx.run_ai("設計回饋表單中…", lambda llm, _s: EventPlanner(llm).feedback_form(ctx.club, p.facts(), content, extra),
                          thinking="minimal")
        if form:
            save_project(ctx.store, ctx.club_id, p.model_copy(update={"feedback": form}))
            _flash("回饋表單題目完成")
    if not p.feedback:
        return
    md = feedback_markdown(p.feedback)
    st.markdown(md)
    st.markdown("**複製到 Google 表單**（右上角可以一鍵複製）")
    st.code(google_form_text(p.feedback), language=None)
    download_buttons(md, f"{p.name}回饋表單", f"feedback_{p.id}")


# ---------------------------------------------------------------------------
# 成果報告
# ---------------------------------------------------------------------------


def report_tab(ctx: AppContext, p: EventProject) -> None:
    st.caption("活動結束後，填入實際人數與回饋重點，AI 會對照企劃書目標撰寫成果報告（可用於學校核銷與交接）。")
    finance_open = st.session_state.get("finance_unlocked") == ctx.club_id
    if finance_open:
        spent, by_category = actual_spending(p, list_requests(ctx.store, ctx.club_id))
        st.caption(f"實際支出取自財務報帳中「所屬活動」為「{p.name}」且已核准的款項：共 {spent:,} 元。")
    else:
        by_category = {}
        spent = st.number_input("實際支出（元）", min_value=0, step=100, value=0, key=f"rp_spent_{p.id}",
                                help="財務資料需要財務密碼；請向財務確認後填寫，或由財務／社長解鎖財務管理後自動帶入")
    with st.form(f"report_inputs_{p.id}", border=False):
        attendance = st.number_input("實際參加人數", min_value=0, step=1, value=p.attendance)
        feedback_notes = st.text_area("回饋表單結果重點", value=p.feedback_notes, height=120,
                                      placeholder="例：滿意度平均 4.5／5；回收 62 份；多數希望下次有更多體驗攤位")
        review_notes = st.text_area("幹部檢討重點（選填）", value=p.review_notes, height=100,
                                    placeholder="例：報到動線塞住約 15 分鐘；宣傳太晚開始")
        submitted = st.form_submit_button("產生成果報告", type="primary")
    with st.container():
        share = ctx.share_toggle(f"report_{p.id}")
    if submitted:
        planned = sum(b.amount for b in p.budget_lines) or p.budget
        results = "\n".join([
            f"實際參加人數：{attendance or '【待補】'}（預計 {p.expected_people or '未定'}）",
            f"預算：{planned:,} 元；實際支出：{spent:,} 元",
            *[f"- {c}：{a:,} 元" for c, a in by_category.items()],
            f"回饋重點：{feedback_notes or '【待補】'}",
            f"幹部檢討：{review_notes or '（無）'}",
        ])
        proposal_text = proposal_markdown(ctx.club.name, p, ctx.settings.name) if p.proposal else ""
        report = ctx.run_ai("撰寫成果報告中…", lambda llm, _s: EventPlanner(llm).report(ctx.club, p.facts(), proposal_text, results))
        if report:
            updated = p.model_copy(update={"report": report, "attendance": int(attendance), "feedback_notes": feedback_notes,
                                           "review_notes": review_notes})
            save_project(ctx.store, ctx.club_id, updated)
            md = report_markdown(ctx.club.name, updated, int(spent), by_category)
            st.session_state[f"report_spent_{p.id}"] = (int(spent), by_category)
            ctx.keep_result(f"report_{p.id}", "report", f"{p.name} 成果報告", report.summary[:150], md, share, "events")
            _flash("成果報告完成")
    if not p.report:
        return
    spent_saved, by_cat_saved = st.session_state.get(f"report_spent_{p.id}", (int(spent), by_category))
    md = report_markdown(ctx.club.name, p, spent_saved, by_cat_saved)
    st.divider()
    st.markdown(md)
    download_buttons(md, f"{p.name}成果報告", f"report_{p.id}")
    ctx.share_controls(f"report_{p.id}")

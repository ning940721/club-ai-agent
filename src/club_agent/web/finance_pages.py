"""財務頁面：各部門的「報帳申請」，以及財務與社長專用、以財務密碼上鎖的「財務管理」。"""

from __future__ import annotations

import io
from datetime import date
from typing import Callable

import pandas as pd
import streamlit as st

from ..agents import FinanceAnalyst
from ..finance import (
    APPROVED,
    EXPENSE,
    EXPENSE_CATEGORIES,
    FIELD_LABELS,
    INCOME,
    INCOME_CATEGORIES,
    PAID,
    PAYMENT_METHODS,
    PENDING,
    REQUIRED_FIELDS,
    STATUSES,
    LedgerEntry,
    Reimbursement,
    add_request,
    approve,
    balance_before,
    budget_rows,
    delete_entry,
    get_request,
    get_settings,
    guess_mapping,
    import_rows,
    list_entries,
    list_requests,
    mark_paid,
    month_range,
    needs_president,
    normalize_invoice,
    policy_markdown,
    reject,
    report_digest,
    report_markdown,
    review_warnings,
    save_entry,
    save_request,
    save_settings,
    summarize_period,
    to_excel,
    transactions,
)
from ..metrics import decode_csv_bytes
from .context import AppContext, download_buttons

XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _dept_label(ctx: AppContext, key: str) -> str:
    return ctx.settings.name(key) if key else "未指定"


def _done(where: str, message: str, notes: list[str] | None = None) -> None:
    """存好訊息後重新整理頁面，讓各分頁顯示最新資料；訊息在重新整理後由 _show_done 顯示。"""
    st.session_state[f"finance_done_{where}"] = (message, notes or [])
    st.rerun()


def _show_done(where: str) -> None:
    if done := st.session_state.pop(f"finance_done_{where}", None):
        message, notes = done
        st.success(message)
        for n in notes:
            st.info(n)


# ---------------------------------------------------------------------------
# 報帳申請（所有部門）
# ---------------------------------------------------------------------------


def reimburse_page(ctx: AppContext) -> None:
    fs = get_settings(ctx.store, ctx.club_id)
    rule = f"，{fs.approval_threshold:,} 元以上需社長同意" if fs.approval_threshold else ""
    st.caption(
        f"自己先付錢買東西後，在這裡申請報帳。請在消費後 {fs.claim_deadline_days} 天內申請{rule}；"
        "送出後把發票或收據正本交給財務，財務核准後撥款。"
    )
    tab_new, tab_check = st.tabs(["新申請", "查詢進度"])
    with tab_new:
        _show_done("request")
        request_form(ctx)
    with tab_check:
        with st.form("reimburse_lookup", border=False):
            code = st.text_input("報帳編號", placeholder="例：R1006-K7Q")
            looked_up = st.form_submit_button("查詢")
        if looked_up and code.strip():
            r = get_request(ctx.store, ctx.club_id, code)
            if r is None:
                st.warning("找不到這個報帳編號，請確認是否輸入正確。")
            else:
                st.markdown(f"**{r.id}｜{r.item}｜{r.amount:,} 元**")
                st.markdown(f"狀態：**{r.status}**" + (f"（{r.paid_at} 撥款）" if r.status == PAID else ""))
                if r.review_note:
                    st.markdown(f"財務備註：{r.review_note}")


def request_form(ctx: AppContext) -> None:
    with st.form("reimburse_new", clear_on_submit=True):
        c1, c2 = st.columns(2)
        applicant = c1.text_input("申請人＊", placeholder="實際付錢、要收到撥款的人")
        departments = ctx.settings.enabled_keys()
        department = c2.selectbox("部門", departments, index=departments.index(ctx.dept_key), format_func=ctx.settings.name)
        item = st.text_input("項目＊", placeholder="例：成果展海報輸出 A1 × 5 張")
        c3, c4, c5 = st.columns(3)
        category = c3.selectbox("類別", EXPENSE_CATEGORIES)
        amount = c4.number_input("金額（元）＊", min_value=0, step=1, value=0)
        receipt_date = c5.date_input("消費日期", value=date.today())
        c6, c7, c8 = st.columns(3)
        invoice_no = c6.text_input("發票號碼", placeholder="例：AB12345678；收據可空白")
        activity = c7.text_input("所屬活動（選填）", placeholder="例：成果展")
        method = c8.selectbox("撥款方式", PAYMENT_METHODS)
        note = st.text_input("備註（選填）", placeholder="收據請說明開立人；轉帳帳號請私下提供給財務，不要寫在這裡")
        if not st.form_submit_button("送出申請", type="primary"):
            return
    if not applicant.strip() or not item.strip() or amount <= 0:
        st.warning("請填寫申請人、項目與金額")
        return
    r = add_request(
        ctx.store,
        ctx.club_id,
        Reimbursement(
            applicant=applicant.strip(), department=department, item=item.strip(), category=category, amount=int(amount),
            invoice_no=normalize_invoice(invoice_no), receipt_date=receipt_date.isoformat(), activity=activity.strip(),
            payment_method=method, note=note.strip(),
        ),
    )
    others = list_requests(ctx.store, ctx.club_id)
    # 需要社長同意是審核端的事，不需要提醒申請人
    notes = [w for w in review_warnings(r, others, get_settings(ctx.store, ctx.club_id)) if "社長" not in w]
    _done("request", f"已送出，報帳編號：**{r.id}**。請把編號寫在單據背面並交給財務，之後可用編號查詢進度。", notes)


# ---------------------------------------------------------------------------
# 財務管理（財務、社長；財務密碼上鎖）
# ---------------------------------------------------------------------------


def unlock_gate(ctx: AppContext) -> bool:
    if st.session_state.get("finance_unlocked") == ctx.club_id:
        return True
    fs = get_settings(ctx.store, ctx.club_id)
    if not fs.has_pin:
        st.info("第一次使用財務管理，請先設定**財務密碼**。之後只有知道密碼的人（財務與社長）能查看帳務。")
        with st.form("finance_set_pin"):
            pin = st.text_input("設定財務密碼（至少 4 個字元）", type="password")
            pin2 = st.text_input("再輸入一次", type="password")
            if st.form_submit_button("設定並進入", type="primary"):
                if pin != pin2:
                    st.error("兩次輸入的密碼不一樣")
                else:
                    try:
                        save_settings(ctx.store, ctx.club_id, fs.with_pin(pin))
                        st.session_state.finance_unlocked = ctx.club_id
                        st.rerun()
                    except ValueError as e:
                        st.error(str(e))
        return False

    st.caption("財務資料只有財務與社長可以查看，請輸入財務密碼。")
    with st.form("finance_unlock"):
        pin = st.text_input("財務密碼", type="password")
        if st.form_submit_button("進入", type="primary"):
            if fs.check_pin(pin):
                st.session_state.finance_unlocked = ctx.club_id
                st.rerun()
            st.error("財務密碼錯誤")
    with st.expander("忘記財務密碼"):
        st.caption("用社團帳號與密碼確認身分後，可以重新設定財務密碼。")
        with st.form("finance_reset_pin"):
            account = st.text_input("社團帳號")
            password = st.text_input("社團密碼", type="password")
            new_pin = st.text_input("新的財務密碼（至少 4 個字元）", type="password")
            if st.form_submit_button("重設財務密碼"):
                if ctx.store.authenticate(account, password) != ctx.club_id:
                    st.error("社團帳號或密碼錯誤")
                else:
                    try:
                        save_settings(ctx.store, ctx.club_id, fs.with_pin(new_pin))
                        st.success("已重設，請用新的財務密碼進入")
                    except ValueError as e:
                        st.error(str(e))
    return False


def finance_tabs(ctx: AppContext) -> list[tuple[str, Callable[[], None]]]:
    """財務分頁；還沒輸入財務密碼時，在分頁上方顯示解鎖畫面，不顯示任何財務分頁。"""
    if not unlock_gate(ctx):
        return []
    requests = list_requests(ctx.store, ctx.club_id)
    pending = sum(r.status == PENDING for r in requests)
    c1, c2 = st.columns([5, 1])
    c1.caption("財務資料只有財務與社長看得到，內容不會出現在社團動態。")
    if c2.button("鎖定", icon=":material/lock:", type="tertiary"):
        st.session_state.pop("finance_unlocked", None)
        st.rerun()
    return [
        (f"報帳審核（{pending}）", lambda: review_section(ctx, requests)),
        ("收支帳簿", lambda: ledger_section(ctx, requests)),
        ("預算", lambda: budget_section(ctx, requests)),
        ("財務報表", lambda: report_section(ctx, requests)),
        ("規範與設定", lambda: settings_section(ctx)),
    ]


def finance_page(ctx: AppContext) -> None:
    """社長的「財務管理」分頁：財務功能收在同一個分頁裡，不和社團總覽並列。"""
    tabs = finance_tabs(ctx)
    if tabs:
        for tab, (_, render) in zip(st.tabs([name for name, _ in tabs]), tabs):
            with tab:
                render()


def review_section(ctx: AppContext, requests: list[Reimbursement]) -> None:
    fs = get_settings(ctx.store, ctx.club_id)
    reviewer = ctx.dept_name
    _show_done("review")
    pending = [r for r in requests if r.status == PENDING]
    st.markdown(f"**待審核（{len(pending)}）**")
    if not pending:
        st.caption("目前沒有待審核的報帳。")
    for r in sorted(pending, key=lambda x: x.created_at):
        with st.container(border=True):
            st.markdown(f"**{r.id}｜{r.item}｜{r.amount:,} 元**　{r.applicant}（{_dept_label(ctx, r.department)}）")
            facts = [f"類別：{r.category}", f"消費日期：{r.receipt_date}", f"發票：{r.invoice_no or '無'}",
                     f"撥款：{r.payment_method}", f"申請：{r.created_at[:16].replace('T', ' ')}"]
            if r.activity:
                facts.insert(1, f"活動：{r.activity}")
            st.caption("｜".join(facts) + (f"\n\n備註：{r.note}" if r.note else ""))
            for w in review_warnings(r, requests, fs):
                st.warning(w, icon=":material/warning:")
            note = st.text_input("審核備註（退件時必填）", key=f"rv_note_{r.id}")
            president_ok = True
            if needs_president(r, fs) and ctx.dept_key != "president":
                president_ok = st.checkbox("社長已同意這筆支出", key=f"rv_pres_{r.id}")
            b1, b2, _ = st.columns([1, 1, 4])
            if b1.button("核准", key=f"rv_ok_{r.id}", type="primary"):
                if not president_ok:
                    st.error("這筆金額需要社長同意，請先確認後勾選")
                else:
                    save_request(ctx.store, ctx.club_id, approve(r, reviewer, note.strip(), president_ok=needs_president(r, fs)))
                    _done("review", f"已核准 {r.id}（{r.item}，{r.amount:,} 元）")
            if b2.button("退件", key=f"rv_no_{r.id}"):
                if not note.strip():
                    st.error("請在審核備註寫下退件原因，申請人查詢時看得到")
                else:
                    save_request(ctx.store, ctx.club_id, reject(r, reviewer, note.strip()))
                    _done("review", f"已退件 {r.id}，申請人查詢時會看到原因")

    approved = [r for r in requests if r.status == APPROVED]
    st.divider()
    st.markdown(f"**已核准、待撥款（{len(approved)} 筆，共 {sum(r.amount for r in approved):,} 元）**")
    if approved:
        labels = {r.id: f"{r.id}｜{r.applicant}｜{r.item}｜{r.amount:,} 元（{r.payment_method}）" for r in approved}
        chosen = st.multiselect("選擇已經撥款的報帳", list(labels), default=list(labels), format_func=labels.get, key="pay_pick")
        c1, c2 = st.columns([1, 2], vertical_alignment="bottom")
        paid_on = c1.date_input("撥款日期", value=date.today(), key="pay_date")
        if c2.button("標記為已撥款", disabled=not chosen):
            for r in approved:
                if r.id in chosen:
                    save_request(ctx.store, ctx.club_id, mark_paid(r, paid_on))
            _done("review", f"已標記 {len(chosen)} 筆為已撥款，並記入收支帳簿")
    else:
        st.caption("沒有待撥款的報帳。")

    st.divider()
    st.markdown("**所有報帳**")
    statuses = st.multiselect("狀態", STATUSES, default=list(STATUSES), key="rv_filter")
    rows = [r for r in requests if r.status in statuses]
    if rows:
        st.dataframe(
            pd.DataFrame(
                {
                    "編號": [r.id for r in rows], "申請日": [r.created_at[:10] for r in rows], "申請人": [r.applicant for r in rows],
                    "部門": [_dept_label(ctx, r.department) for r in rows], "項目": [r.item for r in rows],
                    "類別": [r.category for r in rows], "金額": [r.amount for r in rows], "發票": [r.invoice_no for r in rows],
                    "狀態": [r.status for r in rows], "審核備註": [r.review_note for r in rows], "撥款日": [r.paid_at for r in rows],
                }
            ),
            hide_index=True,
            width="stretch",
            column_config={"金額": st.column_config.NumberColumn(format="%,d")},
        )
    else:
        st.caption("沒有符合的報帳。")


def ledger_section(ctx: AppContext, requests: list[Reimbursement]) -> None:
    fs = get_settings(ctx.store, ctx.club_id)
    today = date.today()
    start, end = fs.term(today)
    entries = list_entries(ctx.store, ctx.club_id)
    txs = transactions(requests, entries)
    term = summarize_period(txs, start, end, fs.opening_balance)
    current = balance_before(txs, date.max, fs.opening_balance) if txs else fs.opening_balance
    _show_done("ledger")
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("目前帳上餘額", f"{current:,}")
    m2.metric("本學期收入", f"{term.income:,}")
    m3.metric("本學期支出", f"{term.expense:,}")
    owed = sum(r.amount for r in requests if r.status == APPROVED)
    m4.metric("已核准待撥款", f"{owed:,}")
    if owed > current:
        st.warning(f"待撥款 {owed:,} 元超過目前餘額 {current:,} 元，請確認資金來源。")
    st.caption(f"本學期：{start} ~ {end}（期初餘額 {fs.opening_balance:,} 元，可在「規範與設定」修改）。已撥款的報帳會自動記為支出。")

    with st.expander("記一筆收入或支出（社費、補助、贊助、不經報帳的支出…）"):
        kind = st.segmented_control("收支", [INCOME, EXPENSE], default=INCOME, key="lg_kind") or INCOME
        with st.form("ledger_add", clear_on_submit=True, border=False):
            c1, c2, c3 = st.columns(3)
            day = c1.date_input("日期", value=today)
            category = c2.selectbox("類別", INCOME_CATEGORIES if kind == INCOME else EXPENSE_CATEGORIES)
            amount = c3.number_input("金額（元）", min_value=0, step=1, value=0)
            description = st.text_input("說明＊", placeholder="例：10 月社費 25 人 × 300 元" if kind == INCOME else "例：社辦文具")
            c4, c5 = st.columns(2)
            handler = c4.text_input("經手人")
            invoice = c5.text_input("發票／收據號碼（選填）")
            if st.form_submit_button("記帳", type="primary"):
                if amount <= 0 or not description.strip():
                    st.warning("請填寫金額與說明")
                else:
                    save_entry(ctx.store, ctx.club_id, LedgerEntry(
                        date=day.isoformat(), kind=kind, category=category, amount=int(amount), description=description.strip(),
                        handler=handler.strip(), invoice_no=normalize_invoice(invoice),
                    ))
                    _done("ledger", f"已記帳：{kind} {int(amount):,} 元（{description.strip()}）")

    st.markdown("**本學期收支明細**")
    if not term.items:
        st.caption("本學期還沒有收支紀錄。")
        return
    balance = term.opening
    rows = []
    for t in term.items:
        balance += t.signed
        rows.append({"日期": t.date, "收支": t.kind, "類別": t.category, "說明": t.description,
                     "金額": t.signed, "餘額": balance, "經手人": t.handler, "單據／編號": t.invoice_no or t.ref})
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch",
                 column_config={"金額": st.column_config.NumberColumn(format="%,d"), "餘額": st.column_config.NumberColumn(format="%,d")})
    manual = [e for e in entries if start.isoformat() <= e.date <= end.isoformat()]
    if manual:
        with st.expander("刪除記錯的帳（只能刪除手動記錄的收支；報帳請到報帳審核處理）"):
            labels = {e.id: f"{e.date}｜{e.kind}｜{e.category}｜{e.description}｜{e.amount:,}" for e in manual}
            target = st.selectbox("選擇要刪除的紀錄", list(labels), format_func=labels.get, key="lg_del_pick")
            if st.button("刪除這筆", key="lg_del"):
                delete_entry(ctx.store, ctx.club_id, target)
                _done("ledger", "已刪除")


def budget_section(ctx: AppContext, requests: list[Reimbursement]) -> None:
    fs = get_settings(ctx.store, ctx.club_id)
    start, end = fs.term(date.today())
    _show_done("budget")
    st.caption(f"本學期（{start} ~ {end}）各類別的預算與執行狀況。已核准與已撥款的報帳、手動記錄的支出都算已使用。")
    rows = budget_rows(fs, requests, list_entries(ctx.store, ctx.club_id), start, end)
    if rows:
        for b in rows:
            if b.status in ("超支", "待審核通過後會超支", "接近上限"):
                st.warning(f"{b.category}：{b.status}（已用 {b.used:,}／預算 {b.budget:,}，待審核 {b.pending:,}）")
        st.dataframe(
            pd.DataFrame({"類別": [b.category for b in rows], "預算": [b.budget for b in rows], "已使用": [b.used for b in rows],
                          "待審核": [b.pending for b in rows], "剩餘": [b.remaining for b in rows],
                          "執行率": [min(b.rate, 1.0) for b in rows], "狀態": [b.status for b in rows]}),
            hide_index=True,
            width="stretch",
            column_config={
                "執行率": st.column_config.ProgressColumn(min_value=0.0, max_value=1.0, format="percent"),
                **{c: st.column_config.NumberColumn(format="%,d") for c in ("預算", "已使用", "待審核", "剩餘")},
            },
        )
    st.markdown("**編列預算**")
    categories = [*EXPENSE_CATEGORIES, *[c for c in fs.budgets if c not in EXPENSE_CATEGORIES]]
    edited = st.data_editor(
        pd.DataFrame({"類別": categories, "預算": [fs.budgets.get(c, 0) for c in categories]}),
        hide_index=True, disabled=["類別"], key="budget_editor",
        column_config={"預算": st.column_config.NumberColumn(min_value=0, step=100, format="%,d")},
    )
    total = int(edited["預算"].fillna(0).sum())
    st.caption(f"預算合計 {total:,} 元。建議保留 5%–10% 作為預備金（放在「雜支」）。")
    if st.button("儲存預算", type="primary"):
        budgets = {row["類別"]: int(row["預算"] or 0) for row in edited.to_dict("records") if row["預算"] and row["預算"] > 0}
        save_settings(ctx.store, ctx.club_id, fs.model_copy(update={"budgets": budgets}))
        _done("budget", "已儲存預算")


def report_section(ctx: AppContext, requests: list[Reimbursement]) -> None:
    fs = get_settings(ctx.store, ctx.club_id)
    today = date.today()
    kind = st.segmented_control("報表", ["月報", "學期報表"], default="月報", key="rp_kind") or "月報"
    if kind == "月報":
        months = [(today.year - (today.month - 1 - i < 0), (today.month - 1 - i) % 12 + 1) for i in range(12)]
        year, month = st.selectbox("月份", months, format_func=lambda ym: f"{ym[0]} 年 {ym[1]} 月", key="rp_month")
        start, end = month_range(year, month)
        title = f"{year} 年 {month} 月財務月報"
    else:
        start, end = fs.term(today)
        title = f"學期財務報表（{start} ~ {end}）"
    entries = list_entries(ctx.store, ctx.club_id)
    summary = summarize_period(transactions(requests, entries), start, end, fs.opening_balance)
    budgets = budget_rows(fs, requests, entries, *fs.term(today))
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("期初餘額", f"{summary.opening:,}")
    m2.metric("收入", f"{summary.income:,}")
    m3.metric("支出", f"{summary.expense:,}")
    m4.metric("期末餘額", f"{summary.closing:,}", delta=f"{summary.net:+,}")

    md = report_markdown(ctx.club.name, title, summary, budgets)
    with st.expander("預覽報表內容"):
        st.markdown(md)
    c1, c2 = st.columns([1, 4])
    c1.download_button(
        "下載 Excel", lambda: to_excel(ctx.club.name, title, summary, budgets, requests), file_name=f"{title}.xlsx",
        mime=XLSX_MIME, icon=":material/table_view:", on_click="ignore", width="stretch", key="rp_xlsx",
    )
    with c2:
        download_buttons(md, title, f"finance_{start}_{end}")

    st.divider()
    st.markdown("**AI 財務分析**")
    st.caption("AI 會依這份報表整理財務狀況、提醒風險並給改善建議。分析結果不會分享到社團動態。")
    if st.button("分析這份報表"):
        text = report_digest(title, summary, budgets, requests)
        review = ctx.run_ai(
            "分析財務狀況中…",
            lambda llm, _s: FinanceAnalyst(llm).run(ctx.club, text, ctx.settings.details("finance")),
        )
        if review:
            st.session_state.finance_review = (title, review)
    if (saved := st.session_state.get("finance_review")) and saved[0] == title:
        review = saved[1]
        st.markdown(review.summary)
        if review.warnings:
            st.markdown("**需要注意**\n" + "\n".join(f"- {w}" for w in review.warnings))
        st.markdown("**建議**\n" + "\n".join(f"- {s}" for s in review.suggestions))


def settings_section(ctx: AppContext) -> None:
    fs = get_settings(ctx.store, ctx.club_id)
    default_start, default_end = fs.term(date.today())
    _show_done("settings")
    st.markdown("**財務設定**")
    with st.form("finance_settings"):
        c1, c2, c3 = st.columns(3)
        threshold = c1.number_input("社長核准門檻（元，0 表示不需要）", min_value=0, step=500, value=fs.approval_threshold)
        deadline = c2.number_input("消費後幾天內要申請", min_value=1, max_value=180, step=1, value=fs.claim_deadline_days)
        opening = c3.number_input("期初餘額（元）", step=100, value=fs.opening_balance, help="學期開始時帳上的錢")
        c4, c5 = st.columns(2)
        term_start = c4.date_input("學期開始", value=default_start)
        term_end = c5.date_input("學期結束", value=default_end)
        if st.form_submit_button("儲存設定", type="primary"):
            if term_end <= term_start:
                st.error("學期結束要晚於學期開始")
            else:
                save_settings(ctx.store, ctx.club_id, fs.model_copy(update={
                    "approval_threshold": int(threshold), "claim_deadline_days": int(deadline), "opening_balance": int(opening),
                    "term_start": term_start.isoformat(), "term_end": term_end.isoformat(),
                }))
                _done("settings", "已儲存設定")

    with st.expander("變更財務密碼"):
        with st.form("finance_change_pin"):
            old = st.text_input("目前的財務密碼", type="password")
            new = st.text_input("新的財務密碼（至少 4 個字元）", type="password")
            if st.form_submit_button("變更"):
                if not fs.check_pin(old):
                    st.error("目前的財務密碼不正確")
                else:
                    try:
                        save_settings(ctx.store, ctx.club_id, fs.with_pin(new))
                        st.success("已變更，請告知社長新的財務密碼")
                    except ValueError as e:
                        st.error(str(e))

    st.divider()
    st.markdown("**建議的報帳與財務規範**")
    st.caption("依上面的設定產生，可以下載後修改，公告給全體幹部。")
    policy = policy_markdown(ctx.club.name, fs)
    with st.expander("查看規範內容"):
        st.markdown(policy)
    download_buttons(policy, "報帳與財務規範", "finance_policy")

    st.divider()
    import_section(ctx)


def import_section(ctx: AppContext) -> None:
    st.markdown("**匯入 Google 表單的報帳紀錄**")
    st.caption("在 Google 表單的回覆試算表中，選「檔案 → 下載 → 逗號分隔值（.csv）」，再上傳到這裡。")
    uploaded = st.file_uploader("上傳 CSV", type="csv", key="fin_import")
    if uploaded is None:
        return
    try:
        df = pd.read_csv(io.StringIO(decode_csv_bytes(uploaded.getvalue())), dtype=str).fillna("")
    except Exception as e:  # 檔案格式錯誤
        st.error(f"CSV 讀取失敗：{e}")
        return
    columns = list(df.columns)
    guessed = guess_mapping(columns)
    st.caption(f"讀到 {len(df)} 筆。請確認每個欄位對應到表單的哪一欄（＊為必填）。")
    mapping = {}
    cols = st.columns(3)
    for i, (field, label) in enumerate(FIELD_LABELS.items()):
        options = ["", *columns]
        mapping[field] = cols[i % 3].selectbox(
            f"{label}{'＊' if field in REQUIRED_FIELDS else ''}", options,
            index=options.index(guessed[field]) if field in guessed else 0, key=f"fin_map_{field}",
            format_func=lambda c: c or "（不匯入）",
        )
    status = st.selectbox("匯入後的狀態", [PAID, APPROVED, PENDING], help="過去已經處理完的報帳，選「已撥款」就會記入帳簿", key="fin_import_status")
    if not all(mapping[f] for f in REQUIRED_FIELDS):
        st.info("請先選好申請人、項目、金額對應的欄位")
        return
    names = {ctx.settings.name(k): k for k in ctx.settings.enabled_keys()}

    def lookup(name: str) -> str:
        return next((key for label, key in names.items() if label and label in name), "")

    items, skipped = import_rows(df.to_dict("records"), {k: v for k, v in mapping.items() if v}, status, lookup)
    st.caption(f"可匯入 {len(items)} 筆，共 {sum(r.amount for r in items):,} 元" + (f"；略過 {len(skipped)} 筆" if skipped else ""))
    if skipped:
        with st.expander("略過的資料"):
            st.markdown("\n".join(f"- {s}" for s in skipped))
    if items and st.button(f"匯入 {len(items)} 筆", type="primary"):
        for r in items:
            add_request(ctx.store, ctx.club_id, r)
        st.success(f"已匯入 {len(items)} 筆報帳紀錄")


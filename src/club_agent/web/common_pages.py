"""所有部門共用的頁面：部門顧問、待辦與進度、社團動態、社團設定（後台）、使用說明。"""

from __future__ import annotations

from datetime import date

import pandas as pd
import streamlit as st

from ..agents import ClubQA, DepartmentAdvisor, club_retriever
from ..departments import DEPARTMENTS, ClubSettings, DepartmentConfig, department_retriever
from ..meetings import list_meetings
from ..report import advice_markdown, meeting_answer_markdown
from ..schemas import ClubProfile
from ..store import StoreError, activity_digest
from ..tasks import STATUSES, Task, delete_task, list_tasks, save_task, tasks_digest
from .context import AppContext, download_buttons

PLATFORMS = ["Instagram", "Facebook", "Dcard", "Threads"]


@st.cache_resource
def get_department_retriever(key: str):
    return department_retriever(key)


# ---------------------------------------------------------------------------
# 部門顧問
# ---------------------------------------------------------------------------


QA_EXAMPLES = ("上次開會決定了什麼？", "下次開會是什麼時候？", "目前有哪些逾期的任務？")
MODE_QA, MODE_ADVICE = "快速問答", "顧問建議"


def advisor_page(ctx: AppContext) -> None:
    mode = st.segmented_control(
        "想做什麼？",
        [MODE_QA, MODE_ADVICE],
        default=MODE_ADVICE,
        key=f"advisor_mode_{ctx.dept_key}",
        help="快速問答：從會議記錄、社團動態與待辦中直接找答案。顧問建議：針對狀況給行動步驟與可用的文件模板。",
    )
    if mode == MODE_QA:
        quick_qa(ctx)
    else:
        advice_section(ctx)


def quick_qa(ctx: AppContext) -> None:
    st.caption("從社團的會議記錄、各部門紀錄與待辦中找答案，並附上出處。")
    q_key = f"qa_question_{ctx.dept_key}"
    cols = st.columns(len(QA_EXAMPLES))
    for i, example in enumerate(QA_EXAMPLES):
        if cols[i].button(example, key=f"qa_ex_{ctx.dept_key}_{i}", width="stretch"):
            st.session_state[q_key] = example
    with st.form(f"club_qa_{ctx.dept_key}", clear_on_submit=False, border=False):
        question = st.text_input("想查什麼？", key=q_key, placeholder="例：成果展預算最後決定多少？")
        submitted = st.form_submit_button("提問", type="primary")
    if submitted:
        if not question.strip():
            st.warning("請先輸入問題")
        else:
            q = question.strip()

            def ask(llm, _status):
                docs = list_meetings(ctx.store, ctx.club_id)
                records = ctx.store.list_records(ctx.club_id, limit=60)
                tasks = tasks_digest(list_tasks(ctx.store, ctx.club_id), ctx.settings, date.today())
                return ClubQA(llm).run(q, docs, club_retriever(docs, records, ctx.settings.name), tasks)

            # 問答只需要從資料找答案，用最低思考程度回應最快
            answer = ctx.run_ai("翻閱社團紀錄中…", ask, thinking="minimal")
            if answer:
                st.session_state.setdefault("club_qa_history", []).insert(0, meeting_answer_markdown(q, answer))
    for i, md in enumerate(st.session_state.get("club_qa_history", [])):
        if i:
            st.divider()
        st.markdown(md)


def advice_section(ctx: AppContext) -> None:
    dept = ctx.dept
    st.caption("專長：" + "、".join(dept.focus))
    if dept.beta:
        st.caption("這個部門的顧問為測試版，知識庫仍在擴充中，建議請再自行確認。")
    if not ctx.settings.details(ctx.dept_key):
        st.caption("提示：到「社團設定 → 部門設定」填寫這個部門的細節，建議會更貼近你們社團。")

    q_key = f"question_{ctx.dept_key}"
    st.markdown("**範例問題**（點一下帶入）")
    for i, example in enumerate(dept.example_questions):
        if st.button(example, key=f"ex_{ctx.dept_key}_{i}"):
            st.session_state[q_key] = example
    question = st.text_area("你的問題", key=q_key, height=120, placeholder="描述你遇到的狀況，越具體建議越準確")

    result_key = f"advice_{ctx.dept_key}"
    col_btn, col_share = st.columns([1, 3], vertical_alignment="center")
    clicked = col_btn.button("取得建議", type="primary")
    with col_share:
        share = ctx.share_toggle(result_key)
    if clicked:
        if not question.strip():
            st.warning("請先輸入問題")
        else:
            q = question.strip()

            def ask(llm, _status):
                records = ctx.store.list_records(ctx.club_id, limit=30)
                activity = activity_digest(records, exclude_department=ctx.dept_key, settings=ctx.settings)
                dept_tasks = tasks_digest(list_tasks(ctx.store, ctx.club_id, ctx.dept_key), ctx.settings)
                advisor = DepartmentAdvisor(llm, get_department_retriever(ctx.dept_key))
                return advisor.run(ctx.club, dept, q, activity, ctx.settings, dept_tasks)

            advice = ctx.run_ai(f"{ctx.dept_name}顧問思考中…", ask)
            if advice:
                md = advice_markdown(ctx.dept_name, q, advice)
                ctx.keep_result(result_key, "advice", q[:60], advice.summary[:150], md, share)

    if item := st.session_state.get(f"result_{result_key}"):
        st.divider()
        st.markdown(item["markdown"])
        download_buttons(item["markdown"], f"{ctx.dept_name}顧問建議", result_key)
        ctx.share_controls(result_key)

    recent = ctx.store.list_records(ctx.club_id, department=ctx.dept_key, limit=5)
    if recent:
        st.divider()
        st.markdown(f"**{ctx.dept_name}最近紀錄**")
        for r in recent:
            ctx.show_record(r, "dept")


# ---------------------------------------------------------------------------
# 待辦與進度
# ---------------------------------------------------------------------------


def add_task_form(ctx: AppContext, key: str, department: str | None = None) -> None:
    """新增任務；department 為 None 時可選擇部門。"""
    with st.form(f"add_task_{key}", clear_on_submit=True):
        st.markdown("**新增任務**")
        c1, c2 = st.columns([3, 2])
        title = c1.text_input("事項", key=f"t_title_{key}")
        owner = c2.text_input("負責人", key=f"t_owner_{key}")
        c3, c4, c5 = st.columns(3)
        if department is None:
            dept = c3.selectbox("部門", ctx.settings.enabled_keys(), format_func=ctx.settings.name, key=f"t_dept_{key}")
        else:
            dept = department
        due = c4.date_input("期限（可不填）", value=None, key=f"t_due_{key}")
        status = c5.selectbox("狀態", STATUSES, key=f"t_status_{key}")
        if st.form_submit_button("新增"):
            if not title.strip():
                st.warning("請填寫事項")
            else:
                save_task(
                    ctx.store,
                    ctx.club_id,
                    Task(title=title.strip(), department=dept, owner=owner.strip(), due=due.isoformat() if due else "", status=status),
                )
                st.success("已新增")


def tasks_table(ctx: AppContext, tasks: list[Task], key: str, show_department: bool) -> None:
    """可直接編輯狀態、負責人、期限的任務表。"""
    if not tasks:
        st.info("目前沒有任務。")
        return
    today = date.today()
    df = pd.DataFrame(
        {
            "id": [t.id for t in tasks],
            "部門": [ctx.settings.name(t.department) for t in tasks],
            "事項": [t.title for t in tasks],
            "負責人": [t.owner for t in tasks],
            "期限": [t.due_date() for t in tasks],
            "狀態": [t.status for t in tasks],
            "逾期": ["逾期" if t.is_overdue(today) else "" for t in tasks],
            "來源": [t.source for t in tasks],
            "刪除": [False for _ in tasks],
        }
    )
    column_order = ["部門"] if show_department else []
    column_order += ["狀態", "事項", "負責人", "期限", "逾期", "來源", "刪除"]
    edited = st.data_editor(
        df,
        key=f"tasks_editor_{key}",
        hide_index=True,
        width="stretch",
        column_order=column_order,
        disabled=["部門", "逾期", "來源"],
        column_config={
            "狀態": st.column_config.SelectboxColumn(options=list(STATUSES), required=True),
            "期限": st.column_config.DateColumn(format="YYYY-MM-DD"),
            "刪除": st.column_config.CheckboxColumn(help="勾選後按「儲存變更」刪除"),
        },
    )
    if st.button("儲存變更", key=f"save_tasks_{key}"):
        by_id = {t.id: t for t in tasks}
        changed = 0
        for row in edited.to_dict("records"):
            task = by_id[row["id"]]
            if row["刪除"]:
                delete_task(ctx.store, ctx.club_id, task.id)
                changed += 1
                continue
            due = row["期限"]
            new = task.model_copy(
                update={
                    "title": str(row["事項"] or "").strip() or task.title,
                    "owner": str(row["負責人"] or "").strip(),
                    "due": due.isoformat() if hasattr(due, "isoformat") and not pd.isna(due) else "",
                    "status": row["狀態"],
                }
            )
            if new.model_dump(exclude={"updated_at"}) != task.model_dump(exclude={"updated_at"}):
                save_task(ctx.store, ctx.club_id, new)
                changed += 1
        st.session_state.pop(f"tasks_editor_{key}", None)  # 清掉表格的暫存編輯，重新載入最新資料
        st.success(f"已更新 {changed} 筆")
        st.rerun()


def tasks_page(ctx: AppContext) -> None:
    st.subheader(f"{ctx.dept_name}的待辦與進度")
    add_task_form(ctx, ctx.dept_key, department=ctx.dept_key)
    show_done = st.toggle("顯示已完成", key=f"show_done_{ctx.dept_key}")
    tasks = [t for t in list_tasks(ctx.store, ctx.club_id, ctx.dept_key) if show_done or t.status != "完成"]
    tasks_table(ctx, tasks, ctx.dept_key, show_department=False)

    with st.expander("看看其他部門在做什麼"):
        others = [t for t in list_tasks(ctx.store, ctx.club_id) if t.department != ctx.dept_key and t.status != "完成"]
        if others:
            st.dataframe(
                pd.DataFrame(
                    {
                        "部門": [ctx.settings.name(t.department) for t in others],
                        "事項": [t.title for t in others],
                        "負責人": [t.owner for t in others],
                        "期限": [t.due for t in others],
                        "狀態": [t.status for t in others],
                    }
                ),
                hide_index=True,
                width="stretch",
            )
        else:
            st.caption("其他部門目前沒有未完成的任務。")


# ---------------------------------------------------------------------------
# 社團動態
# ---------------------------------------------------------------------------


def feed_page(ctx: AppContext) -> None:
    st.subheader("全社團各部門的提問與成果")
    st.caption("各部門的顧問建議、會議重點、診斷與企劃都會出現在這裡，方便掌握彼此進度。")
    all_records = ctx.store.list_records(ctx.club_id)
    keys = ctx.settings.enabled_keys() + sorted({r.department for r in all_records} - set(ctx.settings.enabled_keys()))
    chosen = st.selectbox("篩選部門", ["all", *keys], format_func=lambda k: "全部部門" if k == "all" else ctx.settings.label(k))
    records = [r for r in all_records if chosen == "all" or r.department == chosen][:50]
    if not records:
        st.info("還沒有任何紀錄，先到「部門顧問」問第一個問題吧！")
        return
    if chosen == "all":
        counts = pd.Series([r.department for r in all_records]).value_counts()
        st.caption("｜".join(f"{ctx.settings.label(k)} {n} 筆" for k, n in counts.items()))
    for r in records:
        st.markdown(f"**{r.title}**　{r.summary}")
        ctx.show_record(r, "feed")


# ---------------------------------------------------------------------------
# 社團設定（後台）
# ---------------------------------------------------------------------------


def profile_form(prefix: str, profile: ClubProfile | None = None) -> ClubProfile | None:
    """社團資料欄位（建立帳號與社團設定共用），必填欄位不完整時回傳 None。"""
    p = profile
    name = st.text_input("社團名稱＊", value=p.name if p else "", key=f"{prefix}_name")
    category = st.text_input("社團類型", value=p.category if p else "", placeholder="例：學藝性、康樂性、服務性、系學會", key=f"{prefix}_category")
    positioning = st.text_area("社團定位與特色＊", value=p.positioning if p else "", placeholder="例：以街頭攝影與底片攝影為特色，每週社課＋每月外拍", key=f"{prefix}_positioning")
    audience = st.text_area("主要目標受眾＊", value=p.target_audience if p else "", placeholder="例：對攝影有興趣的大一至大三學生，多為初學者", key=f"{prefix}_audience")
    voice = st.text_input("品牌語氣", value=p.brand_voice if p else "", placeholder="例：文青、溫暖、帶點幽默", key=f"{prefix}_voice")
    platforms = st.multiselect(
        "經營平台",
        PLATFORMS,
        default=[x for x in (p.platforms if p else ["Instagram", "Facebook"]) if x in PLATFORMS],
        key=f"{prefix}_platforms",
    )
    budget = st.number_input("每月行銷預算（新台幣）", min_value=0, step=500, value=p.monthly_budget_ntd if p else 0, key=f"{prefix}_budget")
    if not (name.strip() and positioning.strip() and audience.strip()):
        return None
    return ClubProfile(
        name=name.strip(),
        category=category.strip() or "未填寫",
        positioning=positioning.strip(),
        target_audience=audience.strip(),
        brand_voice=voice.strip() or "親切、有活力",
        platforms=platforms or ["Instagram"],
        monthly_budget_ntd=int(budget),
        notes=p.notes if p else "",
    )


def department_settings_form(settings: ClubSettings) -> ClubSettings:
    st.caption("勾選社團有的部門；展開可以改部門名稱，並填寫部門細節（AI 會依細節調整建議）。")
    configs = {}
    for key, d in DEPARTMENTS.items():
        cfg = settings.config(key)
        enabled = st.checkbox(d.label, value=cfg.enabled, key=f"set_en_{key}", help="、".join(d.focus))
        with st.expander(f"{settings.name(key)}：名稱與細節"):
            name = st.text_input("部門名稱（空白則使用預設）", value=cfg.display_name, placeholder=d.name, key=f"set_name_{key}")
            details = st.text_area("部門細節", value=cfg.details, placeholder=d.details_hint, key=f"set_details_{key}")
        configs[key] = DepartmentConfig(enabled=enabled, display_name=name.strip(), details=details.strip())
    return settings.model_copy(update={"departments": configs})


def settings_page(ctx: AppContext) -> None:
    tab_profile, tab_depts, tab_account = st.tabs(["社團資料", "部門設定", "帳號"])
    with tab_profile:
        st.caption("所有部門的顧問都會參考這些資料。")
        updated = profile_form("settings", ctx.club)
        if st.button("儲存社團資料", type="primary"):
            if updated is None:
                st.error("請填寫社團名稱、定位與目標受眾")
            else:
                ctx.store.update_profile(ctx.club_id, updated)
                st.success("已儲存")
                st.rerun()
    with tab_depts:
        new_settings = department_settings_form(ctx.settings)
        if st.button("儲存部門設定", type="primary"):
            try:
                ctx.store.update_settings(ctx.club_id, new_settings)
                st.success("已儲存")
                st.rerun()
            except StoreError as e:
                st.error(str(e))
    with tab_account:
        with st.form("change_password"):
            old = st.text_input("目前的密碼", type="password")
            new = st.text_input("新密碼（至少 6 個字元）", type="password")
            new2 = st.text_input("再輸入一次新密碼", type="password")
            if st.form_submit_button("變更密碼"):
                if new != new2:
                    st.error("兩次輸入的新密碼不一樣")
                else:
                    try:
                        ctx.store.change_password(ctx.club_id, old, new)
                        st.success("密碼已變更，下次登入請使用新密碼")
                    except StoreError as e:
                        st.error(str(e))


# ---------------------------------------------------------------------------
# 使用說明
# ---------------------------------------------------------------------------


def help_page(csv_columns: list[str]) -> None:
    st.markdown(
        """
### 怎麼使用
1. 在左側選擇**我的部門**。
2. **待辦與進度**：記錄部門的任務、負責人與期限；社長可以在總覽看到全社團進度。
3. **行事曆**（最後一個分頁）：全社團的行程都在這裡，包括排好的幹部會議、會議記錄提到的日期、待辦期限與各部門新增的行程；可以匯出到 Google 日曆。
4. **社團動態**：各部門分享的成果都在這裡，彼此看得到。每次產生結果時可以選擇要不要分享。
5. **部門顧問**：
   - 快速問答：直接問社團的事，例如「上次開會決定了什麼？」，AI 會從會議記錄、社團動態與待辦找答案並附出處
   - 顧問建議：描述遇到的狀況，取得行動步驟與可直接使用的文件模板
6. 部分部門有專屬功能：
   - 社長：各部門進度總覽；設定會議時間與時長，自動產生進度彙整、議程與會議時間表；追蹤上次會議還沒決議的議題
   - 會議記錄：上傳會議記錄或 LINE 對話，自動整理重點並對照會前議程，還可以直接問問題
   - 行銷：社群數據診斷、活動宣傳企劃
   - 財務（社長也看得到）：「財務管理」以財務密碼上鎖，可審核報帳、記帳、編預算、下載月報與學期報表（Excel／Word／PDF）
7. **報帳申請**：每個部門都可以申請報帳並用報帳編號查詢進度；單據正本請交給財務。
8. **社團設定**（左側選單下方）：選擇社團有哪些部門、改部門名稱、填寫部門細節、修改密碼。
9. 所有報告都可以下載成 **Word** 或 **PDF**。

### 怎麼匯出 LINE 對話記錄
在 LINE 聊天室右上角選單 →「設定」→「傳送聊天記錄」，存成 .txt 檔後到「會議記錄」上傳。

### 怎麼準備貼文數據 CSV（行銷）
從 IG／FB 的「洞察報告」把每篇貼文的數據填進 CSV 範本，一列一篇，建議至少近三個月。

| 欄位 | 填什麼 |
|---|---|
| date / time | 發文日期（2026-09-28）與時間（21:30） |
| platform | Instagram、Facebook、Dcard… |
| post_type | 圖文、輪播、Reels、公告、限動… |
| topic | 你們自己的分類，例如：活動宣傳、社課花絮 |
| reach | 觸及人數 |
| likes / comments / shares / saves | 按讚、留言、分享、收藏數 |
| followers / caption | 發文當下粉絲數、貼文內文（選填） |
"""
    )
    template = ",".join(csv_columns) + "\n2026-09-01,21:00,Instagram,輪播,活動宣傳,850,60,5,4,12,1200,範例貼文\n"
    st.download_button("下載 CSV 範本", template.encode("utf-8-sig"), file_name="貼文數據範本.csv", mime="text/csv")
    st.markdown(
        """
**小提醒**
- AI 的建議僅供參考，執行前請再確認資訊正確，涉及學校規定時請向校內單位確認。
- 請不要上傳含有個資的檔案（例如報名者姓名、學號、電話）。
"""
    )

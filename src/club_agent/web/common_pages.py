"""所有部門共用的頁面：部門顧問、待辦與進度、AI Agent 問答、社團設定（後台）、使用說明。"""

from __future__ import annotations

from datetime import date

import pandas as pd
import streamlit as st

from ..agents import ClubQA, DepartmentAdvisor, club_retriever
from ..events import club_events, events_digest
from ..departments import CUSTOM_PREFIX, DEPARTMENTS, FEATURES, ClubSettings, DepartmentConfig, department_retriever
from ..meetings import list_meetings
from ..report import advice_markdown, meeting_answer_markdown
from ..schemas import ClubProfile
from ..metrics import TEMPLATE_CSV
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


def advisor_page(ctx: AppContext) -> None:
    advice_section(ctx)


AGENT_EXAMPLES = ("下次發文時間是什麼時候？", "上次開會決定了什麼？", "這個月有哪些活動？", "目前有哪些逾期的任務？")


def club_qa_box(ctx: AppContext, key: str, examples: tuple[str, ...]) -> None:
    """問答搜尋欄：從會議記錄、各部門分享的成果、待辦與行事曆找答案並附出處。"""
    q_key = f"qa_question_{key}"
    with st.form(f"club_qa_{key}", clear_on_submit=False, border=False):
        c1, c2 = st.columns([5, 1], vertical_alignment="bottom")
        question = c1.text_input("想查什麼？", key=q_key, placeholder="例：下次發文時間是什麼時候？成果展預算最後決定多少？")
        submitted = c2.form_submit_button("提問", type="primary", width="stretch")
    cols = st.columns(len(examples))
    for i, example in enumerate(examples):
        if cols[i].button(example, key=f"qa_ex_{key}_{i}", width="stretch", type="tertiary"):
            st.session_state[f"{q_key}_pending"] = example
    pending = st.session_state.pop(f"{q_key}_pending", None)
    if submitted or pending:
        q = (pending or question or "").strip()
        if not q:
            st.warning("請先輸入問題")
        else:
            today = date.today()

            def ask(llm, _status):
                docs = list_meetings(ctx.store, ctx.club_id)
                records = ctx.store.list_records(ctx.club_id, limit=60)
                tasks = tasks_digest(list_tasks(ctx.store, ctx.club_id), ctx.settings, today)
                calendar = events_digest(club_events(ctx.store, ctx.club_id, ctx.settings), today, settings=ctx.settings)
                return ClubQA(llm).run(q, docs, club_retriever(docs, records, ctx.settings.name), tasks, today, calendar)

            # 問答只需要從資料找答案，用最低思考程度回應最快
            answer = ctx.run_ai("翻閱社團資料中…", ask, thinking="minimal")
            if answer:
                st.session_state.setdefault("club_qa_history", []).insert(0, meeting_answer_markdown(q, answer))
    for i, md in enumerate(st.session_state.get("club_qa_history", [])[:5]):
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


def add_task_form(
    ctx: AppContext, key: str, department: str | None = None, project: str = "", source: str = "手動新增",
    default_department: str | None = None,
) -> None:
    """新增任務；department 為 None 時可選擇部門（預設 default_department）。project／source 用於活動籌備清單。"""
    with st.form(f"add_task_{key}", clear_on_submit=True):
        st.markdown("**新增任務**")
        c1, c2 = st.columns([3, 2])
        title = c1.text_input("事項", key=f"t_title_{key}")
        owner = c2.text_input("負責人", key=f"t_owner_{key}")
        c3, c4, c5 = st.columns(3)
        if department is None:
            options = ctx.settings.enabled_keys()
            index = options.index(default_department) if default_department in options else 0
            dept = c3.selectbox("部門", options, index=index, format_func=ctx.settings.name, key=f"t_dept_{key}")
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
                    Task(title=title.strip(), department=dept, owner=owner.strip(), due=due.isoformat() if due else "", status=status,
                         project=project, source=source),
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
    """全社團共用的待辦（側邊欄「幹部共用」）：每位幹部都可以新增、更新；預設只看自己部門。"""
    st.caption("全社團共用的待辦清單，每位幹部都可以新增與更新進度；社長總覽會彙整各部門的進度。")
    add_task_form(ctx, "shared", department=None, default_department=ctx.dept_key)
    c1, c2 = st.columns([2, 1], vertical_alignment="center")
    scope = c1.segmented_control("顯示", [f"{ctx.dept_name}", "全部部門"], default=ctx.dept_name, key=f"todo_scope_{ctx.dept_key}")
    show_done = c2.toggle("顯示已完成", key="todo_show_done")
    mine_only = scope != "全部部門"
    tasks = list_tasks(ctx.store, ctx.club_id, ctx.dept_key if mine_only else None)
    tasks_table(ctx, [t for t in tasks if show_done or t.status != "完成"], "shared", show_department=not mine_only)


# ---------------------------------------------------------------------------
# AI Agent 問答（問答搜尋＋各部門分享的成果）
# ---------------------------------------------------------------------------


def feed_page(ctx: AppContext) -> None:
    st.caption("直接問社團的事，AI Agent 會從各部門分享的成果、會議記錄、待辦與行事曆找答案並附上出處。")
    club_qa_box(ctx, "agent", AGENT_EXAMPLES)

    st.divider()
    st.subheader("各部門分享的成果")
    st.caption("各部門分享的顧問建議、會議重點、診斷與企劃都在這裡，AI Agent 也會用這些內容回答問題。")
    all_records = ctx.store.list_records(ctx.club_id)
    keys = ctx.settings.enabled_keys() + sorted({r.department for r in all_records} - set(ctx.settings.enabled_keys()))
    chosen = st.selectbox("篩選部門", ["all", *keys], format_func=lambda k: "全部部門" if k == "all" else ctx.settings.label(k))
    records = [r for r in all_records if chosen == "all" or r.department == chosen][:50]
    if not records:
        st.info("還沒有任何分享，各部門產生報告或建議時打開「分享給其他部門」就會出現在這裡。")
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


def _feature_label(f: str) -> str:
    return FEATURES[f][0]


def department_settings_form(settings: ClubSettings, prefix: str = "set") -> ClubSettings:
    """部門與分工：勾選社團有的部門、決定每個部門負責哪些功能，並可新增系統沒有的自訂部門。"""
    st.caption("勾選社團有的部門。每個社團的分工不同，展開部門可以改名稱、調整「負責的功能」並填寫部門細節（AI 會依細節調整建議）。"
               "例如公關也負責邀請講者，就把「講座管理」加到公關。")
    with st.popover("各功能模組在做什麼"):
        st.markdown("\n".join(f"- **{label}**：{desc}" for label, desc in FEATURES.values()))
    feature_keys = list(FEATURES)
    configs = {}
    for key, d in DEPARTMENTS.items():
        cfg = settings.config(key)
        current = list(settings.features(key))
        summary = f"（{'、'.join(_feature_label(f) for f in current)}）" if current else ""
        enabled = st.checkbox(f"{settings.name(key)}{summary}", value=cfg.enabled, key=f"{prefix}_en_{key}", help="、".join(d.focus))
        with st.expander(f"{settings.name(key)}：名稱、分工與細節"):
            name = st.text_input("部門名稱（空白則使用預設）", value=cfg.display_name, placeholder=d.name, key=f"{prefix}_name_{key}")
            features = st.multiselect("負責的功能", feature_keys, default=current, format_func=_feature_label,
                                      key=f"{prefix}_feat_{key}", placeholder="沒有專屬功能（只有部門顧問）")
            details = st.text_area("部門細節", value=cfg.details, placeholder=d.details_hint, key=f"{prefix}_details_{key}")
        configs[key] = DepartmentConfig(
            enabled=enabled, display_name=name.strip(), details=details.strip(),
            features=None if features == list(d.features) else features,  # 和預設相同時不另外存，之後預設更新也會跟著更新
        )

    st.markdown("**自訂部門**（系統沒有的部門，例如學術部、外務部）")
    custom_list = f"{prefix}_custom_keys"
    if custom_list not in st.session_state:
        st.session_state[custom_list] = [k for k in settings.custom_keys() if settings.config(k).enabled]
    for key in settings.custom_keys():  # 刪除過的自訂部門保留設定（停用），舊紀錄仍能顯示部門名稱
        if key not in st.session_state[custom_list]:
            configs[key] = settings.config(key).model_copy(update={"enabled": False})
    for key in list(st.session_state[custom_list]):
        cfg = settings.config(key) if key in settings.departments else DepartmentConfig(enabled=True, custom=True)
        with st.container(border=True):
            c1, c2, c3 = st.columns([2, 4, 1], vertical_alignment="bottom")
            name = c1.text_input("部門名稱", value=cfg.display_name, key=f"{prefix}_cname_{key}", placeholder="例：學術部")
            features = c2.multiselect("負責的功能", feature_keys, default=cfg.features or [], format_func=_feature_label,
                                      key=f"{prefix}_cfeat_{key}", placeholder="沒有專屬功能（只有部門顧問）")
            remove = c3.checkbox("刪除", key=f"{prefix}_cdel_{key}")
            details = st.text_input("部門細節（選填）", value=cfg.details, key=f"{prefix}_cdet_{key}",
                                    placeholder="例：負責每學期的讀書會與學術講座")
        if name.strip():
            configs[key] = DepartmentConfig(enabled=not remove, display_name=name.strip(), details=details.strip(),
                                            features=features, custom=True)
    if st.button("新增自訂部門", icon=":material/add:", key=f"{prefix}_add_custom"):
        import uuid

        st.session_state[custom_list].append(f"{CUSTOM_PREFIX}{uuid.uuid4().hex[:6]}")
        st.rerun()
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
                st.session_state.pop("set_custom_keys", None)
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


def help_page() -> None:
    st.markdown(
        """
### 怎麼使用
1. 在左側選擇**我的部門**，上方會直接列出這個部門的功能，最後一個分頁是**部門顧問**：
   描述遇到的狀況，取得行動步驟與可直接使用的文件模板；想查社團的事（例如上次開會決定了什麼）請用左側的「AI Agent 問答」
2. 各部門的專屬功能：
   - 社長：社團總覽（各部門進度、會議時間表與議程、追蹤上次會議未決議的議題）；財務管理
   - 會議記錄：記錄問答、新增記錄（自動整理重點並對照會前議程）、所有記錄
   - 行銷：社群數據診斷、月報與趨勢、設計需求（處理各部門的需求，AI 寫設計說明與文案）、視覺規範
   - 活動：先在上方選擇活動，再使用活動總覽、企劃書、籌備清單（自動成為各部門待辦）、細流與工作人員（含名牌 PDF）、回饋表單、成果報告
   - 公關：找贊助對象（AI 建議類型與搜尋關鍵字）、合作對象、合作信件、贊助彙整
   - 課程：AI 規劃學期課表（自動加入行事曆）、出席與回饋（出席率、趨勢、滿意度）
   - 講者：講座總覽、新增講座、信件與通知、講座彙整
   - 財務（社長也看得到）：輸入財務密碼後，有報帳審核、收支帳簿、預算、財務報表（Excel／Word／PDF）、規範與設定
3. **幹部共用**（左側選單）：全體幹部都會用到的功能，點選後主畫面會切換過去，按「返回部門功能」回來
   - 待辦與進度：每位幹部都可以新增、更新任務；預設只顯示自己部門，可以切換看全部
   - AI Agent 問答：上方可以直接提問（例：下次發文時間是什麼時候？），AI 會從各部門分享的成果、會議記錄、待辦與行事曆找答案；下方列出各部門分享的成果，產生結果時可以選擇要不要分享
   - 行事曆：幹部會議、活動、講座、會議記錄提到的日期、待辦與追蹤期限、各部門新增的行程；可以匯出到 Google 日曆
   - 報帳申請：申請報帳並用報帳編號查詢進度；單據正本請交給財務
   - 設計需求：需要海報、貼文圖、限動時提出，行銷（美宣）會依截止日處理
4. **社團設定**（左側選單下方）：選擇社團有哪些部門、**每個部門負責哪些功能**（例如公關兼講者）、新增系統沒有的自訂部門、改名稱、填寫部門細節、修改密碼。
5. 所有報告都可以下載成 **Word** 或 **PDF**。

### 怎麼匯出 LINE 對話記錄
在 LINE 聊天室右上角選單 →「設定」→「傳送聊天記錄」，存成 .txt 檔後到「會議記錄」上傳。

### 怎麼準備貼文數據 CSV（行銷）
- **最簡單：** 從 Meta Business Suite（或 IG 專業主控板）的洞察報告匯出貼文 CSV，直接上傳，系統會自動對應欄位。
- **自己整理：** 下載下方的範本，一列一篇貼文，建議至少近三個月。欄位名稱用中文或英文都可以。
- **只有日期一定要填**，其他不知道就空著。空白會當成「不知道」，不會當成 0；分析時會排除，AI 也會知道少了什麼。

| 欄位 | 填什麼 | 沒填會怎樣 |
|---|---|---|
| 日期＊ | 發文日期（2026-09-28、2026/9/28 都可以；也可以連同時間寫在一起） | 這篇不列入分析 |
| 時間 | 發文時間（21:30、下午 9:30） | 不列入發文時段分析 |
| 平台 | Instagram、Facebook… | 上傳時選一次整份檔案的平台即可 |
| 形式／主題 | 圖文、輪播、Reels…；你們自己的分類，例如：活動宣傳 | 不列入依形式／主題的比較 |
| 觸及人數 | 看過這篇的人數（建議盡量填） | 無法計算這篇的互動率 |
| 按讚／留言／分享／收藏 | 互動數；IG 沒有分享數就空著 | 互動率只用有填的項目計算 |
| 粉絲數／內文 | 發文當下粉絲數、貼文內容 | 無法分析粉絲成長；AI 只能依數字分析 |

"""
    )
    template = TEMPLATE_CSV
    st.download_button("下載 CSV 範本", template.encode("utf-8-sig"), file_name="貼文數據範本.csv", mime="text/csv")
    st.markdown(
        """
**小提醒**
- AI 的建議僅供參考，執行前請再確認資訊正確，涉及學校規定時請向校內單位確認。
- 請不要上傳含有個資的檔案（例如報名者姓名、學號、電話）。
"""
    )

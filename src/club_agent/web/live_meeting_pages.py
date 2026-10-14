"""開會模式：選擇議程 → 開始會議 → 逐項計時、記錄重點／決議／待辦 → 結束後直接產生會議記錄與待辦。"""

from __future__ import annotations

from datetime import date, datetime

import pandas as pd
import streamlit as st

from ..agenda import list_plans, parse_time
from ..live_meeting import (
    CANCELLED,
    LiveMeeting,
    add_item,
    clock,
    next_meeting_date,
    running_meeting,
    save_live,
    start_meeting,
    to_meeting_doc,
)
from ..meetings import save_meeting
from ..report import meeting_summary_markdown
from ..schemas import ActionItem
from ..tasks import Task, save_task
from .context import AppContext

ADHOC = "__adhoc__"


def _flash(message: str) -> None:
    st.session_state.live_flash = message
    st.rerun()


def _text(value) -> str:
    return "" if value is None or (not isinstance(value, str) and pd.isna(value)) else str(value).strip()


def live_meeting_page(ctx: AppContext) -> None:
    if message := st.session_state.pop("live_flash", None):
        st.success(message)
    meeting = running_meeting(ctx.store, ctx.club_id)
    if meeting is None:
        setup_view(ctx)
    else:
        running_view(ctx, meeting)


# ---------------------------------------------------------------------------
# 開始前
# ---------------------------------------------------------------------------


def setup_view(ctx: AppContext) -> None:
    st.caption("開會時打開這一頁：依議程逐項進行並計時，邊開會邊記下討論重點、決議與待辦。"
               "結束後直接產生會議記錄並加入待辦，不需要會後再整理，也不會用到 AI 額度。")
    today = date.today().isoformat()
    plans = [p for p in list_plans(ctx.store, ctx.club_id) if p.date >= today]
    plans.sort(key=lambda p: p.date)
    options = [*[p.id for p in plans], ADHOC]
    by_id = {p.id: p for p in plans}
    choice = st.selectbox(
        "要開哪一場會議", options,
        format_func=lambda k: "臨時會議（沒有排議程）" if k == ADHOC else f"{by_id[k].label()}" + ("（今天）" if k == today else ""),
        key=f"live_plan_{'_'.join(options)}",  # 議程有變動時（例如剛排好今天的議程）重新預設為最近的那一場
    )
    plan = by_id.get(choice)
    if plan:
        st.markdown("\n".join(f"{n}. {r.topic}（{r.kind}，{r.minutes} 分鐘）" for n, r in enumerate(plan.agenda, 1))
                    or "（這份議程沒有議題）")
        if plan.video_link:
            st.link_button("加入視訊會議", plan.video_link, icon=":material/videocam:")
    else:
        st.caption("臨時會議會從「討論事項」開始，開會中可以隨時新增議題。社長在「社團總覽」排好議程，這裡就能直接選。")
    c1, c2 = st.columns([3, 1], vertical_alignment="bottom")
    title = c1.text_input("會議名稱", value=f"{plan.date if plan else today} 幹部會議", key="live_title")
    attendees = st.text_input("出席者（選填，用逗號分開）", placeholder="例：社長、小明、小華", key="live_attendees")
    if c2.button("開始會議", type="primary", icon=":material/play_arrow:", width="stretch"):
        meeting = start_meeting(plan, title.strip() or "幹部會議", attendees)
        save_live(ctx.store, ctx.club_id, meeting)
        _flash("會議開始！第一個議題已經開始計時")


# ---------------------------------------------------------------------------
# 會議進行中
# ---------------------------------------------------------------------------


@st.fragment(run_every=1)
def timer(meeting: LiveMeeting) -> None:
    """每秒更新的計時器（只重畫這一小塊）。"""
    now = datetime.now()
    left = meeting.remaining(now)
    item = meeting.items[meeting.current]
    c1, c2 = st.columns(2)
    color = "red" if left < 0 else ("orange" if left <= 60 else "blue")
    c1.markdown(f"#### 本議題 :{color}[{clock(left)}]" + ("　**已超時**" if left < 0 else ""))
    c1.caption(f"預定 {item.minutes} 分鐘")
    elapsed = meeting.elapsed(now)
    c2.markdown(f"#### 會議已進行 {clock(elapsed)}")
    over = elapsed - meeting.planned_minutes * 60
    c2.caption(f"預定 {meeting.planned_minutes} 分鐘" + (f"，已超過 {over // 60} 分鐘" if over > 60 else ""))


def _store_inputs(ctx: AppContext, meeting: LiveMeeting, notes: str, decisions: str, actions_df: pd.DataFrame) -> LiveMeeting:
    """把目前議題的輸入存回會議資料。"""
    names = {ctx.settings.name(k): k for k in ctx.settings.enabled_keys()}
    actions = []
    for row in actions_df.to_dict("records"):
        task = _text(row.get("事項"))
        if not task:
            continue
        due = row.get("期限")
        actions.append(ActionItem(task=task, department=names.get(_text(row.get("部門")), ctx.dept_key), owner=_text(row.get("負責人")),
                                  due=due.isoformat() if isinstance(due, date) else ""))
    items = [i.model_copy() for i in meeting.items]
    items[meeting.current] = items[meeting.current].model_copy(update={
        "notes": notes.strip(), "decisions": [d.strip() for d in decisions.splitlines() if d.strip()], "actions": actions})
    return meeting.model_copy(update={"items": items})


def running_view(ctx: AppContext, meeting: LiveMeeting) -> None:
    head = f"**{meeting.title}**　{meeting.location or ''}"
    c1, c2 = st.columns([4, 1], vertical_alignment="center")
    c1.markdown(head + (f"  \n出席：{meeting.attendees}" if meeting.attendees else ""))
    if meeting.video_link:
        c2.link_button("加入視訊會議", meeting.video_link, icon=":material/videocam:", width="stretch")
    timer(meeting)

    marks = []
    for n, item in enumerate(meeting.items):
        mark = "▶" if n == meeting.current else ("✓" if item.visited else "○")
        spent = f"，實際 {round(meeting.item_spent(n) / 60)} 分" if item.visited and n != meeting.current else ""
        marks.append(f"{mark} {n + 1}. {item.topic}（{item.minutes} 分{spent}）")
    with st.expander(f"議程（第 {meeting.current + 1}／{len(meeting.items)} 項）", expanded=False):
        st.markdown("  \n".join(marks))

    item = meeting.items[meeting.current]
    st.subheader(f"{meeting.current + 1}. {item.topic}")
    meta = "｜".join(x for x in (item.kind, item.department, f"目標：{item.goal}" if item.goal else "") if x)
    if meta:
        st.caption(meta)
    key = f"{meeting.id}_{meeting.current}"
    notes = st.text_area("討論重點", value=item.notes, height=140, key=f"live_notes_{key}",
                         placeholder="邊討論邊記：大家提出的意見、數字、還需要確認的事")
    decisions = st.text_area("決議（一行一項）", value="\n".join(item.decisions), height=90, key=f"live_dec_{key}",
                             placeholder="例：成果展預算 3 萬元")
    names = [ctx.settings.name(k) for k in ctx.settings.enabled_keys()]
    actions_df = st.data_editor(
        pd.DataFrame({
            "事項": pd.Series([a.task for a in item.actions], dtype="object"),
            "部門": pd.Series([ctx.settings.name(a.department) for a in item.actions], dtype="object"),
            "負責人": pd.Series([a.owner for a in item.actions], dtype="object"),
            "期限": pd.Series([date.fromisoformat(a.due) if a.due else None for a in item.actions], dtype="object"),
        }),
        key=f"live_actions_{key}", num_rows="dynamic", hide_index=True, width="stretch",
        column_config={
            "部門": st.column_config.SelectboxColumn(options=names, default=ctx.dept_name),
            "期限": st.column_config.DateColumn(format="YYYY-MM-DD"),
        },
    )
    st.caption("待辦：在表格最下方新增一列。切換議題或結束會議時會自動儲存。")

    c1, c2, c3, c4 = st.columns(4)
    if c1.button("上一個議題", disabled=meeting.current == 0, width="stretch", icon=":material/arrow_back:"):
        updated = _store_inputs(ctx, meeting, notes, decisions, actions_df).switch_to(meeting.current - 1)
        save_live(ctx.store, ctx.club_id, updated)
        st.rerun()
    if c2.button("儲存", width="stretch", icon=":material/save:"):
        save_live(ctx.store, ctx.club_id, _store_inputs(ctx, meeting, notes, decisions, actions_df))
        _flash("已儲存")
    last = meeting.current == len(meeting.items) - 1
    if c3.button("下一個議題", type="primary", disabled=last, width="stretch", icon=":material/arrow_forward:"):
        updated = _store_inputs(ctx, meeting, notes, decisions, actions_df).switch_to(meeting.current + 1)
        save_live(ctx.store, ctx.club_id, updated)
        st.rerun()
    with c4.popover("臨時動議", icon=":material/add:", width="stretch"):
        topic = st.text_input("議題", key=f"live_new_{meeting.id}")
        minutes = st.number_input("預定分鐘", min_value=1, max_value=120, value=10, key=f"live_new_min_{meeting.id}")
        if st.button("加到議程最後", key=f"live_add_{meeting.id}") and topic.strip():
            updated = add_item(_store_inputs(ctx, meeting, notes, decisions, actions_df), topic, int(minutes))
            save_live(ctx.store, ctx.club_id, updated)
            _flash(f"已加入臨時動議「{topic.strip()}」")

    st.divider()
    with st.expander("結束會議", icon=":material/stop_circle:", expanded=last):
        st.caption("結束後會產生會議記錄（存在「會議記錄」），議程對照會標出已決議與還沒討論的議題，待辦會加入各部門的待辦清單。")
        c1, c2, c3 = st.columns(3)
        next_day = c1.date_input("下次開會日期（選填）", value=None, key=f"live_next_{meeting.id}")
        next_time = c2.time_input("時間", value=parse_time(ctx.settings.meeting.start), step=300, key=f"live_next_time_{meeting.id}")
        next_place = c3.text_input("地點", value=meeting.location, key=f"live_next_place_{meeting.id}")
        add_tasks = st.checkbox("把待辦加入各部門的待辦清單", value=True, key=f"live_tasks_{meeting.id}")
        share = ctx.share_toggle(f"live_{meeting.id}")
        if st.button("結束會議並產生記錄", type="primary", icon=":material/task_alt:"):
            finished = _store_inputs(ctx, meeting, notes, decisions, actions_df).finish()
            nxt = next_meeting_date(next_day, f"{next_time:%H:%M}" if next_time else "", next_place.strip())
            doc = to_meeting_doc(finished, nxt, ctx.settings.name)
            save_meeting(ctx.store, ctx.club_id, doc)
            if add_tasks:
                for a in doc.summary.action_items:
                    save_task(ctx.store, ctx.club_id, Task(title=a.task, department=a.department, owner=a.owner, due=a.due,
                                                           source=f"會議記錄「{doc.title}」"))
            if share:
                md = meeting_summary_markdown(doc.title, doc.date, doc.summary, ctx.settings.name)
                ctx.save_record("meeting", doc.title, doc.summary.summary[:150], md, department="minutes")
            save_live(ctx.store, ctx.club_id, finished.model_copy(update={"meeting_doc_id": doc.id}))
            tasks = f"，{len(doc.summary.action_items)} 項待辦已加入待辦清單" if add_tasks and doc.summary.action_items else ""
            _flash(f"會議結束，記錄已存在「會議記錄」{tasks}。" + ("下次開會日期已加入行事曆。" if nxt else ""))
        with st.popover("取消這場會議（不產生記錄）"):
            st.caption("已經記下的內容會被捨棄。")
            if st.button("確定取消", key=f"live_cancel_{meeting.id}"):
                save_live(ctx.store, ctx.club_id, meeting.model_copy(update={"status": CANCELLED}))
                _flash("已取消這場會議")

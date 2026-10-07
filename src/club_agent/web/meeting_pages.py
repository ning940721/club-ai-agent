"""會議記錄部門：上傳會議記錄／LINE 對話 → 重點彙整；對所有記錄提問；待辦一鍵加入任務。"""

from __future__ import annotations

from datetime import date
from typing import Callable

import streamlit as st

from ..agenda import find_plan_for, get_plan, list_plans
from ..agents import MeetingQA, MeetingSummarizer
from ..meetings import (
    SOURCE_TYPES,
    MeetingDoc,
    build_retriever,
    delete_meeting,
    extract_text,
    list_meetings,
    prepare_text,
    save_meeting,
)
from ..report import meeting_answer_markdown, meeting_summary_markdown
from ..tasks import Task, save_task
from .context import AppContext, demote_headings


def _summary_md(ctx: AppContext, doc: MeetingDoc) -> str:
    if not doc.summary:
        return f"# {doc.title}（{doc.date}）\n\n（尚未整理重點）\n"
    return meeting_summary_markdown(doc.title, doc.date, doc.summary, ctx.settings.name)


def ask_section(ctx: AppContext, docs: list[MeetingDoc]) -> None:
    st.caption("根據所有已上傳的會議記錄與 LINE 對話回答，並附上原文出處。例：下次開會時間是什麼時候？成果展預算決定多少？")
    if not docs:
        st.info("還沒有任何記錄，先到「新增記錄」上傳會議記錄或 LINE 對話。")
        return
    with st.form("meeting_qa", clear_on_submit=False):
        question = st.text_input("你的問題", key="meeting_question")
        submitted = st.form_submit_button("提問", type="primary")
    if submitted:
        if not question.strip():
            st.warning("請先輸入問題")
        else:
            q = question.strip()
            # 問答只需要從記錄找答案，用最低思考程度回應最快
            answer = ctx.run_ai(
                "翻閱記錄中…", lambda llm, _s: MeetingQA(llm).run(q, docs, build_retriever(docs)), thinking="minimal"
            )
            if answer:
                history = st.session_state.setdefault("meeting_qa_history", [])
                history.insert(0, meeting_answer_markdown(q, answer))
    for i, md in enumerate(st.session_state.get("meeting_qa_history", [])):
        if i:
            st.divider()
        st.markdown(md)


def plan_picker(ctx: AppContext, meeting_date: date) -> str:
    """選擇要對照的會議議程（社長在總覽排好的時間表）；預設選日期最接近的那份。"""
    plans = list_plans(ctx.store, ctx.club_id)
    if not plans:
        return ""
    matched = find_plan_for(plans, meeting_date.isoformat())
    options = ["", *[p.id for p in plans]]
    labels = {"": "不對照議程", **{p.id: p.label() for p in plans}}
    return st.selectbox(
        "對照會前議程",
        options,
        index=options.index(matched.id) if matched else 0,
        format_func=labels.get,
        key=f"m_plan_{meeting_date.isoformat()}",  # 換日期時重新選擇最接近的議程
        help="AI 會逐一檢查議程上每個議題是否已有決議，社長總覽會列出還沒完成的議題",
    )


def summarize(ctx: AppContext, llm, doc: MeetingDoc):
    plan = get_plan(ctx.store, ctx.club_id, doc.plan_id)
    agenda = plan.agenda_text() if plan else ""
    return MeetingSummarizer(llm).run(ctx.settings, doc.title, doc.date, doc.source_type, doc.text, agenda)


def add_section(ctx: AppContext) -> None:
    c1, c2, c3 = st.columns([2, 2, 3])
    source_type = c1.selectbox("類型", SOURCE_TYPES, key="m_type")
    meeting_date = c2.date_input("日期", value=date.today(), key="m_date")
    title = c3.text_input("標題", placeholder="例：第 5 次幹部會、成果展籌備群組", key="m_title")
    uploaded = st.file_uploader("上傳檔案（.txt／.md／.docx；LINE 請用「傳送聊天記錄」匯出的 .txt）", type=["txt", "md", "docx"], key="m_file")
    pasted = st.text_area("或直接貼上內容", height=200, key="m_text")
    plan_id = plan_picker(ctx, meeting_date)

    col_a, col_b = st.columns(2)
    summarize_clicked = col_a.button("整理重點並儲存", type="primary", key="m_summarize")
    save_only_clicked = col_b.button("只儲存，不整理（不使用 AI 額度）", key="m_save_only")
    st.toggle("整理後把重點放到「成果分享」", value=True, key="share_meeting",
              help="記錄本身一定會存在「會議記錄」裡，可以提問；這個選項只決定重點要不要出現在成果分享")
    if not (summarize_clicked or save_only_clicked):
        return
    try:
        raw = extract_text(uploaded.name, uploaded.getvalue()) if uploaded is not None else pasted
    except (ValueError, KeyError) as e:
        st.error(f"檔案讀取失敗：{e}")
        return
    text = prepare_text(raw or "", source_type)
    if not text.strip():
        st.warning("請上傳檔案或貼上內容")
        return
    doc = MeetingDoc(
        title=title.strip() or (uploaded.name.rsplit(".", 1)[0] if uploaded else f"{source_type} {meeting_date}"),
        date=meeting_date.isoformat(),
        source_type=source_type,
        text=text,
        plan_id=plan_id,
    )
    if summarize_clicked:
        summary = ctx.run_ai("整理重點中…", lambda llm, _s: summarize(ctx, llm, doc), "整理完成")
        if summary is None:
            return
        doc.summary = summary
        if st.session_state.get("share_meeting", True):
            ctx.save_record("meeting", doc.title, summary.summary[:150], _summary_md(ctx, doc), department="minutes")
    save_meeting(ctx.store, ctx.club_id, doc)
    st.session_state.last_meeting_id = doc.id
    st.success(f"已儲存「{doc.title}」")


def action_items_to_tasks(ctx: AppContext, doc: MeetingDoc) -> None:
    if not doc.summary or not doc.summary.action_items:
        return
    items = doc.summary.action_items
    labels = [f"{a.task}（{ctx.settings.name(a.department)}｜{a.owner or '未指定'}｜{a.due or '無期限'}）" for a in items]
    chosen = st.multiselect("選擇要加入「待辦與進度」的事項", range(len(items)), default=list(range(len(items))),
                            format_func=lambda i: labels[i], key=f"ai_pick_{doc.id}")
    if st.button("加入待辦", key=f"ai_add_{doc.id}"):
        for i in chosen:
            a = items[i]
            save_task(ctx.store, ctx.club_id, Task(title=a.task, department=a.department, owner=a.owner, due=a.due,
                                                   source=f"會議記錄「{doc.title}」"))
        st.success(f"已加入 {len(chosen)} 項待辦，各部門可在「待辦與進度」看到")


def records_section(ctx: AppContext, docs: list[MeetingDoc]) -> None:
    if not docs:
        st.info("還沒有任何記錄。")
        return
    for doc in docs:
        with st.expander(f"{doc.date}｜{doc.source_type}｜{doc.title}", expanded=doc.id == st.session_state.get("last_meeting_id")):
            st.markdown(demote_headings(_summary_md(ctx, doc)))
            action_items_to_tasks(ctx, doc)
            if not doc.summary and st.button("整理重點", key=f"sum_{doc.id}"):
                summary = ctx.run_ai("整理重點中…", lambda llm, _s, d=doc: summarize(ctx, llm, d))
                if summary:
                    doc.summary = summary
                    save_meeting(ctx.store, ctx.club_id, doc)
                    if st.session_state.get("share_meeting", True):
                        ctx.save_record("meeting", doc.title, summary.summary[:150], _summary_md(ctx, doc), department="minutes")
                    st.rerun()
            if st.toggle("顯示原文", key=f"raw_{doc.id}"):
                st.text(doc.text[:20000] + ("\n…（以下省略）" if len(doc.text) > 20000 else ""))
            if st.button("刪除這筆記錄", key=f"del_{doc.id}"):
                delete_meeting(ctx.store, ctx.club_id, doc.id)
                st.rerun()


def meeting_tabs(ctx: AppContext) -> list[tuple[str, Callable[[], None]]]:
    docs = list_meetings(ctx.store, ctx.club_id)
    return [
        ("記錄問答", lambda: ask_section(ctx, docs)),
        ("新增記錄", lambda: add_section(ctx)),
        (f"所有記錄（{len(docs)}）", lambda: records_section(ctx, list_meetings(ctx.store, ctx.club_id))),
    ]

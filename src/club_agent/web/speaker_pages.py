"""講者部門：講座總覽與邀約進度、候選時間敲定、AI 信件與宣傳通知、講座彙整。"""

from __future__ import annotations

from datetime import date, datetime, time
from urllib.parse import quote

import pandas as pd
import streamlit as st

from ..agents import LetterWriter
from ..finance import get_settings as finance_settings
from ..speakers import (
    FORMATS,
    STAGES,
    SavedMessage,
    Talk,
    TimeSlot,
    confirm,
    delete_talk,
    list_talks,
    needs_follow_up,
    save_talk,
    talks_markdown,
)
from .context import AppContext, download_buttons

LETTER_KINDS = {
    "邀請信": "第一次邀請講者：介紹社團與來意，說明講座主題、對象與人數、形式，提出候選時間與講師費，請對方回覆意願與方便的時間",
    "追蹤信": "對方還沒回覆或仍在洽談：禮貌提醒並重申重點與候選時間，請對方回覆",
    "確認信": "時間已敲定：確認日期時間、地點或線上連結、講師費與撥付方式、設備需求、當天聯絡人，並請講者提供簡介與照片供宣傳",
    "行前提醒": "講座前 2–3 天寄給講者：提醒時間地點、交通與報到方式、設備準備、當天聯絡人",
    "感謝信": "講座結束後：感謝講者，分享現場反應與參加人數【待補】，說明講師費撥付時間",
    "社員宣傳通知": "對內通知，給社員：介紹講者與主題亮點，寫清楚時間地點與報名方式，適合貼在 IG 與社團群組",
}


def _time(text: str, default: time) -> time:
    try:
        return datetime.strptime(text, "%H:%M").time()
    except (TypeError, ValueError):
        return default


def _flash(message: str) -> None:
    st.session_state.speaker_flash = message
    st.rerun()


def speakers_page(ctx: AppContext) -> None:
    if message := st.session_state.pop("speaker_flash", None):
        st.success(message)
    talks = list_talks(ctx.store, ctx.club_id)
    tab_list, tab_new, tab_letters, tab_summary = st.tabs([f"講座總覽（{len(talks)}）", "新增講座", "信件與通知", "講座彙整"])
    with tab_list:
        overview(ctx, talks)
    with tab_new:
        new_talk(ctx)
    with tab_letters:
        letters_section(ctx, talks)
    with tab_summary:
        summary_section(ctx, talks)


# ---------------------------------------------------------------------------
# 新增／編輯
# ---------------------------------------------------------------------------


def talk_fields(prefix: str, t: Talk | None) -> dict:
    """講座資料欄位（放在 st.form 裡）。"""
    t = t or Talk(speaker="", topic="")
    c1, c2, c3 = st.columns(3)
    speaker = c1.text_input("講者姓名＊", value=t.speaker, key=f"{prefix}_speaker")
    affiliation = c2.text_input("單位與職稱", value=t.affiliation, placeholder="例：自由攝影師、某某公司設計總監", key=f"{prefix}_aff")
    contact = c3.text_input("聯絡方式", value=t.contact, placeholder="Email 或 IG 帳號", key=f"{prefix}_contact")
    topic = st.text_input("講座主題＊", value=t.topic, placeholder="例：用手機拍出好看的街拍", key=f"{prefix}_topic")
    description = st.text_area("想請講者分享的內容", value=t.description, height=80, key=f"{prefix}_desc")
    c4, c5, c6, c7 = st.columns(4)
    audience = c4.text_input("對象與人數", value=t.audience, placeholder="例：社員約 40 人", key=f"{prefix}_aud")
    fmt = c5.selectbox("形式", FORMATS, index=FORMATS.index(t.format) if t.format in FORMATS else 0, key=f"{prefix}_fmt")
    location = c6.text_input("地點", value=t.location, key=f"{prefix}_loc")
    fee = c7.number_input("講師費（元）", min_value=0, step=100, value=t.fee, key=f"{prefix}_fee")
    c8, c9, c10 = st.columns(3)
    stage = c8.selectbox("進度", STAGES, index=STAGES.index(t.stage) if t.stage in STAGES else 0, key=f"{prefix}_stage")
    owner = c9.text_input("負責幹部", value=t.owner, key=f"{prefix}_owner")
    follow = c10.date_input("下次追蹤日（選填）", value=date.fromisoformat(t.follow_up) if t.follow_up else None, key=f"{prefix}_follow")
    notes = st.text_input("備註", value=t.notes, key=f"{prefix}_notes")
    return {
        "speaker": speaker.strip(), "affiliation": affiliation.strip(), "contact": contact.strip(), "topic": topic.strip(),
        "description": description.strip(), "audience": audience.strip(), "format": fmt, "location": location.strip(),
        "fee": int(fee), "stage": stage, "owner": owner.strip(), "follow_up": follow.isoformat() if follow else "",
        "notes": notes.strip(),
    }


def new_talk(ctx: AppContext) -> None:
    st.caption("先記下想邀請的講者與主題，進度選「待聯絡」；之後到「信件與通知」產生邀請信。聯絡方式只有登入社團帳號的幹部看得到。")
    with st.form("talk_new", clear_on_submit=True):
        data = talk_fields("tn", None)
        if st.form_submit_button("新增講座", type="primary"):
            if not data["speaker"] or not data["topic"]:
                st.warning("請填寫講者姓名與講座主題")
            else:
                save_talk(ctx.store, ctx.club_id, Talk(**data))
                _flash(f"已新增「{data['speaker']}｜{data['topic']}」")


def overview(ctx: AppContext, talks: list[Talk]) -> None:
    today = date.today()
    if not talks:
        st.info("還沒有講座，到「新增講座」記下第一位想邀請的講者。")
        return
    for t in needs_follow_up(talks, today):
        st.warning(f"該追蹤了：{t.title()}（{t.stage}，追蹤日 {t.follow_up}，負責 {t.owner or '未指定'}）")
    counts = {s: sum(t.stage == s for t in talks) for s in STAGES}
    st.caption("　".join(f"{s} {n}" for s, n in counts.items() if n))
    show_closed = st.toggle("顯示已完成與婉拒的講座", key="talk_show_closed")
    for t in talks:
        if t.stage in ("已完成", "婉拒") and not show_closed:
            continue
        with st.expander(f"{t.stage}｜{t.title()}｜{t.when()}"):
            talk_detail(ctx, t)


def talk_detail(ctx: AppContext, t: Talk) -> None:
    with st.form(f"talk_edit_{t.id}", border=False):
        data = talk_fields(f"te_{t.id}", t)
        if st.form_submit_button("儲存變更"):
            if not data["speaker"] or not data["topic"]:
                st.warning("講者姓名與講座主題不能空白")
            else:
                save_talk(ctx.store, ctx.club_id, t.model_copy(update=data))
                _flash("已儲存")

    st.markdown("**候選時間與敲定**")
    if t.confirmed:
        st.markdown(f"已敲定：**{t.confirmed.label()}**（已加入行事曆）")
    # 指定欄位型別：沒有候選時間時，空表格的欄位才不會被當成數字而無法編輯
    df = pd.DataFrame(
        {
            "日期": pd.Series([date.fromisoformat(c.date) for c in t.candidates], dtype="object"),
            "開始": pd.Series([_time(c.start, time(19)) for c in t.candidates], dtype="object"),
            "結束": pd.Series([_time(c.end, time(21)) for c in t.candidates], dtype="object"),
        }
    )
    edited = st.data_editor(
        df, key=f"talk_slots_{t.id}", num_rows="dynamic", hide_index=True,
        column_config={
            "日期": st.column_config.DateColumn(format="YYYY-MM-DD", required=True),
            "開始": st.column_config.TimeColumn(format="HH:mm", step=900, default=time(19)),
            "結束": st.column_config.TimeColumn(format="HH:mm", step=900, default=time(21)),
        },
    )
    slots = []
    for row in edited.to_dict("records"):
        if row["日期"] is None or pd.isna(row["日期"]):
            continue
        start = row["開始"] if isinstance(row["開始"], time) else time(19)
        end = row["結束"] if isinstance(row["結束"], time) else time(21)
        slots.append(TimeSlot(date=row["日期"].isoformat(), start=f"{start:%H:%M}", end=f"{end:%H:%M}"))
    c1, c2, c3 = st.columns([1, 2, 1], vertical_alignment="bottom")
    if c1.button("儲存候選時間", key=f"talk_save_slots_{t.id}"):
        save_talk(ctx.store, ctx.club_id, t.model_copy(update={"candidates": slots}))
        _flash(f"已儲存 {len(slots)} 個候選時間")
    if slots:
        labels = [s.label() for s in slots]
        pick = c2.selectbox("講者可以的時間", range(len(slots)), format_func=lambda i: labels[i], key=f"talk_pick_{t.id}")
        if c3.button("敲定這個時間", key=f"talk_confirm_{t.id}", type="primary"):
            save_talk(ctx.store, ctx.club_id, confirm(t.model_copy(update={"candidates": slots}), slots[pick]))
            _flash(f"已敲定 {slots[pick].label()}，並加入行事曆")
    if t.confirmed and st.button("取消已敲定的時間", key=f"talk_unconfirm_{t.id}", type="tertiary"):
        save_talk(ctx.store, ctx.club_id, t.model_copy(update={"confirmed": None, "stage": "洽談中"}))
        _flash("已取消敲定，進度改回洽談中")

    if t.messages:
        st.markdown(f"**往來信件與通知（{len(t.messages)}）**")
        for m in reversed(t.messages):
            with st.popover(f"{m.created_at[:10]}｜{m.kind}｜{m.subject[:24]}"):
                st.markdown(f"**{m.subject}**")
                st.text(m.body)
    if st.button("刪除這場講座", key=f"talk_del_{t.id}", type="tertiary"):
        delete_talk(ctx.store, ctx.club_id, t.id)
        _flash(f"已刪除「{t.title()}」")


# ---------------------------------------------------------------------------
# 信件與通知
# ---------------------------------------------------------------------------


def letters_section(ctx: AppContext, talks: list[Talk]) -> None:
    active = [t for t in talks if t.stage != "婉拒"]
    if not active:
        st.info("先到「新增講座」建立講座，才能產生信件。")
        return
    st.caption("AI 依講座資料撰寫信件；資料不足的地方會標示【待補】，寄出前請檢查並修改。")
    c1, c2 = st.columns([3, 2])
    ids = [t.id for t in active]
    by_id = {t.id: t for t in active}
    talk_id = c1.selectbox("講座", ids, format_func=lambda i: f"{by_id[i].title()}（{by_id[i].stage}）", key="letter_talk")
    kind = c2.selectbox("要寫什麼", list(LETTER_KINDS), key="letter_kind", help="、".join(f"{k}：{v[:18]}…" for k, v in LETTER_KINDS.items()))
    st.caption(LETTER_KINDS[kind])
    extra = st.text_input("補充要求（選填）", placeholder="例：講者是學長，語氣可以輕鬆一點；報名連結是 forms.gle/xxxx", key="letter_extra")
    talk = by_id[talk_id]
    if st.button("產生", type="primary", key="letter_go"):
        sender = ctx.settings.name("speakers")
        letter = ctx.run_ai(f"撰寫{kind}中…", lambda llm, _s: LetterWriter(llm).run(ctx.club, sender, kind, LETTER_KINDS[kind], talk.facts(), extra))
        if letter:
            st.session_state.letter_draft = (talk.id, kind, letter)
            st.session_state.letter_version = st.session_state.get("letter_version", 0) + 1

    draft = st.session_state.get("letter_draft")
    if not draft or draft[0] != talk.id or draft[1] != kind:
        return
    _, _, letter = draft
    v = st.session_state.get("letter_version", 0)
    st.divider()
    subject = st.text_input("主旨", value=letter.subject, key=f"letter_subject_{v}")
    body = st.text_area("內文（可以直接修改）", value=letter.body, height=320, key=f"letter_body_{v}")
    short = st.text_area("LINE／簡訊短版", value=letter.short_text, height=100, key=f"letter_short_{v}")
    c1, c2, c3 = st.columns(3)
    if c1.button("存到這場講座的紀錄", key=f"letter_save_{v}"):
        updated = talk.model_copy(update={"messages": [*talk.messages, SavedMessage(kind=kind, subject=subject, body=body, short_text=short)]})
        if kind == "邀請信" and talk.stage == "待聯絡":
            updated = updated.model_copy(update={"stage": "已邀請"})
        save_talk(ctx.store, ctx.club_id, updated)
        _flash(f"已存到「{talk.title()}」的往來紀錄" + ("，進度改為已邀請" if updated.stage != talk.stage else ""))
    if "@" in talk.contact and kind != "社員宣傳通知":
        mail = f"mailto:{talk.contact}?subject={quote(subject)}&body={quote(body[:1500])}"
        c2.link_button("用郵件程式開啟", mail, icon=":material/mail:")
    elif kind != "社員宣傳通知":
        c2.caption("填寫講者 Email 後，可以直接用郵件程式開啟。")
    download_buttons(f"# {subject}\n\n{body}\n\n---\n\n**短版**\n\n{short}\n", f"{kind}_{talk.speaker}", f"letter_{v}")
    if kind == "社員宣傳通知":
        # 分享的是修改後的最新內容；換一份通知時重新開始
        title = f"講座通知：{talk.topic}"
        item = st.session_state.get("result_talk_notice")
        if item is None or item.get("version") != v:
            ctx.keep_result("talk_notice", "notice", title, short[:150], "", share=False, department="speakers")
            item = st.session_state["result_talk_notice"]
            item["version"] = v
        if not item["shared"]:
            item.update(markdown=f"# {subject}\n\n{body}\n", summary=short[:150])
        ctx.share_controls("talk_notice")


# ---------------------------------------------------------------------------
# 講座彙整
# ---------------------------------------------------------------------------


def summary_section(ctx: AppContext, talks: list[Talk]) -> None:
    scope = st.segmented_control("範圍", ["本學期", "全部"], default="本學期", key="talk_scope") or "本學期"
    start, end = finance_settings(ctx.store, ctx.club_id).term(date.today()) if scope == "本學期" else (None, None)
    md = talks_markdown(ctx.club.name, talks, start, end)
    st.markdown(md)
    download_buttons(md, "講座彙整", "talk_summary")

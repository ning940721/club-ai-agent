"""公關部門：合作對象名單與聯絡進度、AI 建議贊助對象、信件、贊助彙整。"""

from __future__ import annotations

from datetime import date
from typing import Callable
from urllib.parse import quote_plus

import streamlit as st

from ..agents import SponsorAdvisor
from ..partners import (
    STAGES,
    TYPES,
    Partner,
    SavedMessage,
    delete_partner,
    list_partners,
    needs_follow_up,
    save_partner,
    sponsorship_markdown,
)
from ..projects import list_projects
from .context import AppContext, download_buttons
from .letters import letter_workbench

PR_LETTERS = {
    "贊助邀請信": "第一次邀請贊助：介紹社團與活動（時間、地點、人數、受眾），說明為什麼找這個對象，列出請求內容與對應的回饋，附回覆期限",
    "合作提案信": "邀請合辦或跨社團／校外合作：說明合作構想、雙方分工與好處，提出下一步（例如約時間討論）",
    "追蹤信": "對方還沒回覆或仍在洽談：禮貌提醒並簡短重申重點，提供更方便的回覆方式",
    "確認信": "合作已談成：確認雙方約定（贊助內容、回饋項目、時間、交付方式、聯絡人），請對方提供 logo 或資料",
    "感謝信": "活動結束後：感謝對方支持，簡述活動成果與人數【待補】，表達希望持續合作",
    "成果回報信": "給贊助商的結案報告：逐項回報承諾的回饋（貼文觸及、攤位人次、logo 露出）並附照片【待補】，邀請下次合作",
}


def _flash(message: str) -> None:
    st.session_state.pr_flash = message
    st.rerun()


def pr_tabs(ctx: AppContext) -> list[tuple[str, Callable[[], None]]]:
    if message := st.session_state.pop("pr_flash", None):
        st.success(message)
    partners = list_partners(ctx.store, ctx.club_id)

    def summary() -> None:
        md = sponsorship_markdown(ctx.club.name, partners)
        st.markdown(md)
        download_buttons(md, "贊助與合作彙整", "sponsorship")

    return [
        ("找贊助對象", lambda: ideas_tab(ctx, partners)),
        (f"合作對象（{len(partners)}）", lambda: partners_tab(ctx, partners)),
        ("合作信件", lambda: letters_tab(ctx, partners)),
        ("贊助彙整", summary),
    ]


def _event_names(ctx: AppContext) -> list[str]:
    return [p.name for p in list_projects(ctx.store, ctx.club_id) if p.stage != "結案"]


def partner_fields(ctx: AppContext, prefix: str, p: Partner | None) -> dict:
    p = p or Partner(name="")
    c1, c2, c3 = st.columns([3, 2, 2])
    name = c1.text_input("單位／店家名稱＊", value=p.name, key=f"{prefix}_name")
    kind = c2.selectbox("類型", TYPES, index=TYPES.index(p.type) if p.type in TYPES else 0, key=f"{prefix}_type")
    stage = c3.selectbox("進度", STAGES, index=STAGES.index(p.stage) if p.stage in STAGES else 0, key=f"{prefix}_stage")
    c4, c5, c6 = st.columns(3)
    person = c4.text_input("聯絡人", value=p.contact_person, key=f"{prefix}_person")
    contact = c5.text_input("聯絡方式", value=p.contact, placeholder="Email、電話或 IG", key=f"{prefix}_contact")
    events = ["", *_event_names(ctx)]
    if p.event and p.event not in events:
        events.append(p.event)
    event = c6.selectbox("相關活動", events, index=events.index(p.event) if p.event in events else 0,
                         format_func=lambda e: e or "（未指定／長期合作）", key=f"{prefix}_event",
                         help="活動清單來自活動部門的活動專案")
    ask = st.text_input("我們請求", value=p.ask, placeholder="例：現金 3,000 元或 50 杯飲料", key=f"{prefix}_ask")
    offer = st.text_input("我們提供的回饋", value=p.offer, placeholder="例：IG 貼文 2 篇、活動背板 logo、攤位一個", key=f"{prefix}_offer")
    c7, c8, c9, c10 = st.columns(4)
    amount = c7.number_input("談成的現金（元）", min_value=0, step=500, value=p.amount, key=f"{prefix}_amount")
    in_kind = c8.text_input("談成的物資／折扣", value=p.in_kind, key=f"{prefix}_inkind")
    owner = c9.text_input("負責幹部", value=p.owner, key=f"{prefix}_owner")
    follow = c10.date_input("下次追蹤日", value=date.fromisoformat(p.follow_up) if p.follow_up else None, key=f"{prefix}_follow")
    notes = st.text_input("備註", value=p.notes, key=f"{prefix}_notes")
    return {
        "name": name.strip(), "type": kind, "stage": stage, "contact_person": person.strip(), "contact": contact.strip(),
        "event": event, "ask": ask.strip(), "offer": offer.strip(), "amount": int(amount), "in_kind": in_kind.strip(),
        "owner": owner.strip(), "follow_up": follow.isoformat() if follow else "", "notes": notes.strip(),
    }


def partners_tab(ctx: AppContext, partners: list[Partner]) -> None:
    today = date.today()
    for p in needs_follow_up(partners, today):
        st.warning(f"該追蹤了：{p.name}（{p.stage}，追蹤日 {p.follow_up}，負責 {p.owner or '未指定'}）")
    with st.expander("新增合作對象", expanded=not partners):
        with st.form("partner_new", clear_on_submit=True, border=False):
            data = partner_fields(ctx, "pn", None)
            if st.form_submit_button("加入名單", type="primary"):
                if not data["name"]:
                    st.warning("請填寫單位或店家名稱")
                else:
                    save_partner(ctx.store, ctx.club_id, Partner(**data))
                    _flash(f"已新增「{data['name']}」")
    if not partners:
        return
    counts = {s: sum(p.stage == s for p in partners) for s in STAGES}
    st.caption("　".join(f"{s} {n}" for s, n in counts.items() if n))
    c1, c2 = st.columns(2)
    type_filter = c1.multiselect("類型", TYPES, key="partner_types", placeholder="全部類型")
    show_closed = c2.toggle("顯示已結束與婉拒", key="partner_closed")
    for p in partners:
        if (type_filter and p.type not in type_filter) or (p.stage in ("已結束", "婉拒") and not show_closed):
            continue
        money = f"｜{p.amount:,} 元" if p.amount else ""
        with st.expander(f"{p.stage}｜{p.name}（{p.type}）{'｜' + p.event if p.event else ''}{money}"):
            with st.form(f"partner_edit_{p.id}", border=False):
                data = partner_fields(ctx, f"pe_{p.id}", p)
                if st.form_submit_button("儲存變更"):
                    if not data["name"]:
                        st.warning("名稱不能空白")
                    else:
                        save_partner(ctx.store, ctx.club_id, p.model_copy(update=data))
                        _flash("已儲存")
            if p.messages:
                st.markdown(f"**往來信件（{len(p.messages)}）**")
                for m in reversed(p.messages):
                    with st.popover(f"{m.created_at[:10]}｜{m.kind}｜{m.subject[:24]}"):
                        st.markdown(f"**{m.subject}**")
                        st.text(m.body)
            if st.button("刪除", key=f"partner_del_{p.id}", type="tertiary"):
                delete_partner(ctx.store, ctx.club_id, p.id)
                _flash(f"已刪除「{p.name}」")


def ideas_tab(ctx: AppContext, partners: list[Partner]) -> None:
    st.caption("AI 依社團與活動建議可以接洽的對象「類型」與搜尋關鍵字。為了避免過時或錯誤的資訊，不會直接給店名，"
               "請用關鍵字搜尋、確認後再加入名單。")
    c1, c2 = st.columns(2)
    events = ["", *_event_names(ctx)]
    event = c1.selectbox("為哪個活動找贊助", events, format_func=lambda e: e or "長期合作（不指定活動）", key="idea_event")
    area = c2.text_input("學校／地區", placeholder="例：台大公館、逢甲夜市周邊", key="idea_area")
    extra = st.text_input("補充（選填）", placeholder="例：想找飲料或餐點物資贊助；預算缺口約 5,000 元", key="idea_extra")
    if st.button("建議贊助對象", type="primary", key="idea_go"):
        project = next((p for p in list_projects(ctx.store, ctx.club_id) if p.name == event), None)
        event_text = project.facts() if project else (f"活動名稱：{event}" if event else "")
        existing = "\n".join(f"- {p.name}（{p.type}，{p.stage}）" for p in partners[:30])
        ideas = ctx.run_ai(
            "思考適合的贊助對象中…",
            lambda llm, _s: SponsorAdvisor(llm).run(ctx.club, event_text, area.strip(), existing, ctx.settings.details("pr"), extra),
        )
        if ideas:
            st.session_state.sponsor_ideas = (event, ideas)
    saved = st.session_state.get("sponsor_ideas")
    if not saved:
        return
    for_event, ideas = saved
    st.divider()
    for i, idea in enumerate(ideas.ideas):
        with st.container(border=True):
            st.markdown(f"**{i + 1}. {idea.target_type}**")
            st.markdown(f"- 為什麼適合：{idea.why}\n- 可以請求：{idea.ask}\n- 我們的回饋：{idea.offer}")
            cols = st.columns(len(idea.search_keywords) or 1)
            for col, kw in zip(cols, idea.search_keywords):
                col.link_button(f"搜尋：{kw}", f"https://www.google.com/maps/search/{quote_plus(kw)}", icon=":material/search:")
            with st.popover("找到對象了，加入名單"):
                with st.form(f"idea_add_{i}", border=False):
                    name = st.text_input("單位／店家名稱＊")
                    contact = st.text_input("聯絡方式")
                    if st.form_submit_button("加入", type="primary"):
                        if not name.strip():
                            st.warning("請填寫名稱")
                        else:
                            save_partner(ctx.store, ctx.club_id, Partner(
                                name=name.strip(), contact=contact.strip(), event=for_event, ask=idea.ask, offer=idea.offer,
                                notes=f"AI 建議類型：{idea.target_type}",
                            ))
                            _flash(f"已把「{name.strip()}」加入合作對象")
    if ideas.tips:
        st.markdown("**接洽注意事項**\n" + "\n".join(f"- {t}" for t in ideas.tips))


def letters_tab(ctx: AppContext, partners: list[Partner]) -> None:
    active = [p for p in partners if p.stage != "婉拒"]
    if not active:
        st.info("先在「合作對象」新增對象，才能產生信件。")
        return
    st.caption("AI 依合作對象的資料撰寫信件；資料不足的地方會標示【待補】，寄出前請檢查並修改。")
    by_id = {p.id: p for p in active}
    pid = st.selectbox("對象", list(by_id), format_func=lambda i: f"{by_id[i].name}（{by_id[i].stage}）", key="pr_letter_partner")
    partner = by_id[pid]

    def on_save(kind: str, message: SavedMessage) -> None:
        updated = partner.model_copy(update={"messages": [*partner.messages, message]})
        if kind in ("贊助邀請信", "合作提案信") and partner.stage == "待聯絡":
            updated = updated.model_copy(update={"stage": "已聯絡"})
        save_partner(ctx.store, ctx.club_id, updated)
        _flash(f"已存到「{partner.name}」的往來紀錄" + ("，進度改為已聯絡" if updated.stage != partner.stage else ""))

    facts = partner.facts()
    project = next((p for p in list_projects(ctx.store, ctx.club_id) if partner.event and p.name == partner.event), None)
    if project:
        facts += "\n\n活動資訊：\n" + project.facts()
    letter_workbench(ctx, f"partner_{partner.id}", PR_LETTERS, facts, partner.contact, ctx.settings.name("pr"), on_save,
                     download_name=partner.name)

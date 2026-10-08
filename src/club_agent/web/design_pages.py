"""美宣（併入行銷）：側邊欄「設計需求」（各部門提出），行銷的「設計需求」與「視覺規範」分頁。"""

from __future__ import annotations

import html
import re
from datetime import date
from typing import Callable

import pandas as pd
import streamlit as st

from ..agents import DesignAssistant
from ..design import (
    OPEN_STATUSES,
    SIZE_PRESETS,
    STATUSES,
    BrandColor,
    BrandGuide,
    DesignRequest,
    brief_markdown,
    delete_request,
    get_guide,
    guide_markdown,
    list_requests,
    save_guide,
    save_request,
)
from ..projects import list_projects
from .context import AppContext, download_buttons

HEX = re.compile(r"^#[0-9A-Fa-f]{6}$")


def _flash(message: str) -> None:
    st.session_state.design_flash = message
    st.rerun()


def _show_flash() -> None:
    if message := st.session_state.pop("design_flash", None):
        st.success(message)


def _events(ctx: AppContext) -> list[str]:
    return [p.name for p in list_projects(ctx.store, ctx.club_id) if p.stage != "結案"]


# ---------------------------------------------------------------------------
# 側邊欄：各部門提出設計需求
# ---------------------------------------------------------------------------


def design_request_page(ctx: AppContext) -> None:
    _show_flash()
    st.caption("需要海報、貼文圖、限動或簡報時在這裡提出，行銷（美宣）會依截止日排程處理。截止日會出現在行事曆。")
    with st.form("design_new", clear_on_submit=True):
        c1, c2, c3 = st.columns([3, 2, 2])
        title = c1.text_input("需求名稱＊", placeholder="例：成果展主視覺海報")
        kind = c2.selectbox("類型", list(SIZE_PRESETS))
        due = c3.date_input("需要完成的日期", value=None)
        c4, c5, c6 = st.columns(3)
        requester = c4.text_input("聯絡人", placeholder="有問題時找誰")
        size = c5.text_input("尺寸（空白則依類型）", placeholder="例：A3、1080 × 1350 px")
        events = ["", *_events(ctx)]
        event = c6.selectbox("相關活動", events, format_func=lambda e: e or "（無）")
        purpose = st.text_area("用途與想傳達的重點", height=80, placeholder="例：吸引非社員來看展，強調免費入場與底片體驗")
        copy_text = st.text_area("一定要放的文字", height=80, placeholder="例：活動名稱、日期時間、地點、報名 QR code")
        references = st.text_input("參考圖或連結（選填）")
        if st.form_submit_button("送出需求", type="primary"):
            if not title.strip():
                st.warning("請填寫需求名稱")
            else:
                save_request(ctx.store, ctx.club_id, DesignRequest(
                    title=title.strip(), department=ctx.dept_key, requester=requester.strip(), kind=kind,
                    size=size.strip() or SIZE_PRESETS[kind], purpose=purpose.strip(), copy_text=copy_text.strip(),
                    references=references.strip(), event=event, due=due.isoformat() if due else "",
                ))
                _flash(f"已送出「{title.strip()}」，行銷會在「設計需求」看到")

    mine = [r for r in list_requests(ctx.store, ctx.club_id) if r.department == ctx.dept_key]
    st.markdown(f"**{ctx.dept_name}提出的需求（{len(mine)}）**")
    if not mine:
        st.caption("還沒有提出過需求。")
    for r in mine:
        due = f"｜截止 {r.due}" if r.due else ""
        designer = f"｜{r.designer}" if r.designer else ""
        st.markdown(f"- **{r.status}**　{r.title}（{r.kind}）{due}{designer}")


# ---------------------------------------------------------------------------
# 行銷：設計需求、視覺規範
# ---------------------------------------------------------------------------


def design_tabs(ctx: AppContext) -> list[tuple[str, Callable[[], None]]]:
    _show_flash()
    requests = list_requests(ctx.store, ctx.club_id)
    open_count = sum(r.status in OPEN_STATUSES for r in requests)
    return [(f"設計需求（{open_count}）", lambda: queue_tab(ctx, requests)), ("視覺規範", lambda: guide_tab(ctx))]


def queue_tab(ctx: AppContext, requests: list[DesignRequest]) -> None:
    today = date.today()
    st.caption("各部門在左側「設計需求」提出的需求，依截止日排序。也可以請 AI 依視覺規範寫出設計說明與文案。")
    overdue = [r for r in requests if r.is_overdue(today)]
    for r in overdue:
        st.warning(f"已超過截止日：{r.title}（{ctx.settings.name(r.department)}，截止 {r.due}）")
    if not requests:
        st.info("目前沒有設計需求。")
        return
    show_done = st.toggle("顯示已完成與取消", key="design_show_done")
    for r in requests:
        if r.status not in OPEN_STATUSES and not show_done:
            continue
        due = f"｜截止 {r.due}" if r.due else ""
        with st.expander(f"{r.status}｜{r.title}（{r.kind}）｜{ctx.settings.name(r.department)}{due}"):
            st.markdown(r.facts(ctx.settings.name).replace("\n", "  \n"))
            if r.requester:
                st.caption(f"聯絡人：{r.requester}")
            with st.form(f"design_edit_{r.id}", border=False):
                c1, c2, c3 = st.columns(3)
                status = c1.selectbox("狀態", STATUSES, index=STATUSES.index(r.status) if r.status in STATUSES else 0)
                designer = c2.text_input("負責美宣", value=r.designer)
                due_new = c3.date_input("截止日", value=r.due_date())
                note = st.text_input("備註", value=r.note)
                if st.form_submit_button("儲存"):
                    save_request(ctx.store, ctx.club_id, r.model_copy(update={
                        "status": status, "designer": designer.strip(), "due": due_new.isoformat() if due_new else "", "note": note.strip(),
                    }))
                    _flash(f"已更新「{r.title}」")
            extra = st.text_input("給 AI 的補充（選填）", key=f"design_extra_{r.id}", placeholder="例：想要復古底片感；不要用太多字")
            if st.button("AI 產生設計說明與文案" if not r.brief else "重新產生設計說明", key=f"design_brief_{r.id}"):
                project = next((p for p in list_projects(ctx.store, ctx.club_id) if r.event and p.name == r.event), None)
                brief = ctx.run_ai(
                    "撰寫設計說明中…",
                    lambda llm, _s: DesignAssistant(llm).brief(ctx.club, get_guide(ctx.store, ctx.club_id).to_text(),
                                                               r.facts(ctx.settings.name), project.facts() if project else "", extra),
                )
                if brief:
                    save_request(ctx.store, ctx.club_id, r.model_copy(update={"brief": brief}))
                    _flash(f"「{r.title}」的設計說明完成")
            if r.brief:
                md = brief_markdown(r, ctx.settings.name)
                st.markdown(md)
                download_buttons(md, f"設計說明_{r.title}", f"brief_{r.id}")
            if st.button("刪除這個需求", key=f"design_del_{r.id}", type="tertiary"):
                delete_request(ctx.store, ctx.club_id, r.id)
                _flash(f"已刪除「{r.title}」")


def _swatches(guide: BrandGuide) -> None:
    chips = "".join(
        f'<span style="display:inline-flex;align-items:center;gap:6px;margin:0 14px 6px 0;font-size:0.85rem">'
        f'<span style="width:22px;height:22px;border-radius:4px;border:1px solid #D6D2C8;background:{c.hex}"></span>'
        f'{html.escape(c.name)} {c.hex}</span>'
        for c in guide.colors if HEX.match(c.hex)
    )
    if chips:
        st.markdown(f"<div>{chips}</div>", unsafe_allow_html=True)


def guide_tab(ctx: AppContext) -> None:
    guide = get_guide(ctx.store, ctx.club_id)
    st.caption("社團的品牌色、字體、Logo 與文案語氣。AI 寫設計說明時會依這份規範；也可以下載分享給美宣與各部門。")
    _swatches(guide)
    with st.expander("請 AI 建議視覺規範（會保留已經填好的內容再補充）", expanded=guide.is_empty()):
        extra = st.text_input("想要的感覺（選填）", placeholder="例：溫暖、復古底片感；主色想保留深藍", key="guide_extra")
        if st.button("產生建議", key="guide_go"):
            draft = ctx.run_ai(
                "建議視覺規範中…",
                lambda llm, _s: DesignAssistant(llm).guide(ctx.club, guide.to_text(), ctx.settings.details("marketing"), extra),
            )
            if draft:
                save_guide(ctx.store, ctx.club_id, BrandGuide(
                    colors=[BrandColor(**c.model_dump()) for c in draft.colors], heading_font=draft.heading_font,
                    body_font=draft.body_font, logo_rules=draft.logo_rules, tone=draft.tone, dos=draft.dos, donts=draft.donts,
                ))
                st.session_state.pop("guide_colors", None)
                _flash("已套用 AI 建議，可以在下方修改")

    st.markdown("**品牌色**（色碼格式 #RRGGBB）")
    colors = st.data_editor(
        pd.DataFrame({
            "名稱": pd.Series([c.name for c in guide.colors], dtype="object"),
            "色碼": pd.Series([c.hex for c in guide.colors], dtype="object"),
            "用途": pd.Series([c.usage for c in guide.colors], dtype="object"),
        }),
        num_rows="dynamic", hide_index=True, width="stretch", key=f"guide_colors_{guide.updated_at}",
    )
    with st.form("guide_form", border=False):
        c1, c2 = st.columns(2)
        heading = c1.text_input("標題字體", value=guide.heading_font, placeholder="例：思源黑體 Bold")
        body = c2.text_input("內文字體", value=guide.body_font, placeholder="例：思源黑體 Regular")
        logo = st.text_area("Logo 使用規則", value=guide.logo_rules, height=70, placeholder="例：放在左上或右下，周圍留白至少 Logo 高度的一半")
        tone = st.text_area("文案語氣", value=guide.tone, height=70, placeholder="例：親切、帶點幽默，避免太多驚嘆號")
        c3, c4 = st.columns(2)
        dos = c3.text_area("建議做法（一行一項）", value="\n".join(guide.dos), height=100)
        donts = c4.text_area("避免的做法（一行一項）", value="\n".join(guide.donts), height=100)
        if st.form_submit_button("儲存視覺規範", type="primary"):
            rows = [r for r in colors.to_dict("records") if str(r.get("名稱") or "").strip() and str(r.get("名稱")) != "nan"]
            bad = [str(r.get("色碼")) for r in rows if not HEX.match(str(r.get("色碼") or "").strip())]
            if bad:
                st.error(f"色碼格式不正確：{'、'.join(bad)}（請用 #RRGGBB，例如 #2D4A6B）")
            else:
                save_guide(ctx.store, ctx.club_id, BrandGuide(
                    colors=[BrandColor(name=str(r["名稱"]).strip(), hex=str(r["色碼"]).strip().upper(),
                                       usage=str(r.get("用途") or "").strip() if str(r.get("用途")) != "nan" else "") for r in rows],
                    heading_font=heading.strip(), body_font=body.strip(), logo_rules=logo.strip(), tone=tone.strip(),
                    dos=[x.strip() for x in dos.splitlines() if x.strip()], donts=[x.strip() for x in donts.splitlines() if x.strip()],
                ))
                _flash("已儲存視覺規範")
    if not guide.is_empty():
        md = guide_markdown(ctx.club.name, guide)
        download_buttons(md, "視覺規範", "brand_guide")

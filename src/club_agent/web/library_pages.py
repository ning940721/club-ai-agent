"""文件庫（側邊欄「幹部共用」）：上傳與下載各部門的檔案，依部門、類別篩選，搜尋檔名與內文。"""

from __future__ import annotations

import streamlit as st

from ..library import CATEGORIES, LibraryFile, add_file, delete_file, file_bytes, list_files, update_file
from ..store import StoreError
from .context import AppContext

ALL = "__all__"


def _flash(message: str) -> None:
    st.session_state.library_flash = message
    st.rerun()


def library_page(ctx: AppContext) -> None:
    if message := st.session_state.pop("library_flash", None):
        st.success(message)
    st.caption("各部門的檔案集中在這裡：企劃書、報告、簡報、表單、規章、照片…，依部門與類別整理。"
               "Word、PDF、Excel、簡報的內容可以搜尋，AI Agent 問答也會參考。所有幹部都看得到，請不要上傳財務單據與個資。")
    upload_form(ctx)
    files = list_files(ctx.store, ctx.club_id)
    if not files:
        st.info("文件庫還是空的。上傳第一個檔案吧！會議記錄上傳的原始檔也會自動放進來。")
        return

    c1, c2, c3 = st.columns([2, 2, 3], vertical_alignment="bottom")
    departments = [ALL, *ctx.settings.enabled_keys(), *sorted({f.department for f in files} - set(ctx.settings.enabled_keys()))]
    dept = c1.selectbox("部門", departments, index=departments.index(ctx.dept_key) if ctx.dept_key in departments else 0,
                        format_func=lambda k: "全部部門" if k == ALL else ctx.settings.name(k), key=f"lib_dept_{ctx.dept_key}")
    category = c2.selectbox("類別", [ALL, *CATEGORIES], format_func=lambda k: "全部類別" if k == ALL else k, key="lib_category")
    query = c3.text_input("搜尋檔名或內容", placeholder="例：場地申請、贊助", key="lib_query")
    shown = [f for f in files if (dept == ALL or f.department == dept) and (category == ALL or f.category == category) and f.matches(query)]
    counts = {}
    for f in files:
        counts[f.department] = counts.get(f.department, 0) + 1
    st.caption("　".join(f"{ctx.settings.name(k)} {n}" for k, n in counts.items()) + f"　｜　共 {len(files)} 個檔案")
    if not shown:
        st.caption("沒有符合的檔案。")
        return

    groups: dict[str, list[LibraryFile]] = {}
    for f in shown:
        groups.setdefault(f.department, []).append(f)
    for key, items in groups.items():
        st.markdown(f"**{ctx.settings.name(key)}**（{len(items)}）")
        for f in items:
            file_row(ctx, f, query)


def upload_form(ctx: AppContext) -> None:
    with st.expander("上傳檔案", expanded=False, icon=":material/upload_file:"):
        with st.form("library_upload", clear_on_submit=True, border=False):
            uploads = st.file_uploader("選擇檔案（可以一次選多個，每個最多 20 MB）", accept_multiple_files=True)
            c1, c2, c3 = st.columns(3)
            departments = ctx.settings.enabled_keys()
            dept = c1.selectbox("部門", departments, index=departments.index(ctx.dept_key), format_func=ctx.settings.name)
            category = c2.selectbox("類別", CATEGORIES)
            uploader = c3.text_input("上傳者（選填）")
            note = st.text_input("說明（選填）", placeholder="例：113 學年度成果展企劃，已通過幹部會")
            if st.form_submit_button("上傳", type="primary"):
                if not uploads:
                    st.warning("請先選擇檔案")
                    return
                done, errors = [], []
                for up in uploads:
                    try:
                        add_file(ctx.store, ctx.club_id, up.name, up.getvalue(), dept, category=category, note=note, uploader=uploader)
                        done.append(up.name)
                    except StoreError as e:
                        errors.append(str(e))
                for e in errors:
                    st.error(e)
                if done:
                    _flash(f"已上傳 {len(done)} 個檔案到「{ctx.settings.name(dept)}」：{'、'.join(done)}")


def _snippet(text: str, query: str, width: int = 60) -> str:
    i = text.lower().find(query.strip().lower())
    if not query.strip() or i < 0:
        return ""
    start = max(0, i - width)
    return ("…" if start else "") + text[start:i + len(query) + width].replace("\n", " ") + "…"


PREVIEW_TEXT = (".docx", ".pptx", ".txt", ".md")
PREVIEW_TABLE = (".xlsx", ".csv")
PREVIEW_IMAGE = (".png", ".jpg", ".jpeg", ".gif", ".webp")


def can_preview(f: LibraryFile) -> bool:
    return f.name.lower().endswith((".pdf", *PREVIEW_TEXT, *PREVIEW_TABLE, *PREVIEW_IMAGE))


def preview(ctx: AppContext, f: LibraryFile) -> None:
    """在頁面上直接看檔案：PDF 用檢視器、圖片直接顯示、Excel 顯示表格、Word／簡報顯示文字內容。"""
    name = f.name.lower()
    with st.container(border=True):
        c1, c2 = st.columns([5, 1], vertical_alignment="center")
        c1.markdown(f"**預覽：{f.display}**")
        if c2.button("關閉預覽", key=f"lib_close_{f.id}", type="tertiary"):
            st.session_state.pop("lib_preview", None)
            st.rerun()
        data = file_bytes(ctx.store, ctx.club_id, f)
        if not data:
            st.warning("找不到檔案內容")
            return
        if name.endswith(".pdf"):
            try:
                st.pdf(data, height=640)
            except Exception:  # 沒有安裝 PDF 檢視器時，改顯示文字
                st.caption("無法顯示 PDF 檢視器，以下是 PDF 的文字內容：")
                st.text(f.text or "（讀不到文字）")
        elif name.endswith(PREVIEW_IMAGE):
            st.image(data)
        elif name.endswith(PREVIEW_TABLE):
            import io

            import pandas as pd

            try:
                if name.endswith(".csv"):
                    from ..metrics import decode_csv_bytes

                    sheets = {"": pd.read_csv(io.StringIO(decode_csv_bytes(data)), dtype=str)}
                else:
                    sheets = pd.read_excel(io.BytesIO(data), sheet_name=None, dtype=str, nrows=500)
            except Exception:
                st.caption("無法讀取表格，請下載後開啟")
                return
            tabs = st.tabs([s or "表格" for s in sheets]) if len(sheets) > 1 else [st.container()]
            for tab, df in zip(tabs, sheets.values()):
                with tab:
                    st.dataframe(df.fillna(""), hide_index=True, width="stretch", height=360)
            st.caption("最多顯示前 500 列；格式與公式請下載後查看。")
        else:
            st.caption("以下是檔案的文字內容（排版、圖片請下載後查看）")
            with st.container(height=420):
                if name.endswith(".md"):
                    st.markdown(f.text)
                else:
                    st.text(f.text or "（這個檔案沒有文字內容）")


def file_row(ctx: AppContext, f: LibraryFile, query: str) -> None:
    c1, c0, c2, c3 = st.columns([6, 1, 1, 1], vertical_alignment="center")
    if can_preview(f) and c0.button("預覽", key=f"lib_pv_{f.id}", icon=":material/visibility:"):
        st.session_state.lib_preview = None if st.session_state.get("lib_preview") == f.id else f.id
    meta = "｜".join(x for x in (f.category, f.size_label(), f.uploaded_at[:10], f.uploader, f.source if f.source != "上傳" else "") if x)
    c1.markdown(f"**{f.display}**　:gray[{meta}]" + (f"  \n{f.note}" if f.note else "")
                + (f"  \n:gray[{_snippet(f.text, query)}]" if _snippet(f.text, query) else ""))
    c2.download_button("下載", lambda: file_bytes(ctx.store, ctx.club_id, f), file_name=f.name, mime=f.content_type,
                       key=f"lib_dl_{f.id}", on_click="ignore", icon=":material/download:")
    with c3.popover("更多", icon=":material/more_horiz:"):
        with st.form(f"lib_edit_{f.id}", border=False):
            title = st.text_input("顯示名稱", value=f.title, placeholder=f.name)
            departments = ctx.settings.enabled_keys()
            dept = st.selectbox("部門", departments, index=departments.index(f.department) if f.department in departments else 0,
                                format_func=ctx.settings.name)
            category = st.selectbox("類別", CATEGORIES, index=CATEGORIES.index(f.category) if f.category in CATEGORIES else 0)
            note = st.text_input("說明", value=f.note)
            if st.form_submit_button("儲存"):
                update_file(ctx.store, ctx.club_id, f.model_copy(update={
                    "title": title.strip(), "department": dept, "category": category, "note": note.strip()}))
                _flash(f"已更新「{title.strip() or f.name}」")
        if st.button("刪除這個檔案", key=f"lib_del_{f.id}", type="tertiary"):
            delete_file(ctx.store, ctx.club_id, f)
            _flash(f"已刪除「{f.display}」")
    if st.session_state.get("lib_preview") == f.id:
        preview(ctx, f)

"""交接資料包：把全社團各部門的資料整理成一個 ZIP（Word／Excel／.ics），方便交接與備份。

- 依部門與主題分資料夾，文件用一般人能開的格式（Markdown 報告轉成 Word）。
- 敏感資料預設不包含：財務資料需要 include_finance（網頁上要先輸入財務密碼），社員聯絡方式需要 include_contacts。
- manuals：已經由 AI 產生的各部門交接手冊（部門代號 → Markdown），會放進各部門資料夾。
"""

from __future__ import annotations

import io
import re
import zipfile
from datetime import date, datetime

import pandas as pd

from .courses import get_course_settings, list_sessions, schedule_markdown
from .departments import ClubSettings
from .design import brief_markdown, get_guide, guide_markdown
from .design import list_requests as list_design_requests
from .events import club_events, to_ics
from .export import to_docx
from .finance import budget_rows, list_entries, policy_markdown, summarize_period, to_excel, transactions
from .finance import get_settings as finance_settings
from .finance import list_requests as list_reimbursements
from .meetings import list_meetings
from .members import list_applicants, list_members
from .partners import list_partners, sponsorship_markdown
from .post_history import list_history
from .projects import actual_spending, feedback_markdown, list_projects, proposal_markdown, report_markdown, rundown_markdown
from .report import meeting_summary_markdown
from .schemas import ClubProfile
from .speakers import list_talks, talks_markdown
from .tasks import list_tasks
from .venue import bookings_markdown, list_bookings, list_equipment, list_loans, on_loan


def safe_name(name: str, limit: int = 50) -> str:
    cleaned = re.sub(r'[\\/:*?"<>|\r\n\t]+', "_", name).strip(" ._")
    return cleaned[:limit] or "未命名"


def _xlsx(sheets: dict[str, pd.DataFrame]) -> bytes:
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        for name, df in sheets.items():
            df.to_excel(writer, sheet_name=name[:31], index=False)
    return buffer.getvalue()


class _Pack:
    def __init__(self, root: str):
        self.root = root
        self.files: dict[str, bytes] = {}

    def add(self, path: str, data: bytes | str) -> None:
        parts = [safe_name(p) for p in path.split("/")]
        full = "/".join([self.root, *parts])
        stem, dot, ext = full.rpartition(".")
        n = 2
        while full in self.files:  # 同名檔案加上編號
            full = f"{stem}_{n}.{ext}" if dot else f"{full}_{n}"
            n += 1
        self.files[full] = data.encode("utf-8") if isinstance(data, str) else data

    def doc(self, path: str, markdown: str) -> None:
        self.add(path + ".docx", to_docx(markdown))

    def zip(self) -> bytes:
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as z:
            for path, data in self.files.items():
                z.writestr(path, data)
        return buffer.getvalue()


def build_handover_zip(
    store,
    club_id: str,
    club: ClubProfile,
    settings: ClubSettings,
    *,
    include_finance: bool = False,
    include_contacts: bool = False,
    manuals: dict[str, str] | None = None,
    today: date | None = None,
) -> tuple[bytes, list[str]]:
    """回傳 (ZIP 內容, 檔案清單)。"""
    today = today or date.today()
    pack = _Pack(f"{safe_name(club.name)}_交接資料_{today:%Y%m%d}")
    name = settings.name
    counts: list[str] = []

    # 全社團：待辦、行事曆、會議記錄
    tasks = list_tasks(store, club_id)
    if tasks:
        pack.add("01_全社團/待辦與進度.xlsx", _xlsx({"待辦": pd.DataFrame({
            "部門": [name(t.department) for t in tasks], "事項": [t.title for t in tasks], "負責人": [t.owner for t in tasks],
            "期限": [t.due for t in tasks], "狀態": [t.status for t in tasks], "來源": [t.source for t in tasks]})}))
        counts.append(f"待辦 {len(tasks)} 項")
    events = club_events(store, club_id, settings)
    if events:
        pack.add("01_全社團/行事曆.ics", to_ics(events, f"{club.name} 行事曆", settings))
        pack.add("01_全社團/行事曆.xlsx", _xlsx({"行事曆": pd.DataFrame({
            "日期": [e.date for e in events], "時間": [e.when() for e in events], "類型": [e.kind for e in events],
            "部門": [name(e.department) if e.department else "全社團" for e in events], "行程": [e.title for e in events],
            "地點": [e.location for e in events], "來源": [e.source for e in events]})}))
        counts.append(f"行程 {len(events)} 筆")
    meetings = list_meetings(store, club_id)
    for doc in meetings:
        label = f"{doc.date}_{doc.title}"
        if doc.summary:
            pack.doc(f"02_會議記錄/{label}_重點", meeting_summary_markdown(doc.title, doc.date, doc.summary, name))
        pack.add(f"02_會議記錄/原文/{label}.txt", doc.text)
    if meetings:
        counts.append(f"會議記錄 {len(meetings)} 份")

    # 各部門分享的成果與交接手冊
    records = store.list_records(club_id)
    for r in records:
        pack.doc(f"03_各部門/{name(r.department)}/分享的成果/{r.created_at[:10]}_{r.title}", r.markdown)
    if records:
        counts.append(f"各部門分享的成果 {len(records)} 份")
    for key, md in (manuals or {}).items():
        pack.doc(f"03_各部門/{name(key)}/交接手冊", md)
    if manuals:
        counts.append(f"AI 交接手冊 {len(manuals)} 份")

    # 活動專案
    projects = list_projects(store, club_id)
    requests = list_reimbursements(store, club_id) if include_finance else []
    for p in projects:
        folder = f"04_活動專案/{p.date or '日期未定'}_{p.name}"
        if p.proposal:
            pack.doc(f"{folder}/企劃書", proposal_markdown(club.name, p, name))
        if p.rundown or p.staff:
            pack.doc(f"{folder}/細流與工作人員", rundown_markdown(club.name, p))
        if p.feedback:
            pack.doc(f"{folder}/回饋表單", feedback_markdown(p.feedback))
        if p.report:
            spent, by_category = actual_spending(p, requests) if include_finance else (None, {})
            pack.doc(f"{folder}/成果報告", report_markdown(club.name, p, spent, by_category))
    if projects:
        counts.append(f"活動專案 {len(projects)} 個")

    # 講座、合作與贊助
    talks = list_talks(store, club_id)
    if talks:
        pack.doc("05_講座/講座彙整", talks_markdown(club.name, talks))
        counts.append(f"講座 {len(talks)} 場")
    partners = list_partners(store, club_id)
    if partners:
        pack.doc("06_合作與贊助/贊助與合作彙整", sponsorship_markdown(club.name, partners))
        pack.add("06_合作與贊助/合作對象.xlsx", _xlsx({"合作對象": pd.DataFrame({
            "名稱": [p.name for p in partners], "類型": [p.type for p in partners], "聯絡人": [p.contact_person for p in partners],
            "聯絡方式": [p.contact for p in partners], "進度": [p.stage for p in partners], "相關活動": [p.event for p in partners],
            "請求": [p.ask for p in partners], "回饋": [p.offer for p in partners], "現金": [p.amount for p in partners],
            "物資／折扣": [p.in_kind for p in partners], "負責": [p.owner for p in partners], "備註": [p.notes for p in partners]})}))
        counts.append(f"合作對象 {len(partners)} 個")

    # 行銷：貼文歷史、視覺規範、設計需求
    posts = list_history(store, club_id)
    if posts:
        pack.add("07_行銷/貼文數據歷史.xlsx", _xlsx({"貼文": pd.DataFrame([p.model_dump() for p in posts])}))
        counts.append(f"貼文數據 {len(posts)} 篇")
    guide = get_guide(store, club_id)
    if not guide.is_empty():
        pack.doc("07_行銷/視覺規範", guide_markdown(club.name, guide))
    design = list_design_requests(store, club_id)
    if design:
        pack.add("07_行銷/設計需求.xlsx", _xlsx({"設計需求": pd.DataFrame({
            "需求": [r.title for r in design], "類型": [r.kind for r in design], "提出部門": [name(r.department) for r in design],
            "截止": [r.due for r in design], "狀態": [r.status for r in design], "負責美宣": [r.designer for r in design]})}))
        for r in design:
            if r.brief:
                pack.doc(f"07_行銷/設計說明/{r.title}", brief_markdown(r, name))

    # 課程、總務
    sessions = list_sessions(store, club_id)
    if sessions:
        pack.doc("08_課程/社課課表與出席", schedule_markdown(club.name, sessions, get_course_settings(store, club_id).member_count))
        counts.append(f"社課 {len(sessions)} 堂")
    bookings = list_bookings(store, club_id)
    if bookings:
        pack.doc("09_總務/場地申請一覽", bookings_markdown(club.name, bookings))
    equipment = list_equipment(store, club_id)
    loans = list_loans(store, club_id)
    if equipment or loans:
        pack.add("09_總務/器材.xlsx", _xlsx({
            "器材清單": pd.DataFrame({"名稱": [e.name for e in equipment], "數量": [e.quantity for e in equipment],
                                    "借出中": [on_loan(e.id, loans) for e in equipment], "存放位置": [e.location for e in equipment],
                                    "狀況": [e.condition for e in equipment], "備註": [e.note for e in equipment]}),
            "借還紀錄": pd.DataFrame({"器材": [x.equipment_name for x in loans], "數量": [x.quantity for x in loans],
                                    "借用人": [x.borrower for x in loans], "借出": [x.borrowed for x in loans],
                                    "應還": [x.due for x in loans], "歸還": [x.returned for x in loans]}),
        }))
        counts.append(f"器材 {len(equipment)} 項")

    # 人資：社員名單（聯絡方式需另外勾選）
    members = list_members(store, club_id)
    if members:
        data = {"姓名": [m.name for m in members], "系級": [m.major for m in members], "入社學期": [m.joined for m in members],
                "身分": [m.role for m in members], "部門": [name(m.department) if m.department else "" for m in members],
                "狀態": [m.status for m in members], "備註": [m.note for m in members]}
        if include_contacts:
            data["聯絡方式"] = [m.contact for m in members]
        applicants = list_applicants(store, club_id)
        sheets = {"社員名單": pd.DataFrame(data)}
        if applicants:
            sheets["招生紀錄"] = pd.DataFrame({"姓名": [a.name for a in applicants], "應徵": [a.role for a in applicants],
                                           "管道": [a.source for a in applicants], "結果": [a.result for a in applicants]})
        pack.add("10_人資/社員名單.xlsx", _xlsx(sheets))
        counts.append(f"社員 {len(members)} 人")

    # 財務（需要財務密碼）
    if include_finance:
        fs = finance_settings(store, club_id)
        start, end = fs.term(today)
        reimbursements = list_reimbursements(store, club_id)
        entries = list_entries(store, club_id)
        summary = summarize_period(transactions(reimbursements, entries), start, end, fs.opening_balance)
        budgets = budget_rows(fs, reimbursements, entries, start, end)
        title = f"學期財務報表（{start} ~ {end}）"
        pack.add(f"11_財務/{title}.xlsx", to_excel(club.name, title, summary, budgets, reimbursements))
        pack.doc("11_財務/報帳與財務規範", policy_markdown(club.name, fs))
        counts.append("財務報表與規範")

    # 說明文件
    enabled = "、".join(name(k) for k in settings.enabled_keys())
    index = [
        f"# {club.name} 交接資料包", "",
        f"**產生時間：** {datetime.now():%Y-%m-%d %H:%M}", "", f"**部門：** {enabled}", "",
        "## 內容", *[f"- {c}" for c in counts or ["（目前沒有資料）"]], "",
        "## 資料夾說明",
        "- 01_全社團：待辦與進度、行事曆（.ics 可匯入 Google 日曆）",
        "- 02_會議記錄：每次會議的重點整理與原文",
        "- 03_各部門：各部門分享過的成果" + ("與 AI 交接手冊" if manuals else ""),
        "- 04–10：活動專案、講座、合作與贊助、行銷、課程、總務、人資",
        "- 11_財務：" + ("學期財務報表與報帳規範" if include_finance else "未包含（需要財務密碼）"), "",
        "## 注意事項",
        "- 這份資料包含社團內部資訊，請存放在幹部共用的雲端資料夾，不要公開分享。",
        "- 帳號密碼請私下移交，不要放進這份資料。",
        "- 社員名單" + ("包含聯絡方式，屬於個資，請小心保管。" if include_contacts else "未包含聯絡方式。"),
    ]
    pack.doc("00_資料包說明", "\n".join(index) + "\n")
    return pack.zip(), sorted(pack.files)

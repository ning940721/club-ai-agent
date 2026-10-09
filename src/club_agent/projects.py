"""活動專案：每個活動一個專案，從構思、企劃書、籌備清單、細流與工作人員、回饋表單到成果報告。

- 專案存在 projects 集合。
- 籌備清單直接使用全社團的待辦（Task.project 指向專案），所以會出現在社長總覽、各部門待辦與行事曆。
- 實際支出取自財務的報帳：報帳的「所屬活動」填活動名稱，已核准或已撥款的就會算進來。
"""

from __future__ import annotations

import logging
import uuid
from datetime import date, datetime, timedelta

from pydantic import BaseModel, Field

from .schemas import BudgetLine, EventProposal, EventReport, FeedbackForm, RundownItem
from .tasks import Task

COLLECTION = "projects"
STAGES = ("構思", "企劃", "籌備", "執行", "結案")
WEEKDAYS = "一二三四五六日"


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


class StaffMember(BaseModel):
    name: str
    role: str = Field(default="", description="組別或職務")
    shift: str = Field(default="", description="值班時段")
    note: str = ""


class EventProject(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    created_at: str = Field(default_factory=_now)
    updated_at: str = Field(default_factory=_now)
    name: str
    date: str = Field(default="", description="活動日期 YYYY-MM-DD")
    start_time: str = ""
    end_time: str = ""
    location: str = ""
    expected_people: int = 0
    budget: int = Field(default=0, description="總預算（元）")
    goal: str = Field(default="", description="想達成的目的")
    description: str = Field(default="", description="活動構想")
    owner: str = ""
    stage: str = "構思"
    proposal: EventProposal | None = None
    rundown: list[RundownItem] = Field(default_factory=list)
    budget_lines: list[BudgetLine] = Field(default_factory=list)
    staff: list[StaffMember] = Field(default_factory=list)
    feedback: FeedbackForm | None = None
    attendance: int = Field(default=0, description="實際參加人數")
    feedback_notes: str = Field(default="", description="回饋表單結果重點（貼上）")
    review_notes: str = Field(default="", description="幹部檢討重點")
    report: EventReport | None = None

    def event_date(self) -> date | None:
        try:
            return date.fromisoformat(self.date)
        except ValueError:
            return None

    def when(self) -> str:
        d = self.event_date()
        if not d:
            return "日期未定"
        times = f" {self.start_time}–{self.end_time}" if self.start_time and self.end_time else (f" {self.start_time}" if self.start_time else "")
        return f"{d.isoformat()}（{WEEKDAYS[d.weekday()]}）{times}"

    def facts(self) -> str:
        """給 AI 的活動資訊；未知的寫未定。"""
        return "\n".join([
            f"活動名稱：{self.name}",
            f"時間：{self.when()}",
            f"地點：{self.location or '未定'}",
            f"預計人數：{self.expected_people or '未定'}",
            f"總預算：{f'{self.budget:,} 元' if self.budget else '未定'}",
            f"目的：{self.goal or '未填'}",
            f"構想：{self.description or '未填'}",
            f"負責人：{self.owner or '未定'}",
        ])


def save_project(store, club_id: str, p: EventProject) -> None:
    store.put_doc(club_id, COLLECTION, p.id, p.model_copy(update={"updated_at": _now()}).model_dump())


def get_project(store, club_id: str, project_id: str) -> EventProject | None:
    data = store.get_doc(club_id, COLLECTION, project_id)
    return EventProject(**data) if data else None


def delete_project(store, club_id: str, project_id: str) -> None:
    store.delete_doc(club_id, COLLECTION, project_id)


def list_projects(store, club_id: str) -> list[EventProject]:
    """未結案在前，依活動日期排序；沒有日期的排最後。"""
    projects = [EventProject(**d) for d in store.list_docs(club_id, COLLECTION)]
    return sorted(projects, key=lambda p: (p.stage == "結案", p.date or "9999-99-99", p.created_at))


def prep_tasks_to_tasks(p: EventProject, enabled_departments: list[str], today: date | None = None) -> list[Task]:
    """企劃書的籌備工作轉成待辦：期限 = 活動日期往前推；已經過去的期限改成今天。"""
    if not p.proposal:
        return []
    today = today or date.today()
    event_day = p.event_date()
    fallback = "events" if "events" in enabled_departments else enabled_departments[0]
    out = []
    for t in p.proposal.prep_tasks:
        due = ""
        if event_day:
            d = event_day - timedelta(days=max(0, t.days_before))
            due = max(d, today).isoformat()
        out.append(Task(
            title=t.task, department=t.department if t.department in enabled_departments else fallback,
            due=due, source=f"活動「{p.name}」", project=p.id,
        ))
    return out


def actual_spending(p: EventProject, requests) -> tuple[int, dict[str, int]]:
    """報帳中「所屬活動」符合活動名稱、已核准或已撥款的金額（總計, 依類別）。"""
    name = p.name.strip()
    by_category: dict[str, int] = {}
    for r in requests:
        if r.committed and name and name in (r.activity or ""):
            by_category[r.category] = by_category.get(r.category, 0) + r.amount
    return sum(by_category.values()), by_category


# ---------------------------------------------------------------------------
# 文件
# ---------------------------------------------------------------------------


def _cell(text: object) -> str:
    return str(text).replace("|", "｜").replace("\n", " ")


def _rundown_table(rows: list[RundownItem]) -> list[str]:
    out = ["| 時間 | 流程 | 負責 | 注意事項 |", "|---|---|---|---|"]
    out += [f"| {r.start}–{r.end} | {_cell(r.item)} | {_cell(r.owner)} | {_cell(r.note or '—')} |" for r in rows]
    return out


def _budget_table(lines: list[BudgetLine]) -> list[str]:
    out = ["| 項目 | 類別 | 金額 | 說明 |", "|---|---|---|---|"]
    out += [f"| {_cell(b.item)} | {_cell(b.category)} | {b.amount:,} | {_cell(b.note or '—')} |" for b in lines]
    out.append(f"| **合計** | | **{sum(b.amount for b in lines):,}** | |")
    return out


def proposal_markdown(club_name: str, p: EventProject, dept_name=lambda k: k) -> str:
    pr = p.proposal
    if pr is None:
        return f"# {p.name} 活動企劃書\n\n（尚未產生）\n"
    out = [
        f"# {club_name}｜{p.name} 活動企劃書", "",
        f"**時間：** {p.when()}　**地點：** {p.location or '【待補】'}　**負責人：** {p.owner or '【待補】'}", "",
        "## 一、活動緣起與目的", pr.purpose, "",
        "## 二、活動目標", *[f"- {g}" for g in pr.goals], "",
        "## 三、對象", pr.audience, "",
        "## 四、活動內容", *[f"{i}. {c}" for i, c in enumerate(pr.content, 1)], "",
        "## 五、活動流程", *_rundown_table(p.rundown or pr.rundown), "",
        "## 六、預算規劃", *_budget_table(p.budget_lines or pr.budget), "",
        "## 七、人力配置", *[f"- {s}" for s in pr.staffing], "",
        "## 八、宣傳規劃", *[f"- {s}" for s in pr.promotion], "",
        "## 九、籌備時程",
        "| 工作 | 負責部門 | 完成期限 |", "|---|---|---|",
    ]
    event_day = p.event_date()
    for t in sorted(pr.prep_tasks, key=lambda t: -t.days_before):
        when = (event_day - timedelta(days=t.days_before)).isoformat() if event_day else f"活動前 {t.days_before} 天"
        out.append(f"| {_cell(t.task)} | {_cell(dept_name(t.department))} | {when} |")
    out += ["", "## 十、風險與應變", "| 風險 | 預防與應變 |", "|---|---|"]
    out += [f"| {_cell(r.risk)} | {_cell(r.response)} |" for r in pr.risks]
    out += ["", "## 十一、成效指標", *[f"- {k}" for k in pr.kpis]]
    return "\n".join(out) + "\n"


def rundown_markdown(club_name: str, p: EventProject) -> str:
    out = [f"# {club_name}｜{p.name} 活動細流", "", f"**時間：** {p.when()}　**地點：** {p.location or '【待補】'}", "", "## 流程"]
    out += _rundown_table(p.rundown) if p.rundown else ["（尚未建立細流）"]
    out += ["", "## 工作人員"]
    if p.staff:
        out += ["| 姓名 | 組別／職務 | 值班時段 | 備註 |", "|---|---|---|---|"]
        out += [f"| {_cell(s.name)} | {_cell(s.role or '—')} | {_cell(s.shift or '—')} | {_cell(s.note or '—')} |" for s in p.staff]
    else:
        out.append("（尚未建立工作人員表）")
    return "\n".join(out) + "\n"


def feedback_markdown(form: FeedbackForm) -> str:
    out = [f"# {form.title}", "", form.intro, ""]
    for i, q in enumerate(form.questions, 1):
        mark = "（必填）" if q.required else ""
        out.append(f"{i}. **{q.question}**{mark}　*{q.type}*")
        if q.type == "線性刻度" and len(q.options) >= 2:
            out.append(f"   - 1 = {q.options[0]}，5 = {q.options[-1]}")
        else:
            out += [f"   - {o}" for o in q.options]
    return "\n".join(out) + "\n"


def google_form_text(form: FeedbackForm) -> str:
    """方便逐題複製到 Google 表單的純文字。"""
    lines = [form.title, form.intro, ""]
    for i, q in enumerate(form.questions, 1):
        lines.append(f"{i}. {q.question}［{q.type}{'，必填' if q.required else ''}］")
        if q.type == "線性刻度" and len(q.options) >= 2:
            lines.append(f"   1–5 分：1 = {q.options[0]}，5 = {q.options[-1]}")
        else:
            lines += [f"   ○ {o}" for o in q.options]
        lines.append("")
    return "\n".join(lines)


def report_markdown(club_name: str, p: EventProject, spent: int | None, spent_by_category: dict[str, int]) -> str:
    """spent 為 None 表示沒有財務資料（例如交接資料包未包含財務），經費執行只列預算。"""
    r = p.report
    if r is None:
        return f"# {p.name} 成果報告\n\n（尚未產生）\n"
    planned = sum(b.amount for b in p.budget_lines) or p.budget
    out = [
        f"# {club_name}｜{p.name} 成果報告", "",
        f"**時間：** {p.when()}　**地點：** {p.location or '—'}　**參加人數：** {p.attendance or '—'}"
        + (f"（預計 {p.expected_people}）" if p.expected_people else ""), "",
        "## 成果摘要", r.summary, "",
        "## 目標達成情形", *[f"- {x}" for x in r.results], "",
        "## 活動亮點", *[f"- {x}" for x in r.highlights], "",
        "## 經費執行",
        "| 預算 | 實際支出（已核准報帳） | 差額 |", "|---|---|---|",
        f"| {planned:,} | {spent:,} | {planned - spent:+,} |" if spent is not None else f"| {planned:,} | 未包含財務資料 | — |", "",
    ]
    if spent_by_category:
        out += ["| 類別 | 實際支出 |", "|---|---|", *[f"| {c} | {a:,} |" for c, a in spent_by_category.items()], ""]
    out += [r.budget_review, "", "## 參加者回饋", r.feedback_summary, "",
            "## 檢討與改進", *[f"- {x}" for x in r.improvements], "",
            "## 交接重點", *[f"- {x}" for x in r.handover]]
    return "\n".join(out) + "\n"


# ---------------------------------------------------------------------------
# 名牌 PDF（A4，每頁 8 張，90 × 55 mm）
# ---------------------------------------------------------------------------


def badges_pdf(entries: list[tuple[str, str]], club_name: str, event_name: str) -> bytes:
    """entries：(姓名, 職稱或組別)。需要中文字型（見 export.find_pdf_font）。"""
    from fpdf import FPDF

    from .export import ExportError, _ttc_index, find_pdf_font

    font = find_pdf_font()
    if font is None:
        raise ExportError("這台主機沒有中文字型，無法產生名牌 PDF")
    logging.getLogger("fontTools").setLevel(logging.ERROR)
    regular, bold = font
    pdf = FPDF(format="A4")
    pdf.set_auto_page_break(False)
    pdf.add_font("cjk", "", regular, collection_font_number=_ttc_index(regular))
    pdf.add_font("cjk", "B", bold, collection_font_number=_ttc_index(bold))
    w, h, left, top, gap = 90, 55, 12, 18, 4
    for i, (name, role) in enumerate(entries):
        if i % 8 == 0:
            pdf.add_page()
        col, row = i % 2, (i % 8) // 2
        x, y = left + col * (w + gap), top + row * (h + gap)
        pdf.set_draw_color(180, 176, 166)
        pdf.set_line_width(0.3)
        pdf.rect(x, y, w, h)
        pdf.set_fill_color(45, 74, 107)
        pdf.rect(x, y, w, 9, style="F")
        pdf.set_text_color(255, 255, 255)
        pdf.set_font("cjk", "", 8.5)
        pdf.set_xy(x, y + 1.5)
        pdf.cell(w, 6, f"{club_name}｜{event_name}"[:40], align="C")
        pdf.set_text_color(29, 36, 51)
        pdf.set_font("cjk", "B", 24 if len(name) <= 4 else 18)
        pdf.set_xy(x, y + 18)
        pdf.cell(w, 14, name, align="C")
        if role:
            pdf.set_font("cjk", "", 11)
            pdf.set_text_color(90, 98, 112)
            pdf.set_xy(x, y + 35)
            pdf.cell(w, 8, role, align="C")
    return bytes(pdf.output())

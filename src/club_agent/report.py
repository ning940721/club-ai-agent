"""將 Agent 產出轉為社團幹部可直接閱讀、分享的 Markdown 報告。"""

from __future__ import annotations

from .schemas import Advice, CampaignResult, DiagnosisReport, MeetingAnswer, MeetingSummary, ProgressBrief


def _cell(text: object) -> str:
    """表格儲存格內不能有換行或直線符號，否則 Markdown 表格會跑版。"""
    return str(text).replace("|", "｜").replace("\r", " ").replace("\n", " ")


def diagnosis_markdown(club_name: str, report: DiagnosisReport) -> str:
    out = [f"# {club_name} 社群數據診斷報告", "", "## 總結", report.summary, "", "## 流量瓶頸與宣傳盲點"]
    for f in report.bottlenecks:
        out.append(f"- **{f.title}**（影響：{f.impact}）— {f.evidence}")
    out += ["", "## 受眾洞察", *[f"- {i}" for i in report.audience_insights]]
    out += ["", "## 建議貼文主題分配", "| 主題 | 占比 | 理由 |", "|---|---|---|"]
    out += [f"| {_cell(t.topic)} | {t.share_percent}% | {_cell(t.rationale)} |" for t in report.topic_allocation]
    out += ["", "## 最佳發文時機", "| 平台 | 星期 | 時段 | 理由 |", "|---|---|---|---|"]
    out += [f"| {_cell(s.platform)} | {_cell(s.weekday)} | {_cell(s.time_range)} | {_cell(s.rationale)} |" for s in report.best_posting_times]
    out += ["", "## 優先改善行動", *[f"{i}. {a}" for i, a in enumerate(report.priority_actions, 1)]]
    if report.data_gaps:
        out += ["", "## 數據限制", *[f"- {g}" for g in report.data_gaps]]
    return "\n".join(out) + "\n"


def campaign_markdown(result: CampaignResult) -> str:
    p = result.plan
    status = "✅ 通過審查" if result.approved else "⚠️ 未通過審查（已達最大修訂輪數，請人工檢視）"
    out = [
        f"# {p.campaign_name}",
        "",
        f"> {status}｜審查輪數：{result.rounds}｜最終評分：{result.critiques[-1].overall_score:.2f} / 5",
        "",
        f"**核心訊息：** {p.key_message}",
        "",
        f"**目標受眾：** {p.target_audience}",
        "",
        "## 宣傳時程（行銷甘特圖）",
        "| 階段 | 期間 | 目標 | 工作項目 | 負責 |",
        "|---|---|---|---|---|",
    ]
    for ph in p.timeline:
        out.append(
            f"| {_cell(ph.phase)} | D{ph.start_offset_days:+d} ~ D{ph.end_offset_days:+d} | {_cell(ph.goal)} "
            f"| {_cell('；'.join(ph.tasks))} | {_cell(ph.owner)} |"
        )
    out += ["", "## 各平台貼文"]
    for i, post in enumerate(p.posts, 1):
        out += [
            "",
            f"### {i}. {post.platform}｜{post.phase}｜{post.format}",
            f"*建議發布時間：{post.suggested_publish_time}*",
            "",
            f"**{post.hook}**",
            "",
            post.body,
            "",
            f"👉 {post.cta}",
            "",
            " ".join(post.hashtags),
            "",
            f"🎨 視覺建議：{post.visual_suggestion}",
        ]
    if p.story_scripts:
        out += ["", "## 限時動態腳本"]
        for s in p.story_scripts:
            out += ["", f"### {s.title}", *[f"{i}. {fr}" for i, fr in enumerate(s.frames, 1)], f"- 互動設計：{s.interaction}"]
    out += ["", "## 預算說明", p.budget_notes, "", "## 成效指標（KPI）", *[f"- {k}" for k in p.kpis]]
    out += ["", "## 審查紀錄"]
    for n, c in enumerate(result.critiques, 1):
        out += ["", f"### 第 {n} 輪（平均 {c.overall_score:.2f}，{'通過' if c.approved else '未通過'}）"]
        out += [f"- {s.criterion}：{s.score} 分 — {s.comment}" for s in c.scores]
        if c.revision_requests:
            out += ["", "修改要求：", *[f"- {r}" for r in c.revision_requests]]
    if p.references_used:
        out += ["", "## 參考知識庫", *[f"- {r}" for r in p.references_used]]
    return "\n".join(out) + "\n"


def advice_markdown(department_name: str, question: str, advice: Advice) -> str:
    out = [f"# {department_name}部門顧問建議", "", f"> **問題：** {question}", "", "## 建議摘要", advice.summary]
    if advice.steps:
        out += ["", "## 行動步驟", "| # | 步驟 | 做法 | 負責 | 時程 |", "|---|---|---|---|---|"]
        out += [
            f"| {i} | {_cell(s.step)} | {_cell(s.detail)} | {_cell(s.owner)} | {_cell(s.timing)} |"
            for i, s in enumerate(advice.steps, 1)
        ]
    for d in advice.deliverables:
        out += ["", f"## 📄 {d.title}", "", d.content]
    if advice.coordination:
        out += ["", "## 跨部門協作", *[f"- **{c.department}**：{c.what}" for c in advice.coordination]]
    if advice.risks:
        out += ["", "## 注意事項", *[f"- {r}" for r in advice.risks]]
    if advice.info_needed:
        out += ["", "## 補充這些資訊，建議會更精準", *[f"- {i}" for i in advice.info_needed]]
    return "\n".join(out) + "\n"


def meeting_summary_markdown(title: str, meeting_date: str, s: MeetingSummary, dept_name=lambda k: k) -> str:
    out = [f"# {title}（{meeting_date}）", "", "## 重點摘要", s.summary]
    if s.decisions:
        out += ["", "## 決議", *[f"- {d}" for d in s.decisions]]
    if s.action_items:
        out += ["", "## 待辦事項", "| 事項 | 負責人 | 部門 | 期限 |", "|---|---|---|---|"]
        out += [
            f"| {_cell(a.task)} | {_cell(a.owner or '—')} | {_cell(dept_name(a.department))} | {_cell(a.due or '—')} |"
            for a in s.action_items
        ]
    if s.key_dates:
        out += ["", "## 重要日期"]
        out += [f"- **{k.date}** {' '.join(x for x in (k.time, k.location) if x)}｜{k.event}" for k in s.key_dates]
    if s.open_questions:
        out += ["", "## 待討論", *[f"- {q}" for q in s.open_questions]]
    return "\n".join(out) + "\n"


def meeting_answer_markdown(question: str, a: MeetingAnswer) -> str:
    out = [f"**Q：{question}**", "", f"**A：** {a.answer}"]
    if a.sources:
        out += ["", "依據："]
        out += [f"- {src.date}｜{src.title}：「{src.excerpt}」" for src in a.sources]
    return "\n".join(out) + "\n"


def progress_brief_markdown(club_name: str, today: str, b: ProgressBrief) -> str:
    out = [f"# {club_name} 進度彙整與會議議程（{today}）", "", "## 總覽", b.overview, "", "## 各部門進度"]
    for d in b.departments:
        out += ["", f"### {d.department}", d.progress]
        out += [f"- 進行中：{x}" for x in d.doing]
        out += [f"- ⚠️ {x}" for x in d.blockers]
    if b.agenda:
        total = sum(a.minutes for a in b.agenda)
        out += ["", f"## 下次會議議程（約 {total} 分鐘）", "| # | 議題 | 類型 | 部門 | 時間 | 目標 |", "|---|---|---|---|---|---|"]
        out += [
            f"| {i} | {_cell(a.topic)} | {a.kind} | {_cell(a.department)} | {a.minutes} 分 | {_cell(a.goal)} |"
            for i, a in enumerate(b.agenda, 1)
        ]
    if b.decisions_needed:
        out += ["", "## 需要決定的事", *[f"- {x}" for x in b.decisions_needed]]
    if b.reminders:
        out += ["", "## 近期提醒", *[f"- {x}" for x in b.reminders]]
    return "\n".join(out) + "\n"

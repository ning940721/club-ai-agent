import io
import zipfile
from datetime import date

from club_agent.agents import MeetingQA, MeetingSummarizer, ProgressReporter
from club_agent.departments import ClubSettings
from club_agent.meetings import (
    MeetingDoc,
    build_retriever,
    clean_line_chat,
    extract_text,
    is_line_export,
    key_dates_digest,
    merge_summaries,
    prepare_text,
    recent_summaries_digest,
    split_parts,
)
from club_agent.report import meeting_answer_markdown, meeting_summary_markdown, progress_brief_markdown
from club_agent.schemas import (
    ActionItem,
    AgendaItem,
    DepartmentStatus,
    KeyDate,
    MeetingAnswer,
    MeetingSummary,
    ProgressBrief,
    SourceRef,
)

from conftest import FakeLLM

LINE_EXPORT = """﻿[LINE] 幹部群組的聊天記錄
儲存日期：2026/10/04 12:00

2026/10/03（五）
21:05\t小明\t下次開會改到 12/4 晚上七點，在社辦
21:06\t小華\t[貼圖]
21:07\t小華\t好
21:08\t小美\t已收回訊息
"""


def make_summary(**kw) -> MeetingSummary:
    data = dict(
        title="第 5 次幹部會",
        summary="討論成果展",
        decisions=["成果展預算 3 萬元"],
        action_items=[ActionItem(task="找贊助", owner="小明", department="pr", due="2026-11-01")],
        key_dates=[KeyDate(event="下次幹部會", date="2026-12-04", time="19:00", location="社辦")],
        open_questions=["場地未定"],
    )
    data.update(kw)
    return MeetingSummary(**data)


def make_docx(paragraphs: list[str]) -> bytes:
    ns = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    body = "".join(f"<w:p><w:r><w:t>{p}</w:t></w:r></w:p>" for p in paragraphs)
    xml = f'<?xml version="1.0" encoding="UTF-8"?><w:document xmlns:w="{ns}"><w:body>{body}</w:body></w:document>'
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("word/document.xml", xml)
    return buf.getvalue()


def test_extract_text_formats():
    assert extract_text("a.docx", make_docx(["第一段", "第二段"])) == "第一段\n第二段"
    assert extract_text("a.txt", "你好".encode("cp950")) == "你好"
    try:
        extract_text("a.pdf", b"")
        raise AssertionError
    except ValueError as e:
        assert ".docx" in str(e)


def test_line_cleaning():
    assert is_line_export(LINE_EXPORT)
    cleaned = prepare_text(LINE_EXPORT, "會議記錄")  # 自動偵測 LINE 匯出檔
    assert "下次開會改到 12/4" in cleaned and "[貼圖]" not in cleaned and "已收回訊息" not in cleaned
    assert "小華\t好" in clean_line_chat(LINE_EXPORT)


def test_split_and_merge():
    parts = split_parts("a" * 10 + "\n" + "b" * 25 + "\n" + "c" * 5, max_chars=12)
    assert all(len(p) <= 12 for p in parts) and "".join(parts).replace("\n", "") == "a" * 10 + "b" * 25 + "c" * 5
    merged = merge_summaries([make_summary(), make_summary(summary="第二段", decisions=["成果展預算 3 萬元", "延後招生"])])
    assert merged.decisions == ["成果展預算 3 萬元", "延後招生"]
    assert len(merged.action_items) == 1 and "（第 2 段）第二段" in merged.summary


def test_retriever_and_digests():
    docs = [
        MeetingDoc(title="第 5 次幹部會", date="2026-10-03", text="討論成果展場地與預算", summary=make_summary()),
        MeetingDoc(title="LINE 群組", date="2026-10-02", text="週末要不要去外拍", source_type="LINE 對話"),
    ]
    hits = build_retriever(docs).search("下次幹部會什麼時候", k=1)
    assert hits[0].source == "第 5 次幹部會"
    assert "2026-12-04 19:00 社辦｜下次幹部會" in key_dates_digest(docs)
    assert "決議：成果展預算 3 萬元" in recent_summaries_digest(docs)
    assert build_retriever([]) is None


def test_summarizer_maps_unknown_departments_and_splits_long_text():
    settings = ClubSettings.default(["president", "minutes", "pr"])
    bad = make_summary(action_items=[ActionItem(task="訂便當", owner="", department="catering", due="")])
    llm = FakeLLM({MeetingSummary: [bad, make_summary(summary="後半")]})
    long_text = ("會議內容" * 10 + "\n") * 2000  # 約 9 萬字，會分成兩段
    result = MeetingSummarizer(llm).run(settings, "長會議", "2026-10-03", "會議記錄", long_text)
    assert len(llm.calls) == 2 and 'part="1/2"' in llm.calls[0][1]
    assert result.action_items[0].department == "president"
    assert "- pr：公關" in llm.calls[0][1]


def test_meeting_qa_prompt():
    docs = [MeetingDoc(title="第 5 次幹部會", date="2026-10-03", text="下次開會 12/4", summary=make_summary())]
    answer = MeetingAnswer(found=True, answer="12/4 19:00", sources=[SourceRef(title="第 5 次幹部會", date="2026-10-03", excerpt="下次開會 12/4")])
    llm = FakeLLM({MeetingAnswer: [answer]})
    result = MeetingQA(llm).run("下次開會是什麼時候？", docs, build_retriever(docs), date(2026, 10, 4))
    assert result.answer == "12/4 19:00"
    prompt = llm.calls[0][1]
    assert "<today>2026-10-04</today>" in prompt and "2026-12-04 19:00 社辦｜下次幹部會" in prompt
    md = meeting_answer_markdown("下次開會？", result)
    assert "**A：** 12/4 19:00" in md and "「下次開會 12/4」" in md


def test_progress_reporter_prompt(club):
    brief = ProgressBrief(
        overview="整體順利",
        departments=[DepartmentStatus(department="公關", doing=["找贊助"], progress="進行中", blockers=["回覆率低"])],
        agenda=[AgendaItem(topic="贊助進度", department="公關", kind="討論", minutes=15, goal="決定下一步")],
        decisions_needed=["是否延長截止"],
        reminders=["12/4 幹部會"],
    )
    llm = FakeLLM({ProgressBrief: [brief]})
    ProgressReporter(llm).run(club, ClubSettings.default(), "[公關]\n- 待辦｜找贊助", "- 行銷｜企劃", "決議：…", date(2026, 10, 4))
    prompt = llm.calls[0][1]
    assert "[公關]" in prompt and "- 行銷｜企劃" in prompt and "<today>2026-10-04</today>" in prompt
    md = progress_brief_markdown("測試社", "2026-10-04", brief)
    assert "約 15 分鐘" in md and "需要協助：回覆率低" in md


def test_meeting_summary_markdown():
    md = meeting_summary_markdown("幹部會", "2026-10-03", make_summary(), {"pr": "公關"}.get)
    assert "| 找贊助 | 小明 | 公關 | 2026-11-01 |" in md and "**2026-12-04** 19:00 社辦｜下次幹部會" in md


def test_demote_headings():
    from club_agent.web.context import demote_headings

    assert demote_headings("# 標題\n## 小節\n內文 # 不是標題\n###### 最小") == "### 標題\n#### 小節\n內文 # 不是標題\n###### 最小"

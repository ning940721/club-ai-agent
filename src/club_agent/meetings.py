"""會議記錄與 LINE 對話記錄的匯入、整理與檢索。

- 支援貼上文字或上傳 .txt／.md／.docx；LINE 用「傳送聊天記錄」匯出的 .txt 會自動清理貼圖、照片等雜訊。
- 太長的記錄會分段摘要再合併，避免超過模型輸出上限。
- 問答時以 BM25 從所有記錄中找出相關段落，再交給 AI 回答並附上原文出處。
"""

from __future__ import annotations

import io
import re
import uuid
import zipfile
from datetime import datetime
from xml.etree import ElementTree

from pydantic import BaseModel, Field

from .metrics import decode_csv_bytes
from .retriever import BM25Retriever, Chunk
from .schemas import AGENDA_RESULTS, AgendaCheck, MeetingSummary

COLLECTION = "meetings"
SUMMARY_PART_CHARS = 60_000  # 每段送給 AI 摘要的最大字數
CHUNK_CHARS = 700  # 問答檢索時每個段落的大約字數

SOURCE_TYPES = ("會議記錄", "LINE 對話", "其他")
LINE_NOISE = re.compile(r"^\s*(\d{1,2}:\d{2}\s+)?(\S+\s+)?\[(貼圖|照片|影片|檔案|語音訊息|相簿|Sticker|Photo|Video|File)\]\s*$")
LINE_SYSTEM = re.compile(r"(已收回訊息|unsent a message|加入聊天|離開聊天|已邀請)")


class MeetingDoc(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    title: str
    date: str = Field(description="會議或對話日期 YYYY-MM-DD")
    source_type: str = "會議記錄"
    text: str
    plan_id: str = Field(default="", description="對照的會議議程（MeetingPlan 的日期）；沒有對照時為空")
    summary: MeetingSummary | None = None
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))


# ---------------------------------------------------------------------------
# 讀取與清理
# ---------------------------------------------------------------------------


def docx_text(data: bytes) -> str:
    """不依賴額外套件，直接從 .docx 的 XML 取出段落文字。"""
    ns = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        root = ElementTree.fromstring(z.read("word/document.xml"))
    paragraphs = []
    for p in root.iter(f"{ns}p"):
        text = "".join(t.text or "" for t in p.iter(f"{ns}t"))
        if text.strip():
            paragraphs.append(text)
    return "\n".join(paragraphs)


def extract_text(filename: str, data: bytes) -> str:
    name = filename.lower()
    if name.endswith(".docx"):
        return docx_text(data)
    if name.endswith((".txt", ".md", ".csv")):
        return decode_csv_bytes(data)
    raise ValueError("目前支援 .txt、.md、.docx 檔；Google 文件請先下載成 .docx")


def is_line_export(text: str) -> bool:
    head = text.lstrip("﻿")[:200]
    return head.startswith("[LINE]") or "聊天記錄" in head or "Chat history" in head


def clean_line_chat(text: str) -> str:
    """移除貼圖、照片、收回訊息等不含資訊的行。"""
    kept = [line for line in text.splitlines() if not LINE_NOISE.match(line) and not LINE_SYSTEM.search(line)]
    return "\n".join(kept).strip()


def prepare_text(text: str, source_type: str) -> str:
    text = text.lstrip("﻿").strip()
    if source_type == "LINE 對話" or is_line_export(text):
        return clean_line_chat(text)
    return text


def split_parts(text: str, max_chars: int = SUMMARY_PART_CHARS) -> list[str]:
    """依行切成不超過 max_chars 的段落（單行超長時硬切）。"""
    parts, buf, size = [], [], 0
    for line in text.splitlines():
        while len(line) > max_chars:
            if buf:
                parts.append("\n".join(buf))
                buf, size = [], 0
            parts.append(line[:max_chars])
            line = line[max_chars:]
        if size + len(line) + 1 > max_chars and buf:
            parts.append("\n".join(buf))
            buf, size = [], 0
        buf.append(line)
        size += len(line) + 1
    if buf:
        parts.append("\n".join(buf))
    return parts or [""]


def merge_summaries(summaries: list[MeetingSummary]) -> MeetingSummary:
    """合併分段摘要（不再呼叫 AI，避免額外用量）。"""
    if len(summaries) == 1:
        return summaries[0]

    def dedupe(items):
        seen, out = set(), []
        for item in items:
            key = item if isinstance(item, str) else item.model_dump_json()
            if key not in seen:
                seen.add(key)
                out.append(item)
        return out

    return MeetingSummary(
        title=summaries[0].title,
        summary="\n".join(f"（第 {i} 段）{s.summary}" for i, s in enumerate(summaries, 1)),
        decisions=dedupe([d for s in summaries for d in s.decisions]),
        action_items=dedupe([a for s in summaries for a in s.action_items]),
        key_dates=dedupe([k for s in summaries for k in s.key_dates]),
        open_questions=dedupe([q for s in summaries for q in s.open_questions]),
        agenda_review=merge_agenda_reviews([s.agenda_review for s in summaries]),
    )


def merge_agenda_reviews(reviews: list[list[AgendaCheck]]) -> list[AgendaCheck]:
    """分段摘要時，同一個議題取進度最多的那段（已決議 > 已討論 > 未討論），並保留議程順序。"""
    best: dict[str, AgendaCheck] = {}
    for review in reviews:
        for c in review:
            current = best.get(c.topic)
            if current is None or AGENDA_RESULTS.index(c.result) < AGENDA_RESULTS.index(current.result):
                best[c.topic] = c
    return list(best.values())


# ---------------------------------------------------------------------------
# 儲存
# ---------------------------------------------------------------------------


def save_meeting(store, club_id: str, doc: MeetingDoc) -> None:
    store.put_doc(club_id, COLLECTION, doc.id, doc.model_dump())


def delete_meeting(store, club_id: str, doc_id: str) -> None:
    store.delete_doc(club_id, COLLECTION, doc_id)


def list_meetings(store, club_id: str) -> list[MeetingDoc]:
    """由新到舊。"""
    docs = [MeetingDoc(**d) for d in store.list_docs(club_id, COLLECTION)]
    return sorted(docs, key=lambda d: (d.date, d.created_at), reverse=True)


# ---------------------------------------------------------------------------
# 給 AI 參考的整理
# ---------------------------------------------------------------------------


def key_dates_digest(docs: list[MeetingDoc]) -> str:
    rows = []
    for d in docs:
        if d.summary:
            for k in d.summary.key_dates:
                extra = " ".join(x for x in (k.time, k.location) if x)
                rows.append((k.date, f"- {k.date} {extra}｜{k.event}（出自：{d.title}，{d.date}）"))
    return "\n".join(line for _, line in sorted(rows)) or "（尚未整理出任何日期）"


def recent_summaries_digest(docs: list[MeetingDoc], limit: int = 3) -> str:
    lines = []
    for d in docs[:limit]:
        if not d.summary:
            continue
        s = d.summary
        lines.append(f"[{d.date} {d.title}] {s.summary}")
        lines += [f"  決議：{x}" for x in s.decisions]
        lines += [f"  待辦：{a.task}（{a.owner or '未指定'}，{a.due or '無期限'}）" for a in s.action_items]
        lines += [f"  待討論：{q}" for q in s.open_questions]
        lines += [f"  議程未完成：{c.topic}（{c.result}）" for c in s.unresolved_agenda()]
    return "\n".join(lines) or "（沒有已整理的會議記錄）"


def build_retriever(docs: list[MeetingDoc]) -> BM25Retriever | None:
    chunks: list[Chunk] = []
    for d in docs:
        heading = f"{d.date}｜{d.title}"
        if d.summary:
            s = d.summary
            summary_text = "\n".join(
                [s.summary, *[f"決議：{x}" for x in s.decisions], *[f"{k.event}：{k.date} {k.time} {k.location}" for k in s.key_dates]]
            )
            chunks.append(Chunk(source=d.title, heading=f"{heading}｜重點彙整", text=summary_text))
        for part in split_parts(d.text, CHUNK_CHARS):
            if part.strip():
                chunks.append(Chunk(source=d.title, heading=heading, text=part))
    return BM25Retriever(chunks) if chunks else None

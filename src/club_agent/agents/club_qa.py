"""社團問答 Agent：從會議記錄、成果分享與待辦中找答案，例如「上次開會決定了什麼？」。

和 MeetingQA 的差別：資料來源涵蓋全社團（不只會議記錄），並固定附上最近的會議重點與
未完成待辦，讓「上次」「目前」這類沒有關鍵字的問題也找得到答案。
"""

from __future__ import annotations

from datetime import date

from ..llm import LLM
from ..meetings import MeetingDoc, build_retriever, key_dates_digest, recent_summaries_digest
from ..retriever import BM25Retriever, Chunk, format_context, split_markdown
from ..schemas import MeetingAnswer
from ..store import Record

SYSTEM_PROMPT = """你是學生社團的資料小幫手，根據社團的會議記錄、各部門的紀錄與待辦清單回答幹部的問題。

工作原則：
- 只能根據提供的資料回答；找不到答案時 found 設為 false，說明資料中沒有提到，並建議可以去哪裡補資料，絕不猜測。
- 「上次開會」指 <recent_meetings> 中日期最新、且不晚於今天的那一場。
- 同一件事有多筆資料時以日期最新的為準，必要時說明曾經改過。
- 問到「下次」「最近」等相對時間時，以今天的日期判斷。
- 回答要簡短直接，條列重點即可；在 sources 引用原文片段（title 填資料標題，date 填資料日期）。
- 全部使用繁體中文。"""


def club_retriever(docs: list[MeetingDoc], records: list[Record], settings_name=lambda k: k) -> BM25Retriever | None:
    """把會議記錄與成果分享切成段落一起檢索。"""
    meeting = build_retriever(docs)
    chunks: list[Chunk] = list(meeting.chunks) if meeting else []
    for r in records:
        if r.kind == "meeting":
            continue  # 會議重點已包含在會議記錄裡
        source = f"{r.created_at[:10]}｜{settings_name(r.department)}｜{r.title}"
        chunks += split_markdown(source, r.markdown)
    return BM25Retriever(chunks) if chunks else None


class ClubQA:
    def __init__(self, llm: LLM):
        self.llm = llm

    def build_prompt(
        self,
        question: str,
        docs: list[MeetingDoc],
        retriever: BM25Retriever | None,
        tasks_text: str,
        today: date,
    ) -> str:
        context = format_context(retriever.search(question, k=8)) if retriever else "（沒有任何紀錄）"
        return f"""<today>{today.isoformat()}</today>

<recent_meetings>
{recent_summaries_digest(docs, limit=3)}
</recent_meetings>

<key_dates>
{key_dates_digest(docs)}
</key_dates>

<open_tasks>
{tasks_text}
</open_tasks>

<related_records>
{context}
</related_records>

<question>
{question}
</question>"""

    def run(
        self,
        question: str,
        docs: list[MeetingDoc],
        retriever: BM25Retriever | None,
        tasks_text: str,
        today: date | None = None,
    ) -> MeetingAnswer:
        prompt = self.build_prompt(question, docs, retriever, tasks_text, today or date.today())
        return self.llm.structured(SYSTEM_PROMPT, prompt, MeetingAnswer)

"""會議記錄 Agent：重點彙整（MeetingSummarizer）與記錄問答（MeetingQA）。"""

from __future__ import annotations

from datetime import date

from ..departments import ClubSettings
from ..llm import LLM
from ..meetings import MeetingDoc, key_dates_digest, merge_summaries, split_parts
from ..retriever import BM25Retriever
from ..retriever import format_context
from ..schemas import MeetingAnswer, MeetingSummary

SUMMARY_PROMPT = """你是學生社團的會議記錄秘書，負責把會議記錄或 LINE 群組對話整理成清楚的重點。

工作原則：
- 只根據提供的內容整理，不要推測或補充原文沒有的資訊。
- 決議只列「已經確定」的事；還在討論、沒有結論的放在 open_questions。
- 待辦事項要具體，負責人與期限照原文填寫，沒寫就留空。
- 日期一律寫成 YYYY-MM-DD；原文只寫月日（例如 12/4）時，依記錄日期推算年份。
- 待辦的 department 必須使用下方部門清單中的代號。
- 全部使用繁體中文。"""

QA_PROMPT = """你是學生社團的會議記錄小幫手，根據社團的會議記錄與 LINE 對話記錄回答幹部的問題。

工作原則：
- 只能根據提供的記錄回答；記錄中找不到答案時，found 設為 false，並說明記錄中沒有提到，絕不猜測。
- 同一件事有多筆記錄時，以日期最新的為準，必要時說明曾經改過。
- 問到「下次」「最近」等相對時間時，以今天的日期判斷。
- 回答要簡短直接（例如：「下次幹部會是 12/4（四）19:00，在社辦。」），並在 sources 引用原文片段。
- 全部使用繁體中文。"""


def department_codes(settings: ClubSettings) -> str:
    return "\n".join(f"- {k}：{settings.name(k)}" for k in settings.enabled_keys())


class MeetingSummarizer:
    def __init__(self, llm: LLM):
        self.llm = llm

    def build_prompt(self, settings: ClubSettings, title: str, meeting_date: str, source_type: str, text: str, part: str = "") -> str:
        return f"""<departments>
{department_codes(settings)}
</departments>

<record title="{title}" date="{meeting_date}" type="{source_type}"{f' part="{part}"' if part else ''}>
{text}
</record>

請整理這份{source_type}的重點。"""

    def run(self, settings: ClubSettings, title: str, meeting_date: str, source_type: str, text: str) -> MeetingSummary:
        parts = split_parts(text)
        summaries = []
        for i, part in enumerate(parts, 1):
            label = f"{i}/{len(parts)}" if len(parts) > 1 else ""
            prompt = self.build_prompt(settings, title, meeting_date, source_type, part, label)
            summaries.append(self.llm.structured(SUMMARY_PROMPT, prompt, MeetingSummary))
        summary = merge_summaries(summaries)
        enabled = set(settings.enabled_keys())
        fallback = "minutes" if "minutes" in enabled else settings.enabled_keys()[0]
        for item in summary.action_items:
            if item.department not in enabled:
                item.department = "president" if "president" in enabled else fallback
        return summary


class MeetingQA:
    def __init__(self, llm: LLM):
        self.llm = llm

    def build_prompt(self, question: str, docs: list[MeetingDoc], retriever: BM25Retriever | None, today: date) -> str:
        context = format_context(retriever.search(question, k=6)) if retriever else "（沒有任何記錄）"
        return f"""<today>{today.isoformat()}</today>

<key_dates>
{key_dates_digest(docs)}
</key_dates>

<records>
{context}
</records>

<question>
{question}
</question>"""

    def run(self, question: str, docs: list[MeetingDoc], retriever: BM25Retriever | None, today: date | None = None) -> MeetingAnswer:
        prompt = self.build_prompt(question, docs, retriever, today or date.today())
        return self.llm.structured(QA_PROMPT, prompt, MeetingAnswer)

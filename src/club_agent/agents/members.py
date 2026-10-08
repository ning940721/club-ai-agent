"""人資 Agent：面試題目與評分標準、依部門紀錄整理幹部交接手冊。"""

from __future__ import annotations

from ..llm import LLM
from ..schemas import ClubProfile, HandoverManual, InterviewKit

INTERVIEW_PROMPT = """你是學生社團的人資顧問，替幹部準備招生或幹部甄選的面試。

工作原則：
- 題目依應徵的職位設計，由破冰到深入，能看出動機、投入時間、團隊合作與該職位需要的能力。
- 不要詢問與能力無關的私人問題（家庭、感情、宗教、政治、外貌等），並在 tips 提醒面試官。
- 評分標準具體，讓不同面試官打分一致。
- 全部使用繁體中文。"""

HANDOVER_PROMPT = """你是學生社團的組織顧問，替即將卸任的幹部整理交接手冊，讓下一屆可以快速上手。

工作原則：
- 依提供的部門紀錄（待辦、分享的成果、會議決議、行事曆、部門細節）整理；紀錄中沒有的內容寫【待補】，不要捏造。
- 年度時程依紀錄中的日期歸納；操作步驟要具體到新手能照著做。
- 帳號密碼等敏感資訊不要寫進手冊，標示【待補：私下移交】。
- 經驗與教訓要引用紀錄中的具體事件（例如逾期的任務、會議中的決議）。
- 全部使用繁體中文。"""


class PeopleAdvisor:
    def __init__(self, llm: LLM):
        self.llm = llm

    def interview_kit(self, club: ClubProfile, role: str, details: str = "", extra: str = "") -> InterviewKit:
        prompt = f"""<club>{club.name}：{club.positioning}；主要對象：{club.target_audience}</club>

<role>{role}</role>

<role_details>
{details or "（未填寫）"}
</role_details>

<extra_instructions>
{extra or "（無）"}
</extra_instructions>

請設計面試題目與評分標準。"""
        return self.llm.structured(INTERVIEW_PROMPT, prompt, InterviewKit)

    def handover(self, club: ClubProfile, department: str, records_text: str, extra: str = "") -> HandoverManual:
        prompt = f"""<club>{club.name}：{club.positioning}</club>

<department>{department}</department>

<department_records>
{records_text}
</department_records>

<extra_notes>
{extra or "（無）"}
</extra_notes>

請整理這個部門的交接手冊。"""
        return self.llm.structured(HANDOVER_PROMPT, prompt, HandoverManual)
